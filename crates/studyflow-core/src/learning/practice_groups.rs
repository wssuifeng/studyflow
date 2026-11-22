use std::path::Path;

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};
use uuid::Uuid;

use super::{
    attempt_history::scoped_summaries,
    study_sessions::{self, Round},
};
use crate::{
    application::write_contract::{require_version, validate_key, StoredReceipt},
    courses::practice::{self, GroupKind, PreviewError},
    infrastructure::{events, fingerprint::JsonFingerprint, StorageError},
    workspace::Workspace,
};

fn group<'a>(round: &'a Round, exercise: &str, kind: GroupKind) -> Result<&'a Value, StorageError> {
    let category = match kind {
        GroupKind::Reading => "READING_GROUP",
        GroupKind::Listening => "LISTENING_GROUP",
    };
    round.snapshot["lessons"]
        .as_array()
        .into_iter()
        .flatten()
        .flat_map(|lesson| lesson["exercises"].as_array().into_iter().flatten())
        .find(|item| item["id"] == exercise && item["type"] == category)
        .and_then(|item| item.get(kind.field()))
        .filter(|item| item.is_object())
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))
}

struct Attempt {
    id: String,
    version: i64,
    status: String,
    answer: String,
}

fn attempt(db: &Connection, study: &str, exercise: &str) -> Result<Option<Attempt>, StorageError> {
    Ok(db.query_row("SELECT id,version,status,answer_text FROM submissions WHERE study_session_id=? AND exercise_id=? ORDER BY attempt_number DESC,id DESC LIMIT 1",params![study,exercise],
        |row|Ok(Attempt{id:row.get(0)?,version:row.get(1)?,status:row.get(2)?,answer:row.get(3)?})).optional()?)
}

pub fn get(
    db: &Connection,
    study: &str,
    exercise: &str,
    kind: GroupKind,
) -> Result<Value, StorageError> {
    let round = study_sessions::require(db, study, None, false)?;
    let spec = group(&round, exercise, kind)?;
    let state = if let Some(attempt) = attempt(db, study, exercise)? {
        let mut state: Value = serde_json::from_str(&attempt.answer)
            .map_err(|err| StorageError::caused_by("DATABASE_ERROR", err))?;
        if !state.is_object() {
            return Err(StorageError::new("DATABASE_ERROR"));
        }
        state["version"] = json!(attempt.version);
        state
    } else {
        json!({"version":0,"answers":{},"position":0,"result":null})
    };
    let read_only = !state["result"].is_null()
        || round.abandoned.is_some()
        || study_sessions::current(db, &round.course)?.is_none_or(|current| current.id != study);
    Ok(practice::public_group(spec, kind, state, read_only))
}

pub struct WriteRequest<'a> {
    pub study: &'a str,
    pub exercise: &'a str,
    pub answers: &'a Map<String, Value>,
    pub key: &'a str,
    pub position: usize,
    pub version: i64,
    pub kind: GroupKind,
    pub confirm: bool,
}

pub fn write(workspace: &Workspace, request: WriteRequest<'_>) -> Result<Value, PreviewError> {
    validate_key(request.key).map_err(PreviewError::Storage)?;
    let mut active = workspace.open().map_err(PreviewError::Storage)?;
    let tx = active
        .connection
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(StorageError::from)
        .map_err(PreviewError::Storage)?;
    let response = write_group(&tx, &workspace.settings().workspace, request)?;
    tx.commit()
        .map_err(StorageError::from)
        .map_err(PreviewError::Storage)?;
    Ok(response)
}

