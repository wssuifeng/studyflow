mod document;
mod legacy;
mod sources;

use std::collections::{BTreeMap, BTreeSet};

use icu_casemap::CaseMapper;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    application::write_contract::{atomic_write, require_version, validate_key, StoredReceipt},
    infrastructure::{events, fingerprint::JsonFingerprint::Utf8, StorageError},
    workspace::Workspace,
};

pub use legacy::{get_blocks, get_notes, save_blocks, save_note};

pub fn apply_fingerprint(
    plan: &str,
    version: i64,
    operations: &[Value],
    sources: &[Value],
) -> String {
    Utf8.hash(&json!([plan, version, operations, sources]))
}

pub fn legacy_save_fingerprint(plan: &str, blocks: &[Value], version: i64) -> String {
    Utf8.hash(&json!([plan, blocks, version]))
}

fn invalid() -> StorageError {
    StorageError::new("INVALID_ARGUMENT")
}
fn text(value: &Value) -> &str {
    value.as_str().unwrap_or_default()
}
fn rows(value: &Value) -> &[Value] {
    value.as_array().map_or(&[], Vec::as_slice)
}
fn decode<T: serde::de::DeserializeOwned>(value: &str) -> Result<T, StorageError> {
    serde_json::from_str(value).map_err(|error| StorageError::caused_by("DATABASE_ERROR", error))
}
fn timestamp(value: String) -> String {
    let value = value.replacen(' ', "T", 1);
    value.strip_suffix(".000000").unwrap_or(&value).to_owned()
}

struct Row {
    id: String,
    version: i64,
    format: i64,
    blocks: String,
    document: String,
    updated: String,
}

fn find(db: &Connection, plan: &str) -> Result<Option<Row>, StorageError> {
    let exists: bool = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM plan_lines WHERE id=?)",
        [plan],
        |row| row.get(0),
    )?;
    if !exists {
        return Err(StorageError::new("OBJECT_NOT_FOUND"));
    }
    Ok(db.query_row("SELECT id,version,format_version,blocks_json,document_json,updated_at FROM plan_notebooks WHERE plan_line_id=?", [plan], |row|Ok(Row {id:row.get(0)?,version:row.get(1)?,format:row.get(2)?,blocks:row.get(3)?,document:row.get(4)?,updated:row.get(5)?})).optional()?)
}

#[derive(Default)]
struct Record {
    entries: Vec<Value>,
    sources: BTreeMap<String, Value>,
}

fn state(db: &Connection, plan: &str, row: Option<&Row>) -> Result<Record, StorageError> {
    let Some(row) = row else {
        return Ok(Record::default());
    };
    match row.format {
        1 => {
            let blocks: Vec<Value> = decode(&row.blocks)?;
            let (entries, sources) = sources::legacy(db, plan, &blocks)?;
            Ok(Record { entries, sources })
        }
        2 => {
            let document: Value = decode(&row.document)?;
            let entries = document["entries"]
                .as_array()
                .cloned()
                .ok_or_else(|| StorageError::new("DATABASE_ERROR"))?;
            let sources = stored_sources(db, &row.id)?
                .into_iter()
                .map(|item| (text(&item["id"]).to_owned(), item))
                .collect();
            Ok(Record { entries, sources })
        }
        _ => Err(StorageError::new("NOTEBOOK_FORMAT_UNSUPPORTED")),
    }
}

fn stored_sources(db: &Connection, id: &str) -> Result<Vec<Value>, StorageError> {
    let mut query = db.prepare(
        "SELECT data_json FROM plan_notebook_sources WHERE notebook_id=? ORDER BY rowid",
    )?;
    let rows = query.query_map([id], |row| row.get::<_, String>(0))?;
    rows.map(|row| decode(&row?)).collect()
}

fn receipt(
    db: &Connection,
    plan: &str,
    key: &str,
    hash: &str,
) -> Result<Option<Value>, StorageError> {
    let existing = db.query_row("SELECT plan_line_id,payload_hash,result_json FROM plan_notebook_receipts WHERE idempotency_key=?", [key], |row|Ok(StoredReceipt { operation:row.get(0)?,payload_hash:row.get(1)?,result_json:row.get(2)? })).optional()?;
    existing
        .map(|receipt| receipt.replay(Some(plan), hash))
        .transpose()
}

