use std::path::Path;

use rusqlite::{params, Connection, OptionalExtension, Row};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    attempt_history::{frozen_exercise_ids, scoped_summaries, Latest},
    material, request_fingerprints,
};
use crate::{
    application::write_contract::{atomic_write, require_version, validate_key},
    courses::catalog,
    infrastructure::{events, StorageError},
    workspace::Workspace,
};

pub(crate) struct Round {
    pub(crate) id: String,
    pub(crate) course: String,
    pub(crate) revision: i64,
    pub(crate) snapshot: Value,
    pub(crate) hash: String,
    progress: Value,
    resume_lesson: Option<String>,
    pub(super) version: i64,
    pub(crate) abandoned: Option<String>,
    pub(super) reading_completed: bool,
}

const COLUMNS: &str = "id,course_id,revision,snapshot_json,content_hash,progress_json,resume_lesson_id,version,abandoned_at,reading_completed";

fn decode(row: &Row<'_>, index: usize) -> rusqlite::Result<Value> {
    serde_json::from_str(&row.get::<_, String>(index)?).map_err(|err| {
        rusqlite::Error::FromSqlConversionFailure(index, rusqlite::types::Type::Text, Box::new(err))
    })
}

fn load(row: &Row<'_>) -> rusqlite::Result<Round> {
    Ok(Round {
        id: row.get(0)?,
        course: row.get(1)?,
        revision: row.get(2)?,
        snapshot: decode(row, 3)?,
        hash: row.get(4)?,
        progress: decode(row, 5)?,
        resume_lesson: row.get(6)?,
        version: row.get(7)?,
        abandoned: row.get(8)?,
        reading_completed: row.get(9)?,
    })
}

pub(crate) fn current(db: &Connection, course: &str) -> Result<Option<Round>, StorageError> {
    Ok(db.query_row(&format!("SELECT {COLUMNS} FROM course_study_sessions WHERE course_id=? ORDER BY revision DESC LIMIT 1"), [course], load).optional()?)
}

pub(crate) fn require(
    db: &Connection,
    id: &str,
    course: Option<&str>,
    active: bool,
) -> Result<Round, StorageError> {
    if id.trim().is_empty() {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let round = db
        .query_row(
            &format!("SELECT {COLUMNS} FROM course_study_sessions WHERE id=?"),
            [id],
            load,
        )
        .optional()?
        .filter(|round| course.is_none_or(|course| round.course == course))
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    if active && !is_current(db, &round)? {
        return Err(StorageError::new("STUDY_ROUND_SUPERSEDED"));
    }
    Ok(round)
}

fn is_current(db: &Connection, round: &Round) -> Result<bool, StorageError> {
    let newer = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM course_study_sessions WHERE course_id=? AND revision>?)",
        params![round.course, round.revision],
        |row| row.get::<_, bool>(0),
    )?;
    Ok(round.abandoned.is_none() && !newer)
}

impl Round {
    pub(crate) fn scope(&self) -> (&str, i64) {
        (&self.id, self.revision)
    }
    pub(crate) fn ids(&self) -> Vec<String> {
        frozen_exercise_ids(&self.snapshot)
    }
}

