use std::collections::HashSet;

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    decode, document::identity, find, invalid, legacy_save_fingerprint, receipt, rows,
    save_receipt, sources, text, timestamp, Row,
};
use crate::{
    application::write_contract::{atomic_write, require_version, validate_key, StoredReceipt},
    infrastructure::{events, fingerprint::JsonFingerprint::Utf8, StorageError},
    learning::study_sessions,
    workspace::Workspace,
};

pub(super) fn blocks_wire(row: Option<&Row>, plan: &str) -> Result<Value, StorageError> {
    let format = row.map_or(1, |row| row.format);
    if !matches!(format, 1 | 2) {
        return Err(StorageError::new("NOTEBOOK_FORMAT_UNSUPPORTED"));
    }
    let blocks: Vec<Value> = match row.filter(|row| row.format == 1) {
        Some(row) => decode(&row.blocks)?,
        None => vec![],
    };
    Ok(
        json!({"plan_line_id":plan,"format_version":format,"version":row.map_or(0,|row|row.version),"blocks":blocks,"updated_at":row.map(|row|timestamp(row.updated.clone()))}),
    )
}

pub fn get_blocks(db: &Connection, plan: &str) -> Result<Value, StorageError> {
    let mut data = blocks_wire(find(db, plan)?.as_ref(), plan)?;
    let mut query = db.prepare("SELECT n.id,n.text,s.id,c.id,c.title,n.lesson_id FROM study_notes n JOIN course_study_sessions s ON s.id=n.study_session_id JOIN courses c ON c.id=s.course_id WHERE c.plan_line_id=? AND n.text<>'' ORDER BY n.created_at,n.rowid")?;
    let notes = query.query_map([plan], |row| {
        let values = (0..6).map(|i|row.get::<_,String>(i)).collect::<Result<Vec<_>,_>>()?;
        Ok(json!({"id":values[0],"text":values[1],"study_session_id":values[2],"course_id":values[3],"course_title":values[4],"lesson_id":values[5]}))
    })?.collect::<Result<Vec<_>,_>>()?;
    data["legacy_notes"] = json!(notes);
    Ok(data)
}

fn blocks(db: &Connection, plan: &str, input: &[Value]) -> Result<Vec<Value>, StorageError> {
    if input.len() > 1000 {
        return Err(invalid());
    }
    let mut ids = HashSet::new();
    let mut total = 0;
    let mut result = Vec::with_capacity(input.len());
    for item in input {
        let id = identity(&item["id"])?;
        let content = item
            .get("text")
            .map_or(Some(""), Value::as_str)
            .filter(|value| value.chars().count() <= 200_000)
            .ok_or_else(invalid)?;
        let quote = item
            .get("quote")
            .map_or(Some(""), Value::as_str)
            .filter(|value| value.chars().count() <= 20_000)
            .ok_or_else(invalid)?;
        if !ids.insert(id) {
            return Err(invalid());
        }
        total += content.chars().count() + quote.chars().count();
        let optional_id = |key: &str| match &item[key] {
            Value::Null => Ok(Value::Null),
            Value::String(id) if id.is_empty() => Ok(Value::Null),
            value @ Value::String(_) => Ok(value.clone()),
            _ => Err(invalid()),
        };
        let course = optional_id("course_id")?;
        let lesson = optional_id("lesson_id")?;
        let study = optional_id("source_study_id")?;
        let scope = sources::scope(&course, &lesson);
        let mut block = if quote.is_empty() && study.is_null() {
            sources::membership(db, plan, &course, &lesson, scope)?
        } else {
            if quote.is_empty() || study.is_null() || course.is_null() || lesson.is_null() {
                return Err(invalid());
            }
            let mut source = json!({"id":id,"original":quote,"course_id":course,"lesson_id":lesson,"source_study_id":study});
            if !item["source_block_id"].is_null() {
                if !item["source_block_id"].is_string() || text(&item["source_block_id"]).is_empty()
                {
                    return Err(invalid());
                }
                source["source_block_id"] = item["source_block_id"].clone();
            }
            let verified = sources::verify(db, plan, &source, true)?;
            let mut value = json!({"scope":scope,"course_id":course,"lesson_id":lesson,"course_title":verified["course_title"],"lesson_title":verified["lesson_title"],"content_hash":verified["content_hash"]});
            if let Some(block_id) = source.get("source_block_id") {
                value["source_block_id"] = block_id.clone();
            }
            value
        };
        if block.get("content_hash").is_none() {
            block["content_hash"] = Value::Null;
        }
        block["id"] = json!(id);
        block["text"] = json!(content);
        block["quote"] = json!(quote);
        block["source_study_id"] = study;
        result.push(block);
    }
    if total > 1_000_000 {
        return Err(invalid());
    }
    Ok(result)
}

