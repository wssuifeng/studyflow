use rusqlite::{Connection, TransactionBehavior};
use serde_json::Value;

use crate::infrastructure::StorageError;

/// Keep receipt lookup, version checks, domain writes, and receipt recording on
/// one connection. BEGIN IMMEDIATE serializes racing writers before lookup.
pub fn atomic_write<T>(
    connection: &mut Connection,
    action: impl FnOnce(&Connection) -> Result<T, StorageError>,
) -> Result<T, StorageError> {
    let tx = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let result = action(&tx)?;
    tx.commit()?;
    Ok(result)
}

pub fn validate_key(key: &str) -> Result<(), StorageError> {
    // Match Python's definition of whitespace when validating stored keys.
    if key.chars().count() > 160
        || key
            .chars()
            .all(|ch| ch.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&ch))
    {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    Ok(())
}

pub fn require_version(current: i64, expected: i64) -> Result<(), StorageError> {
    if current != expected {
        return Err(StorageError::new("VERSION_CONFLICT"));
    }
    Ok(())
}

pub struct StoredReceipt {
    pub operation: Option<String>,
    pub payload_hash: Option<String>,
    pub result_json: Option<String>,
}

impl StoredReceipt {
    pub fn replay(
        &self,
        operation: Option<&str>,
        payload_hash: &str,
    ) -> Result<Value, StorageError> {
        let hash = self
            .payload_hash
            .as_deref()
            .filter(|hash| !hash.is_empty())
            .ok_or_else(|| StorageError::new("IDEMPOTENCY_UNVERIFIABLE"))?;
        let result = self
            .result_json
            .as_deref()
            .filter(|result| !result.is_empty())
            .ok_or_else(|| StorageError::new("IDEMPOTENCY_UNVERIFIABLE"))?;
        if hash != payload_hash || operation.is_some_and(|op| self.operation.as_deref() != Some(op))
        {
            return Err(StorageError::new("IDEMPOTENCY_KEY_CONFLICT"));
        }
        serde_json::from_str(result)
            .map_err(|error| StorageError::caused_by("IDEMPOTENCY_UNVERIFIABLE", error))
    }
}

pub(crate) fn replay_course(
    db: &Connection,
    key: &str,
    operation: &str,
    hash: &str,
) -> Result<Option<Value>, StorageError> {
    use rusqlite::OptionalExtension;
    let stored=db.query_row("SELECT operation,payload_hash,result_json FROM course_write_receipts WHERE idempotency_key=?",[key],|row|Ok(StoredReceipt{operation:row.get(0)?,payload_hash:row.get(1)?,result_json:row.get(2)?})).optional()?;
    stored
        .map(|stored| stored.replay(Some(operation), hash))
        .transpose()
}

pub(crate) fn record_course(
    db: &Connection,
    course: &str,
    key: &str,
    operation: &str,
    hash: &str,
    result: &Value,
) -> Result<(), StorageError> {
    db.execute("INSERT INTO course_write_receipts(id,course_id,idempotency_key,operation,payload_hash,result_json) VALUES(?,?,?,?,?,?)",rusqlite::params![uuid::Uuid::new_v4().to_string(),course,key,operation,hash,result.to_string()])?;
    Ok(())
}
