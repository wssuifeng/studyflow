use std::collections::HashSet;

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    application::write_contract::require_version,
    infrastructure::StorageError,
    learning::{english_check, submissions},
};

struct Task {
    study: String,
    parent: String,
    title: String,
    prompt: String,
    status: String,
    payload: Value,
}

fn task(db: &Connection, id: &str, active: bool) -> Result<Task, StorageError> {
    let (study,parent,title,prompt,status,raw)=db.query_row("SELECT study_session_id,parent_submission_id,title,prompt,status,payload_json FROM retest_tasks WHERE id=? AND task_mode='english'",[id],
        |row|Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get::<_,String>(4)?,row.get::<_,String>(5)?))).optional()?.ok_or_else(||StorageError::new("OBJECT_NOT_FOUND"))?;
    if active && !matches!(status.as_str(), "READY" | "IN_PROGRESS") {
        return Err(StorageError::new("INVALID_STATE_TRANSITION"));
    }
    let payload =
        serde_json::from_str(&raw).map_err(|err| StorageError::caused_by("DATABASE_ERROR", err))?;
    Ok(Task {
        study,
        parent,
        title,
        prompt,
        status,
        payload,
    })
}

pub(crate) fn study(db: &Connection, id: &str) -> Result<String, StorageError> {
    Ok(task(db, id, false)?.study)
}

struct Attempt {
    id: String,
    answer: String,
    status: String,
    version: i64,
}

fn attempt(db: &Connection, id: &str) -> Result<Option<Attempt>, StorageError> {
    Ok(db.query_row("SELECT id,answer_text,status,version FROM submissions WHERE retest_task_id=? ORDER BY created_at DESC,id DESC LIMIT 1",[id],|row|
        Ok(Attempt{id:row.get(0)?,answer:row.get(1)?,status:row.get(2)?,version:row.get(3)?})).optional()?)
}

pub fn get(db: &Connection, id: &str) -> Result<Value, StorageError> {
    let task = task(db, id, false)?;
    let row = attempt(db, id)?;
    let result:Option<String>=db.query_row("SELECT result_json FROM english_check_attempts WHERE retest_task_id=? ORDER BY created_at,id LIMIT 1",[id],|row|row.get(0)).optional()?;
    let result: Option<Value> = result
        .map(|raw| serde_json::from_str(&raw))
        .transpose()
        .map_err(|err| StorageError::caused_by("DATABASE_ERROR", err))?;
    Ok(
        json!({"task_id":id,"study_session_id":task.study,"exercise_id":task.payload["exercise_id"],"title":task.title,"prompt":task.prompt,
        "token_count":english_check::tokens(task.payload["spec"]["target"].as_str().unwrap_or_default()).len(),"status":task.status,
        "answer_text":row.as_ref().map_or("",|row|row.answer.as_str()),"answer_version":row.as_ref().map_or(0,|row|row.version),"result":result}),
    )
}