pub(crate) fn outcome(round: &Round, ids: &[String], attempts: &Latest) -> Value {
    let formal: Vec<_> = ids
        .iter()
        .map(|id| attempts.get(id).and_then(|pair| pair.0.as_ref()))
        .collect();
    let states: Vec<_> = formal
        .iter()
        .map(|item| {
            item.and_then(|row| row["status"].as_str())
                .unwrap_or("NOT_SUBMITTED")
        })
        .collect();
    let waiting = states.iter().filter(|&&s| s == "WAITING_REVIEW").count();
    let passed = states
        .iter()
        .filter(|&&s| matches!(s, "PASSED" | "RECHECKED" | "REVIEWED"))
        .count();
    let feedback = states
        .iter()
        .filter(|&&s| !matches!(s, "NOT_SUBMITTED" | "WAITING_REVIEW"))
        .count();
    let missing = states.contains(&"NOT_SUBMITTED");
    let status = if round.abandoned.is_some() {
        "ABANDONED"
    } else if ids.is_empty() {
        if round.reading_completed {
            "READ_COMPLETED"
        } else {
            "IN_PROGRESS"
        }
    } else if states.contains(&"NEEDS_REVISION") {
        "NEEDS_REVISION"
    } else if states.contains(&"RETEST_REQUIRED") {
        "RETEST_REQUIRED"
    } else if passed == ids.len() {
        "PASSED"
    } else if missing {
        "IN_PROGRESS"
    } else if waiting == ids.len() {
        "WAITING_REVIEW"
    } else {
        "PARTIAL_FEEDBACK"
    };
    let batch = formal
        .into_iter()
        .flatten()
        .filter_map(|row| row["batch_id"].as_str())
        .next_back();
    json!({"study_status":status,"exercise_total":ids.len(),"exercise_completed":passed,"waiting_count":waiting,"feedback_count":feedback,
        "batch_id":batch,"learning_submitted":if ids.is_empty() {round.reading_completed} else {!missing}})
}

fn eligible(db: &Connection, round: &Round) -> Result<bool, StorageError> {
    let ids = round.ids();
    let attempts = scoped_summaries(db, &ids, Some(round.scope()), false)?;
    if matches!(
        outcome(round, &ids, &attempts)["study_status"].as_str(),
        Some("PASSED" | "READ_COMPLETED")
    ) {
        return Ok(true);
    }
    if round.snapshot["course"]["learning_mode"] != "english" {
        return Ok(false);
    }
    let completed = db
        .query_row(
            "SELECT completed FROM english_study_states WHERE study_session_id=?",
            [&round.id],
            |row| row.get::<_, bool>(0),
        )
        .optional()?
        .unwrap_or(false);
    Ok(completed
        && !ids.is_empty()
        && ids.iter().all(|id| {
            attempts.get(id).is_some_and(|(formal, draft)| {
                draft.is_none()
                    && formal.as_ref().is_some_and(|row| {
                        matches!(
                            row["status"].as_str(),
                            Some("WAITING_REVIEW" | "PASSED" | "RECHECKED" | "REVIEWED")
                        )
                    })
            })
        }))
}

pub fn detail(db: &Connection, root: &Path, id: &str) -> Result<Value, StorageError> {
    let round = require(db, id, None, false)?;
    let ids = round.ids();
    let attempts = scoped_summaries(db, &ids, Some(round.scope()), false)?;
    let mut content = round.snapshot.clone();
    let live = material::capture(
        db,
        root,
        &round.course,
        content["course"]["plan_line_id"].as_str(),
    );
    let changed = live.as_ref().map_or(true, |(snapshot, hash)| {
        *hash != round.hash
            && material::logical_capture(snapshot) != material::logical_capture(&round.snapshot)
    });
    let key = crate::audio::assets::digest(root.to_string_lossy().as_bytes());
    let mut total_percent = 0;
    let mut completed = 0;
    let lessons = content["lessons"]
        .as_array_mut()
        .ok_or_else(|| StorageError::new("DATABASE_ERROR"))?;
    let count = lessons.len();
    for lesson in lessons {
        material::hide_answers(lesson);
        let lesson_id = lesson["id"].as_str().unwrap();
        let progress = round.progress.get(lesson_id).cloned().unwrap_or_else(
            || json!({"progress_percent":0,"status":"NOT_STARTED","last_position":""}),
        );
        total_percent += progress["progress_percent"].as_i64().unwrap_or(0);
        completed += i64::from(progress["status"] == "COMPLETED");
        lesson["progress"] = progress;
        for exercise in lesson["exercises"].as_array_mut().into_iter().flatten() {
            let (formal, draft) = attempts
                .get(exercise["id"].as_str().unwrap())
                .cloned()
                .unwrap_or_default();
            exercise["latest_submission"] = json!(formal);
            exercise["draft"] = json!(draft);
        }
    }
    let reading_percent = (total_percent as f64 / count.max(1) as f64).round_ties_even() as i64;
    let results = outcome(&round, &ids, &attempts);
    let course = content["course"].as_object_mut().unwrap();
    course.extend(results.as_object().unwrap().clone());
    let progress_percent = if ids.is_empty() {
        reading_percent
    } else {
        (results["exercise_completed"].as_f64().unwrap() * 100.0 / ids.len() as f64)
            .round_ties_even() as i64
    };
    course.extend(json!({"knowledge_total":count,"knowledge_completed":completed,"reading_percent":reading_percent,"progress_percent":progress_percent}).as_object().unwrap().clone());
    crate::planning::add_membership(db, &round.course, &mut content["course"])?;
    Ok(
        json!({"course":content["course"],"lessons":content["lessons"],"study":{"workspace_key":&key[..16],"id":round.id,"revision":round.revision,"content_hash":round.hash,
        "progress_version":round.version,"source_changed":changed,"source_available":live.is_ok(),"is_current":is_current(db,&round)?,"abandoned_at":round.abandoned.map(|text|text.replace(' ',"T"))},
        "resume_lesson_id":round.resume_lesson,"next_action":"在当前知识点学习和作答，整课完成后统一提交。"}),
    )
}

