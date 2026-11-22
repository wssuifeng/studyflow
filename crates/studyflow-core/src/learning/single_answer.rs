use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{attempt_history::latest_statuses, study_sessions, submissions};
use crate::{
    application::write_contract::{atomic_write, validate_key, StoredReceipt},
    infrastructure::{events, fingerprint::JsonFingerprint, StorageError},
    workspace::Workspace,
};

pub struct Request<'a> {
    pub exercise: Option<&'a str>,
    pub submission: Option<&'a str>,
    pub task: Option<&'a str>,
    pub expected_version: Option<i64>,
    pub answer: Option<&'a str>,
    pub key: Option<&'a str>,
    pub source: &'a str,
    pub submit: bool,
}

pub fn write(workspace: &Workspace, request: Request<'_>) -> Result<Value, StorageError> {
    let Request {
        exercise,
        submission,
        task,
        expected_version,
        answer,
        key,
        source,
        submit,
    } = request;
    let operation = if submit { "SUBMIT" } else { "DRAFT_SAVE" };
    let answer = if submit {
        answer
    } else {
        Some(answer.unwrap_or_default())
    };
    let payload = json!({"operation":operation,"exercise_id":exercise,"submission_id":submission,"task_id":task,
        "expected_version":expected_version,"answer_text":answer,"source":source});
    let hash = JsonFingerprint::Ascii.hash(&payload);
    if let Some(key) = key {
        validate_key(key)?;
    }
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        if let Some(key) = key {
            let receipt = db.query_row("SELECT operation,payload_hash,result_json FROM submission_write_receipts WHERE idempotency_key=?",[key],
                |row| Ok(StoredReceipt{operation:row.get(0)?,payload_hash:row.get(1)?,result_json:row.get(2)?})).optional()?;
            if let Some(receipt) = receipt {
                let mut result = receipt.replay(Some(operation), &hash)?;
                for field in ["source", "answer_text", "idempotency_key"] {
                    result.as_object_mut().unwrap().remove(field);
                }
                return Ok(result);
            }
            if db.query_row(
                "SELECT EXISTS(SELECT 1 FROM submissions WHERE idempotency_key=?)",
                [key],
                |row| row.get::<_, bool>(0),
            )? {
                return Err(StorageError::new("IDEMPOTENCY_UNVERIFIABLE"));
            }
        }
        if !submit {
            exercise_metadata(
                db,
                exercise.ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?,
            )?;
        }
        if let Some(task) = task {
            if !db.query_row(
                "SELECT EXISTS(SELECT 1 FROM tasks WHERE id=?)",
                [task],
                |row| row.get::<_, bool>(0),
            )? {
                return Err(StorageError::new("OBJECT_NOT_FOUND"));
            }
        }
        let draft_id = if let Some(id) = submission {
            Some(id.to_owned())
        } else if !submit {
            db.query_row("SELECT id FROM submissions WHERE exercise_id=? AND task_id IS ? AND status='DRAFT' ORDER BY created_at DESC LIMIT 1",params![exercise,task],|row|row.get(0)).optional()?
        } else {
            None
        };
        let draft = draft_id
            .as_ref()
            .map(|id| submissions::summary_by_id(db, id))
            .transpose()?
            .flatten();
        if draft_id.is_some() && draft.is_none() {
            return Err(StorageError::new("OBJECT_NOT_FOUND"));
        }
        let exercise = if let Some(draft) = &draft {
            if draft["status"] != "DRAFT" {
                return Err(StorageError::new("INVALID_STATE_TRANSITION"));
            }
            if exercise.is_some_and(|exercise| draft["exercise_id"] != exercise) {
                return Err(StorageError::new("INVALID_ARGUMENT"));
            }
            if expected_version.is_some_and(|version| draft["version"] != version) {
                return Err(StorageError::new("VERSION_CONFLICT"));
            }
            draft["exercise_id"].as_str().unwrap()
        } else {
            exercise.ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?
        };
        let status = if submit { "WAITING_REVIEW" } else { "DRAFT" };
        let next = if submit {
            "等待外部 Agent 批改"
        } else {
            "继续编辑草稿，完成后正式提交。"
        };
        let session = binding(db, exercise, draft.as_ref(), submission.is_none())?;
        let id = if let Some(draft) = &draft {
            let id = draft["id"].as_str().unwrap();
            let new = answer.map(str::to_owned);
            if submit
                && new
                    .as_ref()
                    .map_or_else(
                        || {
                            db.query_row(
                                "SELECT answer_text FROM submissions WHERE id=?",
                                [id],
                                |row| row.get::<_, String>(0),
                            )
                        },
                        |new| Ok(new.clone()),
                    )?
                    .trim()
                    .is_empty()
            {
                return Err(StorageError::new("INVALID_ARGUMENT"));
            }
            let changed = db.execute("UPDATE submissions SET answer_text=COALESCE(?,answer_text),status=?,source=?,study_session_id=COALESCE(?,study_session_id),
                next_action=CASE WHEN ? THEN ? ELSE next_action END,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=? AND status='DRAFT'",
                params![new,status,source,session,submit,next,id,draft["version"].as_i64()])?;
            if changed != 1 {
                return Err(StorageError::new("VERSION_CONFLICT"));
            }
            id.to_owned()
        } else {
            let text = answer.unwrap_or_default();
            let text = if submit { text.trim() } else { text };
            if submit && text.is_empty() {
                return Err(StorageError::new("INVALID_ARGUMENT"));
            }
            let id = Uuid::new_v4().to_string();
            db.execute("INSERT INTO submissions(id,exercise_id,task_id,answer_text,status,version,source,study_session_id,attempt_number,attempt_kind,next_action)
                VALUES(?,?,?,?,?,1,?,?,(SELECT COALESCE(MAX(attempt_number),0)+1 FROM submissions WHERE exercise_id=?2),'FIRST',?)",
                params![id,exercise,task,text,status,source,session,next])?;
            id
        };
        if submit {
            db.execute("UPDATE tasks SET status='IN_PROGRESS',updated_at=CURRENT_TIMESTAMP WHERE status='TODO' AND id=(SELECT task_id FROM submissions WHERE id=?)",[&id])?;
        }
        let result = submissions::summary_by_id(db, &id)?
            .ok_or_else(|| StorageError::new("DATABASE_ERROR"))?;
        if let Some(key) = key {
            let mut receipt = result.clone();
            let stored: String = db.query_row(
                "SELECT answer_text FROM submissions WHERE id=?",
                [&id],
                |row| row.get(0),
            )?;
            receipt["answer_text"] = json!(stored);
            receipt["idempotency_key"] = Value::Null;
            receipt["source"] = json!(source);
            db.execute("INSERT INTO submission_write_receipts(id,idempotency_key,operation,submission_id,payload_hash,result_json) VALUES(?,?,?,?,?,?)",
                params![Uuid::new_v4().to_string(),key,operation,id,hash,receipt.to_string()])?;
        }
        let summary = if submit {
            "正式提交，等待外部 Agent 批改".to_owned()
        } else {
            format!("保存草稿 v{}", result["version"])
        };
        events::record(db, source, "submission", &id, operation, &summary)?;
        Ok(result)
    })
}