fn save_receipt(
    db: &Connection,
    plan: &str,
    key: &str,
    hash: &str,
    result: &Value,
) -> Result<(), StorageError> {
    db.execute("INSERT INTO plan_notebook_receipts(id,plan_line_id,idempotency_key,payload_hash,result_json) VALUES(?,?,?,?,?)", params![Uuid::new_v4().to_string(),plan,key,hash,result.to_string()])?;
    Ok(())
}

pub fn read(db: &Connection, input: &Value) -> Result<Value, StorageError> {
    let plan = text(&input["plan_line_id"]);
    let offset = input
        .get("offset")
        .map_or(Some(0), Value::as_u64)
        .ok_or_else(invalid)?;
    let limit = input
        .get("limit")
        .map_or(Some(100), Value::as_u64)
        .filter(|lim| (1..=100).contains(lim))
        .ok_or_else(invalid)?;
    let query = input
        .get("query")
        .map_or(Some(""), Value::as_str)
        .filter(|query| query.chars().count() <= 200)
        .ok_or_else(invalid)?;
    let entry_ids = match &input["entry_ids"] {
        Value::Null => None,
        Value::Array(ids) if (1..=100).contains(&ids.len()) && ids.iter().all(Value::is_string) => {
            Some(ids)
        }
        _ => return Err(invalid()),
    };
    let row = find(db, plan)?;
    let version = row.as_ref().map_or(0, |row| row.version);
    if !input["expected_version"].is_null() {
        let expected = input["expected_version"]
            .as_i64()
            .filter(|v| *v >= 0)
            .ok_or_else(invalid)?;
        require_version(version, expected)?;
    }
    let doc = state(db, plan, row.as_ref())?;
    let case = CaseMapper::new();
    let query = case.fold_string(query).into_owned();
    let matches: Vec<_> = doc
        .entries
        .into_iter()
        .filter(|entry| {
            scope_matches(entry, input)
                && entry_ids.is_none_or(|ids| ids.contains(&entry["id"]))
                && (query.is_empty()
                    || case
                        .fold_string(&document::plain(&entry["content"]))
                        .contains(&query))
        })
        .collect();
    let total = matches.len() as u64;
    let page: Vec<_> = matches
        .into_iter()
        .skip(offset.min(total) as usize)
        .take(limit as usize)
        .collect();
    let citations = document::citations(&page, &doc.sources)?;
    let references: BTreeSet<_> = citations
        .iter()
        .map(|entry| text(&entry["source_id"]))
        .collect();
    let sources: Vec<_> = references
        .into_iter()
        .filter_map(|id| doc.sources.get(id))
        .collect();
    let next = offset.saturating_add(limit);
    Ok(
        json!({"plan_line_id":plan,"version":version,"format_version":row.as_ref().map_or(2,|row|row.format),"entries":page,"sources":sources,"citations":citations,"offset":offset,"total":total,"next_cursor":(next<total).then_some(next),"updated_at":row.map(|row|timestamp(row.updated))}),
    )
}

fn scope_matches(entry: &Value, input: &Value) -> bool {
    ["course_id", "lesson_id"]
        .into_iter()
        .all(|key| text(&input[key]).is_empty() || entry[key] == input[key])
}

pub fn search(db: &Connection, input: &Value) -> Result<Value, StorageError> {
    let plan = text(&input["plan_line_id"]);
    let row = find(db, plan)?;
    if row.as_ref().is_some_and(|row| row.format == 2) {
        return read(db, input);
    }
    let result = legacy::blocks_wire(row.as_ref(), plan)?;
    let case = CaseMapper::new();
    let query = case.fold_string(text(&input["query"])).into_owned();
    let blocks: Vec<_> = rows(&result["blocks"])
        .iter()
        .filter(|entry| {
            scope_matches(entry, input)
                && (query.is_empty()
                    || case
                        .fold_string(&format!(
                            "{} {}",
                            text(&entry["text"]),
                            text(&entry["quote"])
                        ))
                        .contains(&query))
        })
        .collect();
    Ok(
        json!({"plan_line_id":plan,"version":result["version"],"blocks":blocks,"count":blocks.len()}),
    )
}