pub struct OpenRequest<'a> {
    pub course: &'a str,
    pub key: &'a str,
    pub plan: Option<&'a str>,
    pub new_version: bool,
    pub review_round: bool,
}

pub fn open(workspace: &Workspace, request: OpenRequest<'_>) -> Result<Value, StorageError> {
    validate_key(request.key)?;
    let root = &workspace.settings().workspace;
    let mut active = workspace.open()?;
    let id = atomic_write(&mut active.connection, |db| open_round(db, root, &request))?;
    let tx = active.connection.unchecked_transaction()?;
    let mut result = detail(&tx, root, &id)?;
    if request
        .plan
        .is_some_and(|plan| result["course"]["plan_line_id"] != plan)
    {
        result["scope_notice"] =
            json!("此课程的活跃轮次仍属于开始学习时的计划；未切换旧答案和错误的归属。");
    }
    Ok(result)
}

fn open_round(
    db: &Connection,
    root: &Path,
    request: &OpenRequest<'_>,
) -> Result<String, StorageError> {
    let OpenRequest {
        course,
        key,
        plan,
        new_version,
        review_round,
    } = *request;
    if let Some(plan) = plan {
        if plan.is_empty() {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        if !db.query_row(
            "SELECT EXISTS(SELECT 1 FROM plan_course_items WHERE plan_line_id=? AND course_id=?)",
            params![plan, course],
            |row| row.get::<_, bool>(0),
        )? {
            return Err(StorageError::new("SCOPE_MISMATCH"));
        }
    }
    let hash = request_fingerprints::open_study(course, plan, new_version, review_round);
    let receipt = db.query_row("SELECT operation,payload_hash,result_json FROM course_write_receipts WHERE idempotency_key=?",[key],
        |row|Ok(crate::application::write_contract::StoredReceipt {operation:row.get(0)?,payload_hash:row.get(1)?,result_json:row.get(2)?})).optional()?;
    let legacy = db
        .query_row(
            "SELECT id,course_id,new_version FROM course_study_sessions WHERE idempotency_key=?",
            [key],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, bool>(2)?,
                ))
            },
        )
        .optional()?;
    let replay = if let Some(receipt) = &receipt {
        let result = receipt.replay(Some("STUDY_OPEN"), &hash)?;
        Some(
            result["study_session_id"]
                .as_str()
                .ok_or_else(|| StorageError::new("IDEMPOTENCY_UNVERIFIABLE"))?
                .to_owned(),
        )
    } else if let Some((id, old_course, advanced)) = legacy {
        if old_course != course || advanced != (new_version || review_round) {
            return Err(StorageError::new("IDEMPOTENCY_KEY_CONFLICT"));
        }
        Some(id)
    } else {
        None
    };
    let current = current(db, course)?;
    let entry = if let Some(id) = replay {
        let round = require(db, &id, Some(course), false)?;
        if round.abandoned.is_some() {
            if let Some(current) = current.as_ref().filter(|round| round.abandoned.is_none()) {
                current.id.clone()
            } else {
                let revision = current.as_ref().map_or(1, |round| round.revision + 1);
                let derived = format!(
                    "{}:reset{revision}",
                    key.chars().take(148).collect::<String>()
                );
                insert_round(
                    db,
                    root,
                    course,
                    plan,
                    current.as_ref(),
                    &derived,
                    true,
                    true,
                    "课程内容更新后从最新材料重新开始",
                )?
            }
        } else {
            id
        }
    } else if let Some(existing) = current
        .as_ref()
        .filter(|round| round.abandoned.is_none() && !new_version && !review_round)
    {
        existing.id.clone()
    } else {
        if let Some(existing) = current.as_ref().filter(|round| round.abandoned.is_none()) {
            if !eligible(db, existing)? {
                return Err(StorageError::new("COURSE_STUDY_IN_PROGRESS"));
            }
        }
        insert_round(
            db,
            root,
            course,
            plan,
            current.as_ref(),
            key,
            new_version || review_round,
            review_round,
            "开始固定版本的本地学习轮次",
        )?
    };
    if receipt.is_none() {
        db.execute("INSERT INTO course_write_receipts(id,idempotency_key,course_id,study_session_id,operation,payload_hash,result_json) VALUES(?,?,?,?,'STUDY_OPEN',?,?)",
            params![Uuid::new_v4().to_string(),key,course,entry,hash,json!({"study_session_id":entry}).to_string()])?;
    }
    Ok(entry)
}