fn exercise_metadata(db: &Connection, exercise: &str) -> Result<(String, String), StorageError> {
    db.query_row("SELECT l.course_id,e.exercise_type FROM exercises e JOIN lessons l ON e.lesson_id=l.id WHERE e.id=?",[exercise],|row|Ok((row.get(0)?,row.get(1)?)))
        .optional()?.ok_or_else(||StorageError::new("OBJECT_NOT_FOUND"))
}

fn binding(
    db: &Connection,
    exercise: &str,
    previous: Option<&Value>,
    is_new: bool,
) -> Result<Option<String>, StorageError> {
    let (course, kind) = exercise_metadata(db, exercise)?;
    if matches!(kind.as_str(), "READING_GROUP" | "LISTENING_GROUP") {
        return Err(StorageError::new("PRACTICE_ENDPOINT_REQUIRED"));
    }
    let Some(round) = study_sessions::current(db, &course)? else {
        return Ok(None);
    };
    if round.abandoned.is_some() {
        return Err(StorageError::new("STUDY_ROUND_SUPERSEDED"));
    }
    if round.snapshot["course"]["learning_mode"] == "english" {
        return Err(StorageError::new("ENGLISH_ENDPOINT_REQUIRED"));
    }
    let origin = previous.and_then(|row| row["study_session_id"].as_str());
    if !round.ids().iter().any(|id| id == exercise)
        || origin.is_some_and(|id| id != round.id)
        || origin.is_none() && !is_new && round.revision > 1
    {
        return Err(StorageError::new("VERSION_CONFLICT"));
    }
    if let Some(parent) = previous.and_then(|row| row["parent_submission_id"].as_str()) {
        let record = submissions::summary_by_id(db, parent)?;
        let study = record
            .as_ref()
            .and_then(|row| row["study_session_id"].as_str());
        if study != Some(round.id.as_str()) && !(study.is_none() && round.revision == 1) {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
    } else if is_new
        && latest_statuses(db, &[exercise.to_owned()], Some(round.scope()))?.contains_key(exercise)
    {
        return Err(StorageError::new("INVALID_STATE_TRANSITION"));
    }
    Ok(Some(round.id))
}

pub fn followup(
    workspace: &Workspace,
    parent: &str,
    answer: &str,
    key: Option<&str>,
    source: &str,
    retest: bool,
) -> Result<Value, StorageError> {
    let answer = answer.trim();
    if answer.is_empty() {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    if let Some(key) = key {
        validate_key(key)?;
    }
    let kind = if retest { "RETEST" } else { "REVISION" };
    let label = if retest { "复测版" } else { "修正版" };
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        if let Some(key) = key {
            if let Some((id,old_parent,old_kind,old_answer)) = db.query_row("SELECT id,parent_submission_id,attempt_kind,answer_text FROM submissions WHERE idempotency_key=?",[key],
                |row|Ok((row.get::<_,String>(0)?,row.get::<_,Option<String>>(1)?,row.get::<_,String>(2)?,row.get::<_,String>(3)?))).optional()? {
                if old_parent.as_deref()!=Some(parent) || old_kind!=kind || old_answer!=answer { return Err(StorageError::new("IDEMPOTENCY_KEY_CONFLICT")); }
                return followup_receipt(db,&id);
            }
        }
        let row = submissions::summary_by_id(db, parent)?
            .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
        if !matches!(
            row["status"].as_str(),
            Some("REVIEWED" | "NEEDS_REVISION" | "RETEST_REQUIRED" | "PASSED" | "RECHECKED")
        ) {
            return Err(StorageError::new("INVALID_ATTEMPT_SOURCE"));
        }
        let task = if retest {
            Some(
                crate::reviews::retest_task(db, Some(parent), None)?
                    .ok_or_else(|| StorageError::new("RETEST_TASK_REQUIRED"))?,
            )
        } else {
            None
        };
        let exercise = row["exercise_id"].as_str().unwrap();
        let session = binding(
            db,
            exercise,
            Some(
                &json!({"study_session_id":row["study_session_id"],"parent_submission_id":parent}),
            ),
            true,
        )?;
        let id = Uuid::new_v4().to_string();
        let next_number = row["attempt_number"].as_i64().unwrap() + 1;
        let retest_id = task
            .as_ref()
            .and_then(|task| task["id"].as_str())
            .or_else(|| row["retest_task_id"].as_str());
        db.execute("INSERT INTO submissions(id,exercise_id,task_id,parent_submission_id,answer_text,status,version,source,study_session_id,attempt_number,attempt_kind,next_action,idempotency_key,retest_task_id)
            VALUES(?,?,?,?,?,'WAITING_REVIEW',1,?,?,?,?, '等待外部 Agent 批改',?,?)",
            params![id,exercise,row["task_id"].as_str(),parent,answer,source,session,next_number,kind,key,retest_id])?;
        submissions::claim_parent(db, &row, &id, source)?;
        if let Some(task) = task {
            db.execute("UPDATE retest_tasks SET status='WAITING_REVIEW',updated_at=CURRENT_TIMESTAMP WHERE id=?",[task["id"].as_str()])?;
        }
        events::record(
            db,
            source,
            "submission",
            &id,
            "SUBMIT",
            &format!("创建{label}，父作答 {parent}"),
        )?;
        followup_receipt(db, &id)
    })
}