fn write_group(
    db: &Connection,
    root: &Path,
    request: WriteRequest<'_>,
) -> Result<Value, PreviewError> {
    let WriteRequest {
        study,
        exercise,
        answers,
        key,
        position,
        version,
        kind,
        confirm,
    } = request;
    let operation = match (kind, confirm) {
        (GroupKind::Reading, false) => "READING_SAVE",
        (GroupKind::Reading, true) => "READING_CONFIRM",
        (GroupKind::Listening, false) => "LISTENING_SAVE",
        (GroupKind::Listening, true) => "LISTENING_CONFIRM",
    };
    let hash = JsonFingerprint::Ascii.hash(&json!([
        operation, study, exercise, answers, position, version
    ]));
    let receipt=db.query_row("SELECT operation,payload_hash,result_json FROM course_write_receipts WHERE idempotency_key=?",[key],
        |row|Ok(StoredReceipt{operation:row.get(0)?,payload_hash:row.get(1)?,result_json:row.get(2)?})).optional()?;
    if let Some(receipt) = receipt {
        return Ok(receipt.replay(Some(operation), &hash)?);
    }
    let round = study_sessions::require(db, study, None, true)?;
    let spec = group(&round, exercise, kind)?;
    let attempt = attempt(db, study, exercise)?;
    require_version(attempt.as_ref().map_or(0, |row| row.version), version)?;
    if attempt.as_ref().is_some_and(|row| row.status != "DRAFT") {
        return Err(StorageError::new("INVALID_STATE_TRANSITION").into());
    }
    if position >= spec["questions"].as_array().map_or(0, Vec::len) {
        return Err(PreviewError::Invalid("题号超出题组范围。"));
    }
    let result = practice::evaluate(spec, answers, kind, confirm)?;
    if confirm && matches!(kind, GroupKind::Listening) {
        practice::read_audio(root, spec)?;
    }
    let state = json!({"answers":answers,"position":position,"result":result});
    let status = if confirm { "PASSED" } else { "DRAFT" };
    let next = if confirm {
        "查看题组解析。"
    } else {
        "继续题组练习。"
    };
    let receipt_id = Uuid::new_v4().to_string();
    let batch = confirm.then_some(receipt_id.as_str());
    let id = if let Some(row) = attempt {
        let changed=db.execute("UPDATE submissions SET version=version+1,status=?,batch_id=?,answer_text=?,next_action=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=? AND status='DRAFT'",
            params![status,batch,state.to_string(),next,row.id,version])?;
        if changed != 1 {
            return Err(StorageError::new("VERSION_CONFLICT").into());
        }
        row.id
    } else {
        let id = Uuid::new_v4().to_string();
        db.execute("INSERT INTO submissions(id,exercise_id,study_session_id,attempt_number,attempt_kind,source,status,version,batch_id,answer_text,next_action)
            VALUES(?,?,?,(SELECT COALESCE(MAX(attempt_number),0)+1 FROM submissions WHERE exercise_id=?2),'FIRST','USER_ENGINE',?,1,?,?,?)",
            params![id,exercise,study,status,batch,state.to_string(),next])?;
        id
    };
    let ids = round.ids();
    let summaries = scoped_summaries(db, &ids, Some(round.scope()), false)?;
    let mut response = state;
    response["version"] = json!(version + 1);
    response["course_submitted"] =
        study_sessions::outcome(&round, &ids, &summaries)["learning_submitted"].clone();
    if confirm && matches!(kind, GroupKind::Listening) {
        response["transcript"] = spec["transcript"].clone();
    }
    events::record(db, "USER_ENGINE", "submission", &id, operation, next)?;
    db.execute("INSERT INTO course_write_receipts(id,idempotency_key,operation,course_id,study_session_id,payload_hash,result_json) VALUES(?,?,?,?,?,?,?)",
        params![receipt_id,key,operation,round.course,study,hash,response.to_string()])?;
    Ok(response)
}

pub fn listening_asset(
    db: &Connection,
    root: &Path,
    study: &str,
    exercise: &str,
    captions: bool,
) -> Result<Value, PreviewError> {
    let round = study_sessions::require(db, study, None, false)?;
    let spec = group(&round, exercise, GroupKind::Listening)?;
    if captions {
        return Ok(practice::caption_payload(spec));
    }
    practice::audio_payload(root, spec)
}
