use std::path::Path;

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    material,
    study_sessions::{self, Round},
};
use crate::{
    application::write_contract::{atomic_write, replay_course, require_version, validate_key},
    infrastructure::{
        events,
        fingerprint::JsonFingerprint::{Ascii, Utf8},
        StorageError,
    },
    workspace::Workspace,
};

mod restart;
pub use restart::{restart, restart_preview};

const RESET_EFFECT: &str =
    "重置本课当前阅读、作答和训练状态并采用最新材料；旧作答封存，不再进入当前待处理队列。";

fn latest(db: &Connection, root: &Path, round: &Round) -> Result<(Value, String), StorageError> {
    let plan = round.snapshot["course"]["plan_line_id"].as_str();
    let member = exists(
        db,
        "SELECT EXISTS(SELECT 1 FROM plan_course_items WHERE course_id=? AND plan_line_id=?)",
        params![round.course, plan],
    )?;
    let capture = material::capture(db, root, &round.course, plan.filter(|_| member))?;
    if capture.0["course"]["plan_line_id"].as_str() != plan {
        return Err(StorageError::new("SCOPE_MISMATCH"));
    }
    Ok(capture)
}

fn exists(db: &Connection, sql: &str, args: impl rusqlite::Params) -> Result<bool, StorageError> {
    Ok(db.query_row(sql, args, |row| row.get(0))?)
}

fn json_rows(db: &Connection, sql: &str, course: &str) -> Result<Vec<Value>, StorageError> {
    let mut query = db.prepare(sql)?;
    let rows = query.query_map([course], |row| row.get::<_, String>(0))?;
    rows.map(|row| {
        serde_json::from_str(&row?).map_err(|err| StorageError::caused_by("DATABASE_ERROR", err))
    })
    .collect()
}

struct ResetInventory {
    snapshot: Value,
    next_revision: i64,
    preview: Value,
}