pub fn export(db: &Connection, plan: &str) -> Result<Value, StorageError> {
    let row = find(db, plan)?;
    if let Some(row) = row.as_ref().filter(|row| row.format == 2) {
        let doc: Value = decode(&row.document)?;
        let sources = stored_sources(db, &row.id)?;
        let markdown = rows(&doc["entries"])
            .iter()
            .map(|entry| document::plain(&entry["content"]))
            .collect::<Vec<_>>()
            .join("\n\n");
        return Ok(
            json!({"filename":"StudyFlow-学习笔记.json","document":{"entries":doc["entries"],"sources":sources},"format_version":2,"version":row.version,"markdown":markdown,"markdown_lossy":true}),
        );
    }
    let data = legacy::blocks_wire(row.as_ref(), plan)?;
    let mut lines = vec![
        "# 学习笔记".to_owned(),
        "".into(),
        format!("计划：{plan}"),
        "".into(),
    ];
    for block in rows(&data["blocks"]) {
        let title = ["lesson_title", "course_title"]
            .into_iter()
            .map(|key| text(&block[key]))
            .find(|title| !title.is_empty())
            .unwrap_or("计划笔记");
        lines.extend([format!("## {title}"), "".into()]);
        if !text(&block["quote"]).is_empty() {
            lines.extend([
                format!("> {}", text(&block["quote"]).replace('\n', "\n> ")),
                "".into(),
            ]);
        }
        lines.extend([text(&block["text"]).to_owned(), "".into()]);
        if !text(&block["source_study_id"]).is_empty() {
            lines.extend([
                format!(
                    "来源学习轮次：{} · 知识点：{} · 内容版本：{}",
                    text(&block["source_study_id"]),
                    text(&block["lesson_id"]),
                    text(&block["content_hash"])
                ),
                "".into(),
            ]);
        }
    }
    Ok(
        json!({"filename":"StudyFlow-学习笔记.md","markdown":lines.join("\n"),"version":data["version"]}),
    )
}

fn same_scope(a: &Value, b: &Value) -> bool {
    ["scope", "course_id", "lesson_id"]
        .into_iter()
        .all(|field| a[field] == b[field])
}

fn place(
    entries: &mut Vec<Value>,
    entry: Value,
    after: Option<&Value>,
) -> Result<(), StorageError> {
    let index = match after {
        None => entries
            .iter()
            .rposition(|existing| same_scope(existing, &entry))
            .map(|i| i + 1),
        Some(Value::Null) => entries
            .iter()
            .position(|existing| same_scope(existing, &entry)),
        Some(id) => Some(
            entries
                .iter()
                .position(|existing| existing["id"] == *id && same_scope(existing, &entry))
                .ok_or_else(invalid)?
                + 1,
        ),
    }
    .unwrap_or(entries.len());
    entries.insert(index, entry);
    Ok(())
}

fn edit(
    db: &Connection,
    plan: &str,
    record: &mut Record,
    op: &Value,
) -> Result<String, StorageError> {
    use document::{check_content, fields, identity};
    let kind = text(&op["type"]);
    let allowed: &[&str] = match kind {
        "insert_entry" => &["type", "entry", "after_id"],
        "replace_entry" => &["type", "entry_id", "content"],
        "remove_entry" => &["type", "entry_id"],
        "move_entry" => &[
            "type",
            "entry_id",
            "scope",
            "course_id",
            "lesson_id",
            "after_id",
        ],
        _ => return Err(invalid()),
    };
    if !fields(op, allowed) {
        return Err(invalid());
    }
    let entries = &mut record.entries;
    let id = if kind == "insert_entry" {
        let entry = &op["entry"];
        if !fields(entry, &["id", "scope", "course_id", "lesson_id", "content"]) {
            return Err(invalid());
        }
        let id = identity(&entry["id"])?;
        if entries.iter().any(|entry| entry["id"] == id) {
            return Err(invalid());
        }
        let course = &entry["course_id"];
        let lesson = &entry["lesson_id"];
        let scope = entry
            .get("scope")
            .map_or(sources::scope(course, lesson), text);
        let mut value = sources::membership(db, plan, course, lesson, scope)?;
        check_content(&entry["content"], &mut 0, &record.sources)?;
        value["id"] = json!(id);
        value["content"] = entry["content"].clone();
        place(entries, value, op.get("after_id"))?;
        id
    } else {
        let id = identity(&op["entry_id"])?;
        let index = entries
            .iter()
            .position(|entry| entry["id"] == id)
            .ok_or_else(invalid)?;
        match kind {
            "replace_entry" => {
                check_content(&op["content"], &mut 0, &record.sources)?;
                entries[index]["content"] = op["content"].clone();
            }
            "remove_entry" => {
                entries.remove(index);
            }
            _ => {
                let mut entry = entries.remove(index);
                let scope = sources::membership(
                    db,
                    plan,
                    &op["course_id"],
                    &op["lesson_id"],
                    text(&op["scope"]),
                )?;
                entry
                    .as_object_mut()
                    .unwrap()
                    .extend(scope.as_object().unwrap().clone());
                place(entries, entry, op.get("after_id"))?;
            }
        }
        id
    };
    Ok(id.into())
}

