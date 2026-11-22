use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use super::retest_task;
use crate::{
    application::write_contract::{atomic_write, validate_key},
    infrastructure::{events, fingerprint::JsonFingerprint::Ascii, StorageError},
    workspace::Workspace,
};

pub fn publish(workspace: &Workspace, input: &Value) -> Result<Value, StorageError> {
    let text = |key: &str, max: usize, default: Option<&'static str>| {
        input
            .get(key)
            .map_or(default, Value::as_str)
            .filter(|value| {
                value.chars().count() <= max && (default.is_some() || !value.trim().is_empty())
            })
            .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))
    };
    let parent = text("parent_submission_id", 20_000, None)?;
    let title = text("title", 200, None)?;
    let prompt = text("prompt", 20_000, None)?;
    let requirements = text("requirements", 20_000, Some(""))?;
    let objective = text("objective", 20_000, None)?;
    let agent_reference = text("agent_reference", 20_000, Some(""))?;
    let key = text("idempotency_key", 160, None)?;
    validate_key(key)?;
    let hash=Ascii.hash(&json!({"parent_submission_id":parent,"title":title,"prompt":prompt,"requirements":requirements,"objective":objective,"agent_reference":agent_reference}));
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        let previous = db
            .query_row(
                "SELECT id,payload_hash FROM retest_tasks WHERE idempotency_key=?",
                [key],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?;
        if let Some((id, stored)) = previous {
            if stored != hash {
                return Err(StorageError::new("IDEMPOTENCY_KEY_CONFLICT"));
            }
            return retest_task(db, None, Some(&id))?
                .ok_or_else(|| StorageError::new("DATABASE_ERROR"));
        }
        let study = db
            .query_row(
                "SELECT study_session_id FROM submissions WHERE id=? AND status='RETEST_REQUIRED'",
                [parent],
                |row| row.get::<_, Option<String>>(0),
            )
            .optional()?
            .ok_or_else(|| StorageError::new("INVALID_ATTEMPT_SOURCE"))?;
        let already:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM submissions WHERE parent_submission_id=?1) OR EXISTS(SELECT 1 FROM retest_tasks WHERE parent_submission_id=?1)",[parent],|row|row.get(0))?;
        if already {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        let id = Uuid::new_v4().to_string();
        db.execute("INSERT INTO retest_tasks(id,parent_submission_id,study_session_id,title,prompt,requirements,objective,agent_reference,status,idempotency_key,payload_hash) VALUES(?,?,?,?,?,?,?,?,'READY',?,?)",params![id,parent,study,title,prompt,requirements,objective,agent_reference,key,hash])?;
        events::record(
            db,
            "AGENT_CLI",
            "retest",
            &id,
            "PUBLISH",
            "发布冻结复测题面",
        )?;
        retest_task(db, None, Some(&id))?.ok_or_else(|| StorageError::new("DATABASE_ERROR"))
    })
}
