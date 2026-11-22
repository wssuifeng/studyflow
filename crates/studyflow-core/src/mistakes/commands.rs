use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    projection::select_english_review,
    query::{self, Domain, Entry, Scope},
};
use crate::{
    application::write_contract::{atomic_write, record_course, replay_course, validate_key},
    infrastructure::{
        events,
        fingerprint::JsonFingerprint::{Ascii, Utf8},
        StorageError,
    },
    learning::study_sessions,
    workspace::Workspace,
};

fn invalid() -> StorageError {
    StorageError::new("INVALID_ARGUMENT")
}

fn archive_snapshot(
    db: &Connection,
    input: &Value,
) -> Result<(Domain, Vec<Entry>, Value), StorageError> {
    let scope = Scope::new(db, input)?;
    let rows = scope.entries(db, None, None, 1001)?;
    if rows.len() > 1000 {
        return Err(StorageError::new("SCOPE_TOO_LARGE"));
    }
    if rows.iter().any(|row| row.archive_blocked(scope.domain)) {
        return Err(StorageError::new("ACTIVE_TASK_PROTECTED"));
    }
    let versions: Vec<_> = rows
        .iter()
        .map(|row| json!({"id":row.id,"version":row.version}))
        .collect();
    let hash = Utf8.hash(&json!({"scope":scope.value,"rows":versions}));
    let result = json!({"count":rows.len(),"preview_hash":hash,"logical_only":true});
    Ok((scope.domain, rows, result))
}

pub fn archive_preview(db: &Connection, input: &Value) -> Result<Value, StorageError> {
    Ok(archive_snapshot(db, input)?.2)
}

pub fn archive_apply(workspace: &Workspace, input: &Value) -> Result<Value, StorageError> {
    let key = input["idempotency_key"].as_str().ok_or_else(invalid)?;
    validate_key(key)?;
    let preview = input["preview_hash"]
        .as_str()
        .filter(|hash| crate::infrastructure::file_paths::is_sha256(hash))
        .ok_or_else(invalid)?;
    let hash = Ascii.hash(&json!({"preview_hash":preview,"scope":query::normalize(input)}));
    let operation = "MISTAKES_ARCHIVE";
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        if let Some(saved) = replay_course(db, key, operation, &hash)? {
            return Ok(saved);
        }
        let (domain, rows, current) = archive_snapshot(db, input)?;
        if rows.is_empty() {
            return Err(StorageError::new("EMPTY_SCOPE"));
        }
        if current["preview_hash"] != preview {
            return Err(StorageError::new("PREVIEW_CHANGED"));
        }
        let statement=format!("UPDATE {} SET archived=1,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?",domain.table());
        for row in &rows {
            if db.execute(&statement, params![row.id, row.version])? != 1 {
                return Err(StorageError::new("VERSION_CONFLICT"));
            }
        }
        let result = json!({"archived":rows.len(),"logical_only":true});
        record_course(db, &rows[0].course, key, operation, &hash, &result)?;
        events::record(
            db,
            "USER_ENGINE",
            "mistakes",
            preview,
            "ARCHIVE",
            "逻辑归档，保留证据。",
        )?;
        Ok(result)
    })
}

pub fn select_review(workspace: &Workspace, input: &Value) -> Result<Value, StorageError> {
    english_write(workspace, input, false)
}

pub fn request_retest(workspace: &Workspace, input: &Value) -> Result<Value, StorageError> {
    english_write(workspace, input, true)
}

fn english_write(
    workspace: &Workspace,
    input: &Value,
    retest: bool,
) -> Result<Value, StorageError> {
    let key = input["idempotency_key"].as_str().ok_or_else(invalid)?;
    validate_key(key)?;
    let id = input["identifier"]
        .as_str()
        .filter(|id| !id.is_empty())
        .ok_or_else(invalid)?;
    let version = input["expected_version"]
        .as_i64()
        .filter(|v| *v >= 1)
        .ok_or_else(invalid)?;
    let operation = if retest {
        "EN_RETEST_PUBLISH"
    } else {
        "EN_REVIEW_SELECT"
    };
    let hash = Ascii
        .hash(&json!({"identifier":id,"expected_version":version,"scope":query::normalize(input)}));
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        if let Some(saved) = replay_course(db, key, operation, &hash)? {
            return Ok(saved);
        }
        let scope = Scope::new(db, input)?;
        if scope.domain != Domain::English {
            return Err(StorageError::new(if retest {
                "AGENT_RETEST_REQUIRED"
            } else {
                "INVALID_ARGUMENT"
            }));
        }
        let entry = scope.entries(db, Some(id), None, 1)?.pop().ok_or_else(|| {
            StorageError::new(if retest {
                "SCOPE_MISMATCH"
            } else {
                "VERSION_CONFLICT"
            })
        })?;
        if entry.version != version {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        let result = if retest {
            let result = publish_exact(db, &entry, key)?;
            events::record(
                db,
                "USER_ENGINE",
                "english_retest",
                result["task_id"].as_str().unwrap(),
                "PUBLISH",
                "发布有冻结来源的英语无提示复测。",
            )?;
            result
        } else {
            select_english_review(db, id, "MANUAL")?;
            let review: String = db.query_row(
                "SELECT id FROM english_review_items WHERE aggregate_id=?",
                [id],
                |row| row.get(0),
            )?;
            events::record(
                db,
                "USER_ENGINE",
                "english_review",
                &review,
                "SELECT",
                "收录指定英语复习项",
            )?;
            json!({"review_id":review,"version":version+1,"status":"PENDING"})
        };
        record_course(db, &entry.course, key, operation, &hash, &result)?;
        Ok(result)
    })
}