fn inventory(db: &Connection, root: &Path, course: &str) -> Result<ResetInventory, StorageError> {
    if course.trim().is_empty() {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let revision: i64 = db
        .query_row("SELECT version FROM courses WHERE id=?", [course], |row| {
            row.get(0)
        })
        .optional()?
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    let current: Option<String> = db.query_row("SELECT id FROM course_study_sessions WHERE course_id=? AND abandoned_at IS NULL ORDER BY revision DESC LIMIT 1", [course], |row| row.get(0)).optional()?;
    let (snapshot, content_hash) = match current {
        Some(id) => latest(
            db,
            root,
            &study_sessions::require(db, &id, Some(course), false)?,
        )?,
        None => material::capture(db, root, course, None)?,
    };
    let next_revision =
        study_sessions::current(db, course)?.map_or(2, |round| (round.revision + 1).max(2));
    let rounds = json_rows(db, "SELECT json_array(id,version,replace(abandoned_at,' ','T')) FROM course_study_sessions WHERE course_id=? ORDER BY id", course)?;
    let active: Vec<_> = rounds
        .iter()
        .filter(|row| row[2].is_null())
        .map(|row| &row[0])
        .collect();
    let answers = json_rows(db, "SELECT json_array(s.id,s.version,s.status) FROM submissions s JOIN exercises e ON e.id=s.exercise_id JOIN lessons l ON l.id=e.lesson_id WHERE l.course_id=? ORDER BY s.id", course)?;
    let training = json_rows(db, "SELECT json_array(t.study_session_id,t.version) FROM english_study_states t JOIN course_study_sessions s ON s.id=t.study_session_id WHERE s.course_id=? ORDER BY t.study_session_id", course)?;
    let receipts = json_rows(
        db,
        "SELECT json_quote(id) FROM course_write_receipts WHERE course_id=? ORDER BY id",
        course,
    )?;
    let progress = json_rows(db, "SELECT json_array(id,progress_percent,status,last_position) FROM learning_progress WHERE course_id=? ORDER BY id", course)?;
    let state_hash = Ascii.hash(&json!({"course_id":course,"content_revision":revision,"content_hash":content_hash,"rounds":rounds,"answers":answers,"training":training,"receipts":receipts,"progress":progress}));
    let preview = json!({"ok":true,"course_id":course,"content_revision":revision,"state_hash":state_hash,"content_hash":content_hash,
        "active_study_sessions":active,"counts":{"active_rounds":active.len(),"answer_records_retained":answers.len(),"legacy_reading_progress_cleared":progress.len()},
        "notes_retained":true,"history_retained":true,"effect":RESET_EFFECT});
    Ok(ResetInventory {
        snapshot,
        next_revision,
        preview,
    })
}

pub fn reset_preview(workspace: &Workspace, course: &str) -> Result<Value, StorageError> {
    workspace
        .read_consistent(|db| Ok(inventory(db, &workspace.settings().workspace, course)?.preview))
}

pub fn reset(workspace: &Workspace, course: &str, input: &Value) -> Result<Value, StorageError> {
    if input["confirm"] != true {
        return Err(StorageError::new("CONFIRMATION_REQUIRED"));
    }
    let digest = |field: &str| {
        input[field]
            .as_str()
            .filter(|s| {
                s.len() == 64
                    && s.bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            })
            .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))
    };
    let state_hash = digest("expected_state_hash")?;
    let content_hash = digest("expected_content_hash")?;
    let key = input["idempotency_key"]
        .as_str()
        .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?;
    validate_key(key)?;
    let fingerprint = Ascii
        .hash(&json!({"course_id":course,"state_hash":state_hash,"content_hash":content_hash}));
    let root = &workspace.settings().workspace;
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        if let Some(receipt) = replay_course(db, key, "LEARNING_RESET", &fingerprint)? {
            return Ok(receipt);
        }
        require_unused_round_key(db, key)?;
        if exists(
            db,
            "SELECT EXISTS(SELECT 1 FROM course_revisions WHERE idempotency_key=?)",
            [key],
        )? {
            return Err(StorageError::new("IDEMPOTENCY_KEY_CONFLICT"));
        }
        let current = inventory(db, root, course)?;
        if current.preview["content_hash"] != content_hash {
            return Err(StorageError::new("COURSE_CONTENT_CONFLICT"));
        }
        if current.preview["state_hash"] != state_hash {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        let sealed = material::seal_current(db, course, "用户授权外部Agent重置本课并采用最新材料")?;
        let id = insert_round(
            db,
            course,
            current.next_revision,
            key,
            current.snapshot,
            content_hash,
        )?;
        let result = json!({"ok":true,"course_id":course,"learning_state_reset":true,"study_session_id":id,
            "reset_study_sessions":sealed,"content_revision":current.preview["content_revision"],"content_hash":content_hash,
            "cleared_legacy_progress":current.preview["counts"]["legacy_reading_progress_cleared"],"history_retained":true,"notes_retained":true});
        record_receipt(
            db,
            course,
            &id,
            key,
            "LEARNING_RESET",
            &fingerprint,
            &result,
        )?;
        events::record(
            db,
            "AGENT_CLI",
            "course",
            course,
            "RESET_LEARNING",
            "获授权重置当前状态并采用最新材料，历史与笔记保留",
        )?;
        Ok(result)
    })
}

fn require_unused_round_key(db: &Connection, key: &str) -> Result<(), StorageError> {
    if exists(
        db,
        "SELECT EXISTS(SELECT 1 FROM course_study_sessions WHERE idempotency_key=?)",
        [key],
    )? {
        return Err(StorageError::new("IDEMPOTENCY_KEY_CONFLICT"));
    }
    Ok(())
}

fn insert_round(
    db: &Connection,
    course: &str,
    revision: i64,
    key: &str,
    snapshot: Value,
    content_hash: &str,
) -> Result<String, StorageError> {
    let id = Uuid::new_v4().to_string();
    db.execute("INSERT INTO course_study_sessions(id,course_id,revision,idempotency_key,new_version,snapshot_json,content_hash,progress_json,version,hint_tracking_enabled) VALUES(?,?,?,?,1,?,?,'{}',1,1)",
        params![id,course,revision,key,Utf8.serialize(&snapshot),content_hash])?;
    Ok(id)
}

fn record_receipt(
    db: &Connection,
    course: &str,
    study: &str,
    key: &str,
    operation: &str,
    hash: &str,
    result: &Value,
) -> Result<(), StorageError> {
    db.execute("INSERT INTO course_write_receipts(id,idempotency_key,course_id,study_session_id,operation,payload_hash,result_json) VALUES(?,?,?,?,?,?,?)",
        params![Uuid::new_v4().to_string(),key,course,study,operation,hash,result.to_string()])?;
    Ok(())
}
