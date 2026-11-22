use rusqlite::Connection;
use serde_json::{json, Value};

use crate::{
    application::write_contract::atomic_write,
    infrastructure::{events, fingerprint::JsonFingerprint::CompactUtf8, StorageError},
    workspace::Workspace,
};

fn inventory(db: &Connection, root: &std::path::Path) -> Result<Value, StorageError> {
    let mut statement = db.prepare(
        "SELECT id,study_session_id,lesson_id,version,text FROM study_notes ORDER BY id",
    )?;
    let notes = statement
        .query_map([], |row| {
            Ok(json!([
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, String>(4)?
            ]))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    let mut statement = db.prepare(
        "SELECT id,idempotency_key,payload_hash,result_json FROM study_note_receipts ORDER BY id",
    )?;
    let receipts = statement
        .query_map([], |row| {
            Ok(json!([
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?
            ]))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    let token = CompactUtf8.hash(&json!([root, notes, receipts]));
    Ok(
        json!({"scope":"legacy-study-notes","workspace_root":root,"note_count":notes.len(),
        "nonempty_note_count":notes.iter().filter(|row|row[4]!="").count(),"receipt_count":receipts.len(),"preview_token":token,
        "preserved":["plan_notebooks","plan_notebook_sources","courses","course_study_sessions","answers","submissions","reviews","retests"]}),
    )
}

pub fn preview(workspace: &Workspace) -> Result<Value, StorageError> {
    workspace.read_consistent(|db| inventory(db, &workspace.settings().workspace))
}

pub fn purge(workspace: &Workspace, token: &str) -> Result<Value, StorageError> {
    if token.len() != 64 {
        return Err(StorageError::new("PREVIEW_REQUIRED"));
    }
    let root = &workspace.settings().workspace;
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        if inventory(db, root)?["preview_token"] != token {
            return Err(StorageError::new("PREVIEW_CHANGED"));
        }
        let receipts = db.execute("DELETE FROM study_note_receipts", [])?;
        let notes = db.execute("DELETE FROM study_notes", [])?;
        if notes + receipts != 0 {
            events::record(
                db,
                "AGENT_CLI",
                "legacy_study_notes",
                "workspace",
                "PURGE",
                &format!(
                    "用户授权删除旧草稿{notes}条、保存回执{receipts}条；保留计划笔记及学习作答"
                ),
            )?;
        }
        let mut data = inventory(db, root)?;
        data["deleted_notes"] = json!(notes);
        data["deleted_receipts"] = json!(receipts);
        Ok(data)
    })
}