pub fn save_blocks(
    workspace: &Workspace,
    input: &Value,
    actor: &str,
) -> Result<Value, StorageError> {
    let plan = text(&input["plan_line_id"]);
    let version = input["expected_version"]
        .as_i64()
        .filter(|v| *v >= 0)
        .ok_or_else(invalid)?;
    let key = text(&input["idempotency_key"]);
    validate_key(key)?;
    let input_blocks = input["blocks"].as_array().ok_or_else(invalid)?;
    let hash = legacy_save_fingerprint(plan, input_blocks, version);
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        let row = find(db, plan)?;
        if let Some(replay) = receipt(db, plan, key, &hash)? {
            return Ok(replay);
        }
        if row.as_ref().is_some_and(|row| row.format != 1) {
            return Err(StorageError::new("NOTEBOOK_FORMAT_UPGRADE_REQUIRED"));
        }
        require_version(row.as_ref().map_or(0, |row| row.version), version)?;
        let normalized = json!(blocks(db, plan, input_blocks)?).to_string();
        let id = if let Some(row) = row {
            let changed = db.execute("UPDATE plan_notebooks SET blocks_json=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?",params![normalized,row.id,version])?;
            if changed != 1 {
                return Err(StorageError::new("VERSION_CONFLICT"));
            }
            row.id
        } else {
            let id = Uuid::new_v4().to_string();
            db.execute(
                "INSERT INTO plan_notebooks(id,plan_line_id,blocks_json) VALUES(?,?,?)",
                params![id, plan, normalized],
            )?;
            id
        };
        let result = blocks_wire(find(db, plan)?.as_ref(), plan)?;
        save_receipt(db, plan, key, &hash, &result)?;
        events::record(db, actor, "plan_notebook", &id, "SAVE", "计划学习笔记更新")?;
        Ok(result)
    })
}

fn note(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    Ok(
        json!({"id":row.get::<_,String>(0)?,"lesson_id":row.get::<_,String>(1)?,"text":row.get::<_,String>(2)?,"version":row.get::<_,i64>(3)?,"updated_at":row.get::<_,Option<String>>(4)?.map(timestamp)}),
    )
}

pub fn get_notes(db: &Connection, study: &str) -> Result<Value, StorageError> {
    study_sessions::require(db, study, None, false)?;
    let mut query = db.prepare("SELECT id,lesson_id,text,version,updated_at FROM study_notes WHERE study_session_id=? ORDER BY rowid")?;
    let notes = query
        .query_map([study], note)?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(json!({"study_session_id":study,"notes":notes}))
}

pub fn save_note(workspace: &Workspace, input: &Value, actor: &str) -> Result<Value, StorageError> {
    let study = text(&input["study_session_id"]);
    let lesson = text(&input["lesson_id"]);
    let content = input["text"]
        .as_str()
        .filter(|text| text.chars().count() <= 200_000)
        .ok_or_else(invalid)?;
    let key = text(&input["idempotency_key"]);
    let version = input["expected_version"]
        .as_i64()
        .filter(|v| *v >= 0)
        .ok_or_else(invalid)?;
    validate_key(key)?;
    let hash = Utf8.hash(&json!([study, lesson, content, version]));
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        let receipt = db
            .query_row(
                "SELECT payload_hash,result_json FROM study_note_receipts WHERE idempotency_key=?",
                [key],
                |row| {
                    Ok(StoredReceipt {
                        operation: None,
                        payload_hash: row.get(0)?,
                        result_json: row.get(1)?,
                    })
                },
            )
            .optional()?;
        if let Some(receipt) = receipt {
            return receipt.replay(None, &hash);
        }
        let round = study_sessions::require(db, study, None, false)?;
        if round.abandoned.is_some() {
            return Err(StorageError::new("STUDY_CLOSED"));
        }
        if !rows(&round.snapshot["lessons"])
            .iter()
            .any(|entry| entry["id"] == lesson)
        {
            return Err(invalid());
        }
        let existing: Option<(String, i64)> = db
            .query_row(
                "SELECT id,version FROM study_notes WHERE study_session_id=? AND lesson_id=?",
                params![study, lesson],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        require_version(
            existing.as_ref().map_or(0, |(_, version)| *version),
            version,
        )?;
        let id = if let Some((id, _)) = existing {
            let changed = db.execute("UPDATE study_notes SET text=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?",params![content,id,version])?;
            if changed != 1 {
                return Err(StorageError::new("VERSION_CONFLICT"));
            }
            id
        } else {
            let id = Uuid::new_v4().to_string();
            db.execute(
                "INSERT INTO study_notes(id,study_session_id,lesson_id,text) VALUES(?,?,?,?)",
                params![id, study, lesson, content],
            )?;
            id
        };
        let result = json!({"study_session_id":study,"note":db.query_row("SELECT id,lesson_id,text,version,updated_at FROM study_notes WHERE id=?",[&id],note)?});
        db.execute("INSERT INTO study_note_receipts(id,idempotency_key,study_session_id,payload_hash,result_json) VALUES(?,?,?,?,?)",params![Uuid::new_v4().to_string(),key,study,hash,result.to_string()])?;
        events::record(db, actor, "study_note", &id, "SAVE", "知识点私人草稿更新")?;
        Ok(result)
    })
}
