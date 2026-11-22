use rusqlite::{params, Connection};
use uuid::Uuid;

use super::StorageError;

pub(crate) fn record(
    db: &Connection,
    source: &str,
    object: &str,
    object_id: &str,
    action: &str,
    summary: &str,
) -> Result<(), StorageError> {
    db.execute(
        "INSERT INTO event_logs(id,source,object_type,object_id,action,summary) VALUES(?,?,?,?,?,?)",
        params![Uuid::new_v4().to_string(), source, object, object_id, action, summary],
    )?;
    Ok(())
}