pub(crate) fn save(
    db: &Connection,
    id: &str,
    answer: &str,
    expected: i64,
) -> Result<Value, StorageError> {
    let task = task(db, id, true)?;
    if answer.chars().count() > 4000 || expected < 0 {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let existing = attempt(db, id)?;
    require_version(existing.as_ref().map_or(0, |row| row.version), expected)?;
    if let Some(row) = existing {
        if row.status != "DRAFT" {
            return Err(StorageError::new("ANSWER_LOCKED"));
        }
        if db.execute("UPDATE submissions SET answer_text=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=? AND status='DRAFT'",params![answer,row.id,expected])?!=1{return Err(StorageError::new("VERSION_CONFLICT"));}
    } else {
        db.execute("INSERT INTO submissions(id,exercise_id,study_session_id,retest_task_id,answer_text,status,version,attempt_number,attempt_kind,source,next_action)
            VALUES(?,?,?,?,?,'DRAFT',1,1,'RETEST','USER_ENGINE','')",params![Uuid::new_v4().to_string(),task.payload["exercise_id"].as_str(),task.study,id,answer])?;
    }
    db.execute(
        "UPDATE retest_tasks SET status='IN_PROGRESS',updated_at=CURRENT_TIMESTAMP WHERE id=?",
        [id],
    )?;
    Ok(json!({"task_id":id,"answer_version":expected+1,"status":"IN_PROGRESS"}))
}

pub(crate) fn check(
    db: &Connection,
    id: &str,
    answer: &str,
    expected: i64,
) -> Result<Value, StorageError> {
    let task = task(db, id, true)?;
    if answer.trim().is_empty() || answer.chars().count() > 4000 {
        return Err(StorageError::new("ANSWER_EMPTY"));
    }
    let existing = attempt(db, id)?;
    require_version(existing.as_ref().map_or(0, |row| row.version), expected)?;
    if existing.as_ref().is_some_and(|row| row.status != "DRAFT") {
        return Err(StorageError::new("ANSWER_LOCKED"));
    }
    let mut result = english_check::evaluate(&task.payload["spec"], answer)?;
    let mut parent = task.parent;
    let mut visited = HashSet::new();
    while let Some(child) = db
        .query_row(
            "SELECT child_id FROM submission_chain_links WHERE parent_id=?",
            [&parent],
            |row| row.get::<_, String>(0),
        )
        .optional()?
    {
        if !visited.insert(parent) {
            return Err(StorageError::new("SUBMISSION_BRANCH_CONFLICT"));
        }
        parent = child;
    }
    let parent_row = submissions::summary_by_id(db, &parent)?
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    let sequence = parent_row["attempt_number"].as_i64().unwrap_or(0) + 1;
    let matched = result["matched"] == true;
    let (status, retest_status, review) = if matched {
        ("RECHECKED", "PASSED", "PASSED_THIS_TIME")
    } else {
        ("RETEST_REQUIRED", "RETEST_REQUIRED", "PENDING")
    };
    let exercise = task.payload["exercise_id"]
        .as_str()
        .ok_or_else(|| StorageError::new("DATABASE_ERROR"))?;
    let version = expected + 1;
    let submission = if let Some(row) = existing {
        if db.execute("UPDATE submissions SET parent_submission_id=?,attempt_number=?,attempt_kind='RETEST',answer_text=?,status=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=? AND status='DRAFT'",
            params![parent,sequence,answer,status,row.id,expected])?!=1{return Err(StorageError::new("VERSION_CONFLICT"));}
        row.id
    } else {
        let submission = Uuid::new_v4().to_string();
        db.execute("INSERT INTO submissions(id,exercise_id,study_session_id,retest_task_id,parent_submission_id,attempt_number,attempt_kind,answer_text,status,version,source,next_action)
            VALUES(?,?,?,?,?,?,'RETEST',?,?,1,'USER_ENGINE','')",params![submission,exercise,task.study,id,parent,sequence,answer,status])?;
        submission
    };
    submissions::claim_parent(db, &parent_row, &submission, "USER_ENGINE")?;
    let attempt = Uuid::new_v4().to_string();
    db.execute("INSERT INTO english_check_attempts(id,study_session_id,exercise_id,submission_id,retest_task_id,answer_text,answer_version,rule_hash,result_json,assisted)
        VALUES(?,?,?,?,?,?,?,?,?,0)",params![attempt,task.study,exercise,submission,id,answer,version,task.payload["rule_hash"].as_str(),result.to_string()])?;
    let aggregate = task.payload["aggregate_id"]
        .as_str()
        .ok_or_else(|| StorageError::new("DATABASE_ERROR"))?;
    if !matched {
        db.execute("INSERT INTO english_error_evidence(id,aggregate_id,attempt_id,round_key,valid_error) VALUES(?,?,?,?,1)",params![Uuid::new_v4().to_string(),aggregate,attempt,id])?;
    }
    let aggregate_version:i64=db.query_row("UPDATE english_error_aggregates SET latest_attempt_id=?,version=version+1,failed_attempts=failed_attempts+?2,failed_rounds=failed_rounds+?2,
        archived=CASE WHEN ?2 THEN 0 ELSE archived END,updated_at=CURRENT_TIMESTAMP WHERE id=?3 RETURNING version",params![attempt,i64::from(!matched),aggregate],|row|row.get(0))?;
    if db.execute("UPDATE english_review_items SET status=?,updated_at=CURRENT_TIMESTAMP WHERE aggregate_id=?",params![review,aggregate])?!=1{return Err(StorageError::new("DATABASE_ERROR"));}
    db.execute(
        "UPDATE retest_tasks SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        params![retest_status, id],
    )?;
    result.as_object_mut().unwrap().extend(json!({"task_id":id,"submission_id":submission,"status":retest_status,"aggregate_version":aggregate_version,"answer_version":version}).as_object().unwrap().clone());
    Ok(result)
}