#[allow(clippy::too_many_arguments)]
fn insert_round(
    db: &Connection,
    root: &Path,
    course: &str,
    plan: Option<&str>,
    previous: Option<&Round>,
    key: &str,
    advanced: bool,
    permit_unchanged: bool,
    event: &str,
) -> Result<String, StorageError> {
    let (snapshot, hash) = material::capture(db, root, course, plan)?;
    if !permit_unchanged
        && previous.is_some_and(|round| {
            round.abandoned.is_none()
                && (round.hash == hash
                    || material::logical_capture(&round.snapshot)
                        == material::logical_capture(&snapshot))
        })
    {
        return Err(StorageError::new("COURSE_VERSION_UNCHANGED"));
    }
    let mut progress = json!({});
    if previous.is_none() {
        let mut query = db.prepare("SELECT lesson_id,progress_percent,status,last_position FROM learning_progress WHERE course_id=?")?;
        let mut rows = query.query([course])?;
        while let Some(row) = rows.next()? {
            progress[row.get::<_, String>(0)?] = json!({"progress_percent":row.get::<_,i64>(1)?,"status":row.get::<_,String>(2)?,"last_position":row.get::<_,String>(3)?});
        }
    }
    let id = Uuid::new_v4().to_string();
    db.execute("INSERT INTO course_study_sessions(id,course_id,revision,idempotency_key,new_version,snapshot_json,content_hash,progress_json,version,reading_completed,hint_tracking_enabled) VALUES(?,?,?,?,?,?,?,?,1,0,1)",
        params![id,course,previous.map_or(1,|round|round.revision+1),key,advanced,crate::infrastructure::fingerprint::JsonFingerprint::Utf8.serialize(&snapshot),hash,progress.to_string()])?;
    events::record(db, "USER_ENGINE", "course_study", &id, "OPEN", event)?;
    Ok(id)
}