fn followup_receipt(db: &Connection, id: &str) -> Result<Value, StorageError> {
    let row =
        submissions::summary_by_id(db, id)?.ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    let source: String =
        db.query_row("SELECT source FROM submissions WHERE id=?", [id], |row| {
            row.get(0)
        })?;
    Ok(
        json!({"submission_id":id,"parent_submission_id":row["parent_submission_id"],"attempt_number":row["attempt_number"],
        "attempt_kind":row["attempt_kind"],"status":row["status"],"source":source,"next_action":row["next_action"]}),
    )
}

pub fn resolve_branch(
    workspace: &Workspace,
    parent: &str,
    child: &str,
    reason: &str,
) -> Result<Value, StorageError> {
    if reason.trim().is_empty() {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        let (count, matches): (i64, i64) = db.query_row(
            "SELECT COUNT(*),COALESCE(SUM(id=?2),0) FROM submissions WHERE parent_submission_id=?1",
            params![parent, child],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        if count < 2 || matches != 1 {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        let chosen: Option<String> = db
            .query_row(
                "SELECT child_id FROM submission_chain_links WHERE parent_id=?",
                [parent],
                |row| row.get(0),
            )
            .optional()?;
        if let Some(chosen) = chosen.as_deref() {
            if chosen != child {
                return Err(StorageError::new("VERSION_CONFLICT"));
            }
        } else {
            db.execute("INSERT INTO submission_chain_links(parent_id,child_id,source,reason) VALUES(?,?,'AGENT_CLI',?)",params![parent,child,reason])?;
            events::record(
                db,
                "AGENT_CLI",
                "submission",
                parent,
                "RESOLVE_BRANCH",
                reason,
            )?;
        }
        Ok(
            json!({"ok":true,"parent_submission_id":parent,"child_submission_id":child,"replayed":chosen.is_some()}),
        )
    })
}
