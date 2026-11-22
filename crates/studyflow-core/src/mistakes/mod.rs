mod commands;
pub mod remediation;
pub use commands::{archive_apply, archive_preview, request_retest, select_review};
mod query;
pub use query::{context, list, notebooks, summary};
mod projection;

use rusqlite::{params, Connection, OptionalExtension};
use uuid::Uuid;

use crate::infrastructure::StorageError;

pub(crate) use projection::record_review;

pub(crate) fn notebook(
    db: &Connection,
    plan: Option<&str>,
    domain: &str,
    create: bool,
) -> Result<Option<String>, StorageError> {
    if !matches!(domain, "general" | "english") {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let scope = plan
        .filter(|id| !id.is_empty())
        .map_or_else(|| "unassigned".to_owned(), |id| format!("plan:{id}"));
    if create {
        db.execute("INSERT INTO mistake_notebooks(id,scope_key,plan_line_id,domain) VALUES(?,?,?,?) ON CONFLICT(scope_key,domain) DO NOTHING",params![Uuid::new_v4().to_string(),scope,plan,domain])?;
    }
    Ok(db
        .query_row(
            "SELECT id FROM mistake_notebooks WHERE scope_key=? AND domain=?",
            params![scope, domain],
            |row| row.get(0),
        )
        .optional()?)
}