fn publish_exact(db: &Connection, entry: &Entry, key: &str) -> Result<Value, StorageError> {
    if db.query_row(
        "SELECT EXISTS(SELECT 1 FROM retest_tasks WHERE idempotency_key=?)",
        [key],
        |row| row.get::<_, bool>(0),
    )? {
        return Err(StorageError::new("IDEMPOTENCY_KEY_CONFLICT"));
    }
    let (review,previous)=db.query_row("SELECT id,retest_task_id FROM english_review_items WHERE aggregate_id=? AND status IN ('PENDING','RETESTING','PASSED_THIS_TIME','AGENT_ACCEPTED')",[&entry.id],|row|Ok((row.get::<_,String>(0)?,row.get::<_,Option<String>>(1)?))).optional()?.ok_or_else(||StorageError::new("REVIEW_NOT_SELECTED"))?;
    if let Some(previous) = &previous {
        if let Some(current)=db.query_row("SELECT title,prompt,status FROM retest_tasks WHERE id=? AND status IN ('READY','IN_PROGRESS')",[previous],|row|Ok(json!({"task_id":previous,"title":row.get::<_,String>(0)?,"prompt":row.get::<_,String>(1)?,"status":row.get::<_,String>(2)?}))).optional()?{return Ok(current);}
    }
    let mut parent=db.query_row("SELECT a.submission_id FROM english_error_evidence ev LEFT JOIN english_check_attempts a ON a.id=ev.attempt_id WHERE ev.aggregate_id=? AND ev.valid_error=1 ORDER BY ev.created_at DESC,ev.id DESC LIMIT 1",[&entry.id],|row|row.get::<_,Option<String>>(0)).optional()?.flatten().ok_or_else(||StorageError::new("AGENT_RETEST_REQUIRED"))?;
    if let Some(previous) = previous {
        if let Some(new_parent)=db.query_row("SELECT id FROM submissions WHERE retest_task_id=? ORDER BY created_at DESC,id DESC LIMIT 1",[previous],|row|row.get(0)).optional()?{parent=new_parent;}
    }
    if db.query_row(
        "SELECT EXISTS(SELECT 1 FROM retest_tasks WHERE parent_submission_id=?)",
        [&parent],
        |row| row.get::<_, bool>(0),
    )? {
        return Err(StorageError::new("RETEST_TASK_EXISTS"));
    }
    let (study, exercise) = db.query_row(
        "SELECT study_session_id,exercise_id FROM submissions WHERE id=?",
        [&parent],
        |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
    )?;
    let frozen = study_sessions::frozen_context(db, &study, &exercise)?
        .ok_or_else(|| StorageError::new("AGENT_RETEST_REQUIRED"))?;
    let question = &frozen["exercise"];
    let prompt = question["prompt"].as_str().ok_or_else(invalid)?;
    let title = format!(
        "无提示回忆 · {}",
        question["title"].as_str().unwrap_or_default()
    );
    let payload = json!({"aggregate_id":entry.id,"exercise_id":exercise,"spec":question["english"],"prompt":prompt,"rule_hash":entry.rule});
    let id = Uuid::new_v4().to_string();
    db.execute("INSERT INTO retest_tasks(id,task_mode,payload_json,parent_submission_id,study_session_id,title,prompt,requirements,objective,agent_reference,status,idempotency_key,payload_hash) VALUES(?,'english',?,?,?,?,?,'不查看参考或听目标语音，重新输入。','原冻结训练项的无提示回忆','','READY',?,?)",params![id,payload.to_string(),parent,study,title,prompt,key,Ascii.hash(&payload)])?;
    db.execute("UPDATE english_review_items SET retest_task_id=?,status='RETESTING',updated_at=CURRENT_TIMESTAMP WHERE id=?",params![id,review])?;
    db.execute("UPDATE english_error_aggregates SET version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",[&entry.id])?;
    Ok(json!({"task_id":id,"title":title,"prompt":prompt,"status":"READY"}))
}
