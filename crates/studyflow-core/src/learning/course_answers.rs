use std::collections::HashSet;

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    attempt_history::scoped_summaries,
    request_fingerprints,
    study_sessions::{self, Round},
    submissions,
};
use crate::{
    application::write_contract::{atomic_write, validate_key, StoredReceipt},
    courses::catalog,
    infrastructure::{events, StorageError},
    workspace::Workspace,
};

fn action(formal: Option<&Value>) -> &'static str {
    match formal.map(|row| row["status"].as_str().unwrap_or_default()) {
        None => "FIRST",
        Some("NEEDS_REVISION") => "REVISION",
        Some("RETEST_REQUIRED") => "RETEST",
        Some(_) => "LOCKED",
    }
}

fn exercises(
    db: &Connection,
    course: &str,
    round: Option<&Round>,
) -> Result<Vec<Value>, StorageError> {
    let lessons = match round {
        Some(round) => round.snapshot["lessons"].as_array().unwrap().clone(),
        None => catalog::rows(db, course)?,
    };
    Ok(lessons
        .into_iter()
        .flat_map(|mut lesson| {
            lesson["exercises"]
                .take()
                .as_array()
                .cloned()
                .unwrap_or_default()
        })
        .collect())
}

fn ids_from(exercises: &[Value]) -> Vec<String> {
    exercises
        .iter()
        .map(|row| row["id"].as_str().unwrap().to_owned())
        .collect()
}

fn get_round(
    db: &Connection,
    course: &str,
    study: Option<&str>,
    active: bool,
) -> Result<Option<Round>, StorageError> {
    catalog::course(db, course)?;
    match study {
        Some(id) => study_sessions::require(db, id, Some(course), active).map(Some),
        None => match study_sessions::current(db, course)? {
            Some(round) if active && round.abandoned.is_some() => {
                Err(StorageError::new("STUDY_ROUND_SUPERSEDED"))
            }
            result => Ok(result),
        },
    }
}

pub fn read(db: &Connection, course: &str, study: Option<&str>) -> Result<Value, StorageError> {
    let round = get_round(db, course, study, false)?;
    let ids = match &round {
        Some(round) => round.ids(),
        None => ids_from(&exercises(db, course, None)?),
    };
    let mut latest = scoped_summaries(db, &ids, round.as_ref().map(Round::scope), true)?;
    let mut answers = Vec::with_capacity(ids.len());
    for id in ids {
        let (formal, draft) = latest.remove(&id).unwrap_or_default();
        let mut action = action(formal.as_ref());
        let retest = match &formal {
            Some(row) => {
                crate::reviews::retest_task(db, row["id"].as_str(), row["retest_task_id"].as_str())?
            }
            None => None,
        };
        if action == "RETEST" && retest.is_none() {
            action = "WAITING_RETEST_TASK";
        }
        let draft = draft.filter(|draft| {
            action != "LOCKED"
                && formal
                    .as_ref()
                    .is_none_or(|formal| draft["parent_submission_id"] == formal["id"])
        });
        let read = |item: Value| submissions::detail(db, item["id"].as_str().unwrap(), false);
        answers.push(json!({"exercise_id":id,"action":action,"retest_task":retest,"draft":draft.map(read).transpose()?,"submission":formal.map(read).transpose()?}));
    }
    Ok(
        json!({"course_id":course,"study_session_id":round.map(|round|round.id),"answers":answers,"next_action":"在本课统一保存或提交；批改仍按题保留原答案和版本链。"}),
    )
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Operation {
    Save,
    Submit,
    Essay,
}

impl Operation {
    fn name(self) -> &'static str {
        match self {
            Self::Save => "DRAFT_SAVE",
            Self::Submit => "SUBMIT",
            Self::Essay => "ESSAY_SUBMIT",
        }
    }
    fn submitted(self) -> bool {
        self != Self::Save
    }
}

pub struct WriteRequest<'a> {
    pub course: &'a str,
    pub study: Option<&'a str>,
    pub key: &'a str,
    pub source: &'a str,
    pub operation: Operation,
    pub answers: &'a Value,
}