pub fn apply(workspace: &Workspace, input: &Value, actor: &str) -> Result<Value, StorageError> {
    let plan = text(&input["plan_line_id"]);
    let version = input["expected_version"]
        .as_i64()
        .filter(|version| *version >= 0)
        .ok_or_else(invalid)?;
    let key = text(&input["idempotency_key"]);
    validate_key(key)?;
    let operations = input["operations"]
        .as_array()
        .filter(|ops| ops.len() <= 2000)
        .ok_or_else(invalid)?;
    let sources = match &input["new_sources"] {
        Value::Null => &[][..],
        Value::Array(sources) if sources.len() <= 100 => sources,
        _ => return Err(invalid()),
    };
    let fingerprint = json!([plan, version, operations, sources]);
    if Utf8.serialize(&fingerprint).len() > 8_000_000 {
        return Err(invalid());
    }
    let hash = apply_fingerprint(plan, version, operations, sources);
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        let row = find(db, plan)?;
        if let Some(replay) = receipt(db, plan, key, &hash)? {
            return Ok(replay);
        }
        require_version(row.as_ref().map_or(0, |row| row.version), version)?;
        let mut record = state(db, plan, row.as_ref())?;
        let mut added: Vec<String> = if row.as_ref().is_some_and(|row| row.format == 1) {
            record.sources.keys().cloned().collect()
        } else {
            Vec::new()
        };
        for item in sources {
            let id = document::identity(&item["id"])?;
            if let Some(current) = record.sources.get(id) {
                if item
                    .as_object()
                    .unwrap()
                    .iter()
                    .any(|(field, value)| current[field] != *value)
                {
                    return Err(StorageError::new("NOTEBOOK_SOURCE_IMMUTABLE"));
                }
            } else {
                record
                    .sources
                    .insert(id.to_owned(), self::sources::verify(db, plan, item, false)?);
                added.push(id.to_owned());
            }
        }
        if record.sources.len() > 10_000 {
            return Err(invalid());
        }
        let mut changed = Vec::new();
        for operation in operations {
            let id = edit(db, plan, &mut record, operation)?;
            if !changed.contains(&id) {
                changed.push(id);
            }
        }
        document::validate(&record)?;
        let document = json!({"entries":record.entries}).to_string();
        let id = if let Some(row) = row {
            let updated = db.execute("UPDATE plan_notebooks SET document_json=?,format_version=2,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?",params![document,row.id,version])?;
            if updated != 1 {
                return Err(StorageError::new("VERSION_CONFLICT"));
            }
            row.id
        } else {
            let id = Uuid::new_v4().to_string();
            db.execute("INSERT INTO plan_notebooks(id,plan_line_id,document_json,format_version) VALUES(?,?,?,2)",params![id,plan,document])?;
            id
        };
        for source in &added {
            db.execute(
                "INSERT INTO plan_notebook_sources(notebook_id,id,data_json) VALUES(?,?,?)",
                params![id, source, record.sources[source].to_string()],
            )?;
        }
        let updated: String = db.query_row(
            "SELECT updated_at FROM plan_notebooks WHERE id=?",
            [&id],
            |row| row.get(0),
        )?;
        let published: Vec<_> = sources
            .iter()
            .map(|source| &record.sources[text(&source["id"])])
            .collect();
        let result = json!({"plan_line_id":plan,"format_version":2,"version":version+1,"changed_entry_ids":changed,"updated_at":timestamp(updated),"sources":published});
        save_receipt(db, plan, key, &hash, &result)?;
        events::record(db, actor, "plan_notebook", &id, "APPLY", "计划笔记增量更新")?;
        Ok(result)
    })
}
pub mod cleanup;
