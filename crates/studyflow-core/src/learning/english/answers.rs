use rusqlite::{params, Connection};
use serde_json::{json, Map, Value};
use uuid::Uuid;

use super::{body, feedback, initialize, item, items, latest, mistakes, reference, spec, state};
use crate::{
    application::write_contract::require_version,
    infrastructure::StorageError,
    learning::{english_check, study_sessions::Round, submissions},
};

fn essay(item: &Value) -> bool {
    item["type"] == "ESSAY" && item.get("english").is_none()
}

pub(crate) fn save(
    db: &Connection,
    round: &Round,
    exercise: &str,
    answer: &str,
    expected: i64,
    skipped: bool,
) -> Result<Value, StorageError> {
    let item = item(round, exercise)?;
    let spec = if essay(item) { None } else { Some(spec(item)?) };
    let limit = if spec.is_some() { 4000 } else { 100000 };
    if expected < 0 || answer.chars().count() > limit {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let existing = latest(db, &round.id, exercise)?.unwrap_or(Value::Null);
    let current = existing["version"].as_i64().unwrap_or(0);
    require_version(current, expected)?;
    let status = existing["status"].as_str();
    if matches!(
        status,
        Some("WAITING_REVIEW" | "PASSED" | "RECHECKED" | "REVIEWED")
    ) {
        return Err(StorageError::new("ANSWER_LOCKED"));
    }
    let (id, version) = if status == Some("DRAFT") {
        let id = existing["id"].as_str().unwrap();
        if db.execute("UPDATE submissions SET answer_text=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=? AND status='DRAFT'",params![answer,id,expected])?!=1 {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        (id.to_owned(), expected + 1)
    } else {
        let id = Uuid::new_v4().to_string();
        let (parent, attempt, kind) = if let Some(parent) = existing["id"].as_str() {
            (
                Some(parent),
                existing["attempt_number"].as_i64().unwrap_or(0) + 1,
                "REVISION",
            )
        } else {
            (None, 1, "FIRST")
        };
        db.execute("INSERT INTO submissions(id,exercise_id,study_session_id,parent_submission_id,attempt_number,attempt_kind,answer_text,status,version,source,next_action)
            VALUES(?,?,?,?,?,?,?,'DRAFT',1,'USER_ENGINE','')",params![id,exercise,round.id,parent,attempt,kind,answer])?;
        if parent.is_some() {
            submissions::claim_parent(db, &existing, &id, "USER_ENGINE")?;
        }
        (id, 1)
    };
    if let Some(spec) = spec {
        let mode = spec["evaluation_mode"].as_str().unwrap_or("local_exact");
        db.execute("INSERT INTO english_submission_details(submission_id,assisted,skipped,evaluation_mode) VALUES(?,0,?,?) ON CONFLICT(submission_id)
            DO UPDATE SET last_attempt_id=NULL,skipped=excluded.skipped,evaluation_mode=excluded.evaluation_mode",params![id,skipped,mode])?;
    }
    initialize(db, round)?;
    let version_state:i64=db.query_row("UPDATE english_study_states SET completed=0,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE study_session_id=? RETURNING version",[&round.id],|row|row.get(0))?;
    Ok(
        json!({"submission_id":id,"answer_version":version,"state_version":version_state,"saved":true}),
    )
}

fn require_draft(
    db: &Connection,
    round: &Round,
    exercise: &str,
    expected: i64,
) -> Result<Value, StorageError> {
    latest(db, &round.id, exercise)?
        .filter(|row| row["status"] == "DRAFT" && row["version"] == expected)
        .ok_or_else(|| StorageError::new("VERSION_CONFLICT"))
}

pub(crate) fn check(
    db: &Connection,
    round: &Round,
    exercise: &str,
    expected: i64,
) -> Result<Value, StorageError> {
    let item = item(round, exercise)?;
    let spec = spec(item)?;
    let row = require_draft(db, round, exercise, expected)?;
    let submission = row["id"].as_str().unwrap();
    let answer = body(db, submission)?;
    if answer.trim().is_empty() {
        return Err(StorageError::new("ANSWER_EMPTY"));
    }
    let assisted = feedback(db, Some(submission))?.assisted;
    let mut result = english_check::evaluate(spec, &answer)?;
    let error_count = if result["matched"] == true {
        0
    } else {
        consecutive_errors(db, &round.id, exercise)? + 1
    };
    result["error_count"] = json!(error_count);
    let rule = english_check::rule_hash(spec, item["prompt"].as_str().unwrap_or_default());
    let id = Uuid::new_v4().to_string();
    db.execute("INSERT INTO english_check_attempts(id,study_session_id,exercise_id,submission_id,answer_text,answer_version,rule_hash,result_json,assisted,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%d %H:%M:%f','now'),strftime('%Y-%m-%d %H:%M:%f','now'))",params![id,round.id,exercise,submission,answer,expected,rule,result.to_string(),assisted])?;
    if db.execute(
        "UPDATE english_submission_details SET last_attempt_id=?,skipped=0 WHERE submission_id=?",
        params![id, submission],
    )? != 1
    {
        return Err(StorageError::new("DATABASE_ERROR"));
    }
    initialize(db, round)?;
    let state:i64=db.query_row("UPDATE english_study_states SET version=version+1,updated_at=CURRENT_TIMESTAMP WHERE study_session_id=? RETURNING version",[&round.id],|row|row.get(0))?;
    mistakes::record_check(db, round, item, &id, &rule, result["matched"] == true)?;
    result["attempt_id"] = json!(id);
    result["answer_version"] = json!(expected);
    result["state_version"] = json!(state);
    Ok(result)
}

fn consecutive_errors(db: &Connection, study: &str, exercise: &str) -> Result<i64, StorageError> {
    let mut query=db.prepare("SELECT json_extract(result_json,'$.matched') FROM english_check_attempts WHERE study_session_id=? AND exercise_id=? AND retest_task_id IS NULL ORDER BY created_at DESC,rowid DESC")?;
    let mut rows = query.query(params![study, exercise])?;
    let mut count = 0;
    while let Some(row) = rows.next()? {
        match row.get::<_, Option<bool>>(0)? {
            Some(true) => break,
            Some(false) => count += 1,
            None => {}
        }
    }
    Ok(count)
}

pub(crate) fn reveal(
    db: &Connection,
    round: &Round,
    exercise: &str,
) -> Result<Value, StorageError> {
    let spec = spec(item(round, exercise)?)?;
    let (id, version) = if let Some(row) = latest(db, &round.id, exercise)? {
        (
            row["id"].as_str().unwrap().to_owned(),
            row["version"].as_i64().unwrap(),
        )
    } else {
        let saved = save(db, round, exercise, "", 0, false)?;
        (
            saved["submission_id"].as_str().unwrap().to_owned(),
            saved["answer_version"].as_i64().unwrap(),
        )
    };
    if db.execute(
        "UPDATE english_submission_details SET assisted=1 WHERE submission_id=?",
        [id],
    )? != 1
    {
        return Err(StorageError::new("DATABASE_ERROR"));
    }
    initialize(db, round)?;
    let version_state:i64=db.query_row("UPDATE english_study_states SET version=version+1,updated_at=CURRENT_TIMESTAMP WHERE study_session_id=? RETURNING version",[&round.id],|row|row.get(0))?;
    let mut result = reference(spec);
    result["assisted"] = json!(true);
    result["answer_version"] = json!(version);
    result["state_version"] = json!(version_state);
    Ok(result)
}

pub(crate) fn request_review(
    db: &Connection,
    round: &Round,
    exercise: &str,
    expected: i64,
) -> Result<Value, StorageError> {
    let item = item(round, exercise)?;
    if !essay(item) {
        spec(item)?;
    }
    let row = require_draft(db, round, exercise, expected)?;
    let id = row["id"].as_str().unwrap();
    if body(db, id)?.trim().is_empty() {
        return Err(StorageError::new("ANSWER_EMPTY"));
    }
    if !essay(item) {
        db.execute(
            "UPDATE english_submission_details SET evaluation_mode='agent' WHERE submission_id=?",
            [id],
        )?;
    }
    if db.execute("UPDATE submissions SET status='WAITING_REVIEW',version=version+1,next_action='等待Agent审核此项，其余项可以继续。',updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=? AND status='DRAFT'",params![id,expected])?!=1 {return Err(StorageError::new("VERSION_CONFLICT"));}
    Ok(json!({"submission_id":id,"answer_version":expected+1,"status":"WAITING_REVIEW"}))
}

pub(crate) fn navigate(
    db: &Connection,
    round: &Round,
    position: i64,
    expected: i64,
) -> Result<Value, StorageError> {
    require_version(state(db, &round.id)?.version, expected)?;
    if position < 0 || position as usize >= items(round).count() {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    initialize(db, round)?;
    let version:i64=db.query_row("UPDATE english_study_states SET position=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE study_session_id=? RETURNING version",params![position,round.id],|row|row.get(0))?;
    Ok(json!({"position":position,"state_version":version}))
}

pub(crate) fn submit(
    db: &Connection,
    round: &Round,
    versions: Option<&Map<String, Value>>,
) -> Result<Value, StorageError> {
    let ids = round.ids();
    if versions.is_some_and(|versions| {
        versions.len() != ids.len() || ids.iter().any(|id| !versions.contains_key(id))
    }) {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let mut to_finalize = Vec::new();
    let mut waiting = 0;
    for id in ids {
        let row = latest(db, &round.id, &id)?.unwrap_or(Value::Null);
        let current = row["version"].as_i64().unwrap_or(0);
        if versions.is_some_and(|versions| versions[&id].as_i64() != Some(current)) {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        match row["status"].as_str() {
            Some("WAITING_REVIEW") => {
                waiting += 1;
                continue;
            }
            Some("PASSED" | "RECHECKED" | "REVIEWED") => continue,
            _ => {}
        }
        let submission = row["id"]
            .as_str()
            .ok_or_else(|| StorageError::new("COURSE_INCOMPLETE"))?;
        let feedback = feedback(db, Some(submission))?;
        if feedback.skipped
            || feedback.checked["matched"] != true
            || body(db, submission)?.trim().is_empty()
        {
            return Err(StorageError::new("COURSE_INCOMPLETE"));
        }
        to_finalize.push((
            submission.to_owned(),
            current,
            row["parent_submission_id"].is_string(),
        ));
    }
    let batch = Uuid::new_v4().to_string();
    for (id, version, followup) in to_finalize {
        let status = if followup { "RECHECKED" } else { "PASSED" };
        if db.execute("UPDATE submissions SET status=?,version=version+1,batch_id=?,next_action='本地规则检查通过，不代表长期掌握。',updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?",params![status,batch,id,version])?!=1 {return Err(StorageError::new("VERSION_CONFLICT"));}
    }
    initialize(db, round)?;
    let version:i64=db.query_row("UPDATE english_study_states SET completed=1,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE study_session_id=? RETURNING version",[&round.id],|row|row.get(0))?;
    Ok(json!({"completed":true,"waiting_review":waiting,"batch_id":batch,"state_version":version}))
}