pub fn save_progress(
    workspace: &Workspace,
    id: &str,
    lesson: &str,
    percent: i64,
    position: &str,
    expected: Option<i64>,
) -> Result<Value, StorageError> {
    if !(0..=100).contains(&percent) {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        let mut round = require(db, id, None, true)?;
        if !round.snapshot["lessons"]
            .as_array()
            .unwrap()
            .iter()
            .any(|row| row["id"] == lesson)
        {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        if let Some(expected) = expected {
            require_version(round.version, expected)?;
        }
        let percent = percent.max(
            round.progress[lesson]["progress_percent"]
                .as_i64()
                .unwrap_or(0),
        );
        let status = if percent == 100 {
            "COMPLETED"
        } else if percent > 0 {
            "IN_PROGRESS"
        } else {
            "NOT_STARTED"
        };
        let position = position.chars().take(500).collect::<String>();
        round.progress[lesson] =
            json!({"progress_percent":percent,"status":status,"last_position":position});
        let changed = db.execute("UPDATE course_study_sessions SET progress_json=?,resume_lesson_id=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?",params![round.progress.to_string(),lesson,id,round.version])?;
        if changed != 1 {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        Ok(
            json!({"id":id,"study_session_id":id,"course_id":round.course,"lesson_id":lesson,"version":round.version+1,"progress_percent":percent,"status":status,"last_position":position}),
        )
    })
}

pub fn complete_reading(workspace: &Workspace, id: &str) -> Result<Value, StorageError> {
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        let round = require(db, id, None, true)?;
        if !round.ids().is_empty()
            || round.snapshot["lessons"]
                .as_array()
                .unwrap()
                .iter()
                .any(|row| round.progress[row["id"].as_str().unwrap()]["progress_percent"] != 100)
        {
            return Err(StorageError::new("READING_INCOMPLETE"));
        }
        db.execute(
            "UPDATE course_study_sessions SET reading_completed=1 WHERE id=?",
            [id],
        )?;
        Ok(())
    })?;
    let tx = active.connection.unchecked_transaction()?;
    detail(&tx, &workspace.settings().workspace, id)
}

pub(crate) fn frozen_context(
    db: &Connection,
    session: &str,
    exercise: &str,
) -> Result<Option<Value>, StorageError> {
    let round = require(db, session, None, false)?;
    for lesson in round.snapshot["lessons"].as_array().into_iter().flatten() {
        if let Some(item) = lesson["exercises"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|row| row["id"] == exercise)
        {
            let mut lesson_fields = lesson.as_object().unwrap().clone();
            for key in ["exercises", "markdown", "rendered_html"] {
                lesson_fields.remove(key);
            }
            let mut exercise_fields = item.as_object().unwrap().clone();
            for key in ["reading", "listening"] {
                exercise_fields.remove(key);
            }
            return Ok(Some(
                json!({"study_session_id":session,"revision":round.revision,"content_hash":round.hash,"course":round.snapshot["course"],
                "lesson":lesson_fields,"exercise":exercise_fields,"markdown":lesson["markdown"]}),
            ));
        }
    }
    Ok(None)
}

pub fn save_legacy_progress(
    workspace: &Workspace,
    course: &str,
    lesson: &str,
    percent: i64,
    position: &str,
    source: &str,
) -> Result<Value, StorageError> {
    if !(0..=100).contains(&percent) {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        catalog::course(db, course)?;
        let owner: String = db
            .query_row(
                "SELECT course_id FROM lessons WHERE id=?",
                [lesson],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
        if owner != course {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        let status = if percent == 100 {
            "COMPLETED"
        } else if percent == 0 {
            "NOT_STARTED"
        } else {
            "IN_PROGRESS"
        };
        let position = position.chars().take(500).collect::<String>();
        let id: String = db.query_row("INSERT INTO learning_progress(id,course_id,lesson_id,progress_percent,status,last_position,source) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(course_id,lesson_id) DO UPDATE SET progress_percent=excluded.progress_percent,status=excluded.status,last_position=excluded.last_position,source=excluded.source,updated_at=CURRENT_TIMESTAMP
            RETURNING id",params![Uuid::new_v4().to_string(),course,lesson,percent,status,position,source],|row|row.get(0))?;
        Ok(
            json!({"id":id,"course_id":course,"lesson_id":lesson,"progress_percent":percent,"status":status,"last_position":position,"source":source,
            "next_action":"继续阅读或开始对应练习；该字段仅表示阅读位置，不代表已掌握。"}),
        )
    })
}
