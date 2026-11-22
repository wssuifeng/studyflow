use std::path::Path;
use std::time::Duration;

use rusqlite::{Connection, OpenFlags};

use super::StorageError;

mod migration;
mod schema;

pub(crate) use migration::{archive_revision, copy_database, is_known_revision, upgrade};
pub use migration::{MigrationReceipt, CURRENT_REVISION};

pub fn read_existing(path: &Path) -> Result<Connection, StorageError> {
    if !path.is_file() {
        return Err(StorageError::new("WORKSPACE_NOT_INITIALIZED"));
    }
    let connection = connect(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    connection.pragma_update(None, "query_only", true)?;
    migration::validate_read_schema(&connection, "SCHEMA_UPGRADE_REQUIRED")?;
    Ok(connection)
}

pub(crate) fn check_current_read_only(path: &Path) -> Result<(), StorageError> {
    if !path.is_file() {
        return Err(StorageError::new("WORKSPACE_NOT_INITIALIZED"));
    }
    let connection = connect(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    migration::validate_current(&connection, "SCHEMA_UPGRADE_REQUIRED")
}

pub fn write_existing(path: &Path) -> Result<Connection, StorageError> {
    if !path.is_file() {
        return Err(StorageError::new("WORKSPACE_NOT_INITIALIZED"));
    }
    let connection = connect(path, OpenFlags::SQLITE_OPEN_READ_WRITE)?;
    migration::validate_current(&connection, "SCHEMA_UPGRADE_REQUIRED")?;
    Ok(connection)
}

pub(crate) fn connect(path: &Path, mode: OpenFlags) -> Result<Connection, StorageError> {
    let connection = Connection::open_with_flags(path, mode | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
    connection.busy_timeout(Duration::from_secs(5))?;
    connection.execute_batch("PRAGMA temp_store=MEMORY; PRAGMA foreign_keys=ON;")?;
    Ok(connection)
}