fn normalize(request: &WriteRequest<'_>) -> Result<Vec<Value>, StorageError> {
    validate_key(request.key)?;
    if request.source.is_empty() || request.source.chars().count() > 32 {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let entries = request
        .answers
        .as_array()
        .filter(|rows| (1..=500).contains(&rows.len()))
        .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?;
    let mut seen = HashSet::new();
    let ids = [
        "submission_id",
        "parent_submission_id",
        "task_id",
        "retest_task_id",
    ];
    for row in entries {
        let fields = row
            .as_object()
            .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?;
        if fields.keys().any(|key| {
            !matches!(
                key.as_str(),
                "exercise_id" | "answer_text" | "expected_version"
            ) && !ids.contains(&key.as_str())
        }) {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        let id = row["exercise_id"]
            .as_str()
            .filter(|id| !id.is_empty())
            .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?;
        if !seen.insert(id)
            || ids
                .iter()
                .any(|name| !row[*name].is_null() && row[*name].as_str().is_none_or(str::is_empty))
        {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        if (!row["expected_version"].is_null() || !row["submission_id"].is_null())
            && row["expected_version"]
                .as_i64()
                .is_none_or(|version| version < 1)
        {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        let text = row["answer_text"]
            .as_str()
            .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?;
        if request.operation == Operation::Essay && text.chars().count() > 100000 {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        if request.operation.submitted()
            && text
                .trim_matches(|ch: char| ch.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&ch))
                .is_empty()
        {
            return Err(StorageError::new("INCOMPLETE_COURSE_ANSWERS"));
        }
    }
    Ok(entries.clone())
}

pub fn write(workspace: &Workspace, request: WriteRequest<'_>) -> Result<Value, StorageError> {
    let entries = normalize(&request)?;
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        write_batch(db, &request, &entries)
    })
}

fn write_batch(
    db: &Connection,
    request: &WriteRequest<'_>,
    entries: &[Value],
) -> Result<Value, StorageError> {
    let WriteRequest {
        course,
        study,
        key,
        source,
        operation,
        ..
    } = *request;
    let hash =
        request_fingerprints::course_answers(course, study, source, operation.name(), entries);
    let receipt = db.query_row("SELECT operation,payload_hash,result_json FROM course_write_receipts WHERE idempotency_key=?",[key],
        |row|Ok(StoredReceipt {operation:row.get(0)?,payload_hash:row.get(1)?,result_json:row.get(2)?})).optional()?;
    if let Some(receipt) = receipt {
        return receipt.replay(Some(operation.name()), &hash);
    }
    let round = get_round(db, course, study, true)?;
    if round
        .as_ref()
        .is_some_and(|round| round.snapshot["course"]["learning_mode"] == "english")
    {
        return Err(StorageError::new("ENGLISH_ENDPOINT_REQUIRED"));
    }
    let exercises = exercises(db, course, round.as_ref())?;
    let ids = ids_from(&exercises);
    let answered: HashSet<_> = entries
        .iter()
        .map(|row| row["exercise_id"].as_str().unwrap())
        .collect();
    let groups: HashSet<_> = exercises
        .iter()
        .filter(|row| {
            matches!(
                row["type"].as_str(),
                Some("READING_GROUP" | "LISTENING_GROUP")
            )
        })
        .map(|row| row["id"].as_str().unwrap())
        .collect();
    if !answered.is_disjoint(&groups) {
        return Err(StorageError::new("PRACTICE_ENDPOINT_REQUIRED"));
    }
    if answered
        .iter()
        .any(|id| !ids.iter().any(|other| other == id))
    {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    if operation == Operation::Essay
        && (study.is_none()
            || answered.len() != 1
            || !exercises.iter().any(|row| {
                row["type"] == "ESSAY" && answered.contains(row["id"].as_str().unwrap())
            }))
    {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let latest = scoped_summaries(db, &ids, round.as_ref().map(Round::scope), false)?;
    let formal = |id: &str| latest.get(id).and_then(|pair| pair.0.as_ref());
    if operation == Operation::Submit {
        if groups.iter().any(|id| formal(id).is_none()) {
            return Err(StorageError::new("INCOMPLETE_PRACTICE_GROUP"));
        }
        for id in ids
            .iter()
            .filter(|id| !groups.contains(id.as_str()) && !answered.contains(id.as_str()))
        {
            let row = formal(id);
            let required = match action(row) {
                "LOCKED" => false,
                "RETEST" => {
                    crate::reviews::retest_task(db, row.and_then(|row| row["id"].as_str()), None)?
                        .is_some()
                }
                _ => true,
            };
            if required {
                return Err(StorageError::new("INCOMPLETE_COURSE_ANSWERS"));
            }
        }
    }
    let batch = Uuid::new_v4().to_string();
    let mut written = Vec::with_capacity(entries.len());
    for entry in entries {
        written.push(write_one(
            db,
            entry,
            formal(entry["exercise_id"].as_str().unwrap()),
            round.as_ref(),
            operation,
            source,
            &batch,
        )?);
    }
    let session = round.as_ref().map(|round| round.id.as_str());
    let submitted = operation.submitted();
    let response = json!({"course_id":course,"study_session_id":session,"batch_id":submitted.then_some(&batch),"status":if submitted {"WAITING_REVIEW"} else {"DRAFT"},
        "submissions":written,"next_action":if submitted {"本课已提交；等待外部 Agent 批改。"} else {"继续课程作答。"}});
    db.execute("INSERT INTO course_write_receipts(id,idempotency_key,course_id,study_session_id,operation,payload_hash,result_json) VALUES(?,?,?,?,?,?,?)",
        params![batch,key,course,session,operation.name(),hash,response.to_string()])?;
    Ok(response)
}

fn write_one(
    db: &Connection,
    entry: &Value,
    formal: Option<&Value>,
    round: Option<&Round>,
    operation: Operation,
    source: &str,
    batch: &str,
) -> Result<Value, StorageError> {
    let kind = action(formal);
    if kind == "LOCKED" {
        return Err(StorageError::new("INVALID_STATE_TRANSITION"));
    }
    let exercise = entry["exercise_id"].as_str().unwrap();
    let parent = entry["parent_submission_id"].as_str();
    if let Some(formal) = formal {
        if parent != formal["id"].as_str() {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
    } else if parent.is_some() {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let retest = if kind == "RETEST" {
        let task = crate::reviews::retest_task(db, parent, None)?;
        if !task
            .as_ref()
            .is_some_and(|task| task["id"].as_str() == entry["retest_task_id"].as_str())
        {
            return Err(StorageError::new("RETEST_TASK_REQUIRED"));
        }
        task
    } else {
        None
    };
    let inherited_retest = formal.and_then(|row| row["retest_task_id"].as_str());
    if kind != "RETEST"
        && !entry["retest_task_id"].is_null()
        && entry["retest_task_id"].as_str() != inherited_retest
    {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let retest_id = retest
        .as_ref()
        .and_then(|row| row["id"].as_str())
        .or(inherited_retest);
    let session = round.map(|round| round.id.as_str());
    let task = entry["task_id"].as_str();
    if let Some(id) = task {
        if !db.query_row(
            "SELECT EXISTS(SELECT 1 FROM tasks WHERE id=?)",
            [id],
            |row| row.get::<_, bool>(0),
        )? {
            return Err(StorageError::new("OBJECT_NOT_FOUND"));
        }
    }
    let submitted = operation.submitted();
    let (status, next, batch) = if submitted {
        ("WAITING_REVIEW", "等待外部 Agent 批改", Some(batch))
    } else {
        ("DRAFT", "继续编辑课程草稿。", None)
    };
    let text = entry["answer_text"].as_str().unwrap();
    let id = if let Some(draft) = entry["submission_id"].as_str() {
        let row = submissions::summary_by_id(db, draft)?
            .filter(|row| {
                row["status"] == "DRAFT"
                    && row["exercise_id"] == exercise
                    && row["parent_submission_id"].as_str() == parent
            })
            .ok_or_else(|| StorageError::new("INVALID_STATE_TRANSITION"))?;
        if round.is_some_and(|r| {
            row["study_session_id"].as_str() != session
                && !(r.revision == 1 && row["study_session_id"].is_null())
        }) {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        let changed = db.execute("UPDATE submissions SET answer_text=?,version=version+1,status=?,next_action=?,source=?,study_session_id=COALESCE(?,study_session_id),batch_id=COALESCE(?,batch_id),retest_task_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=? AND status='DRAFT'",
            params![text,status,next,source,session,batch,retest_id,draft,entry["expected_version"].as_i64()])?;
        if changed != 1 {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        draft.to_owned()
    } else {
        let exists = db.query_row("SELECT EXISTS(SELECT 1 FROM submissions WHERE exercise_id=? AND status='DRAFT' AND parent_submission_id IS ? AND study_session_id IS ?)",params![exercise,parent,session],|row|row.get::<_,bool>(0))?;
        if exists {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        let id = Uuid::new_v4().to_string();
        let task = task.or_else(|| formal.and_then(|row| row["task_id"].as_str()));
        db.execute("INSERT INTO submissions(id,exercise_id,parent_submission_id,task_id,answer_text,source,study_session_id,status,version,attempt_number,attempt_kind,next_action,batch_id,retest_task_id)
            VALUES(?,?,?,?,?,?,?,?,1,(SELECT COALESCE(MAX(attempt_number),0)+1 FROM submissions WHERE exercise_id=?2),?,?,?,?)",
            params![id,exercise,parent,task,text,source,session,status,kind,next,batch,retest_id])?;
        if let Some(parent) = formal {
            submissions::claim_parent(db, parent, &id, source)?;
        }
        id
    };
    if let Some(task) = &retest {
        let state = if operation == Operation::Submit {
            "WAITING_REVIEW"
        } else {
            "IN_PROGRESS"
        };
        db.execute(
            "UPDATE retest_tasks SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            params![state, task["id"].as_str()],
        )?;
    }
    if submitted {
        db.execute("UPDATE tasks SET status='IN_PROGRESS',updated_at=CURRENT_TIMESTAMP WHERE status='TODO' AND id=(SELECT task_id FROM submissions WHERE id=?)",[&id])?;
    }
    events::record(
        db,
        source,
        "submission",
        &id,
        operation.name(),
        if submitted {
            "整课统一提交"
        } else {
            "整课统一保存"
        },
    )?;
    submissions::summary_by_id(db, &id)?.ok_or_else(|| StorageError::new("DATABASE_ERROR"))
}
