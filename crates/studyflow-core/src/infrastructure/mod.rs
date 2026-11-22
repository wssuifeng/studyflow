pub mod config;
pub(crate) mod events;
pub mod file_paths;
pub mod fingerprint;
pub mod installation;
pub mod leases;
pub mod sqlite;

use std::{error::Error, fmt, io};

#[derive(Debug)]
pub struct StorageError {
    pub code: &'static str,
    cause: Option<Box<dyn Error + Send + Sync>>,
}

impl StorageError {
    pub const fn new(code: &'static str) -> Self {
        Self { code, cause: None }
    }

    pub fn caused_by(code: &'static str, error: impl Error + Send + Sync + 'static) -> Self {
        Self {
            code,
            cause: Some(Box::new(error)),
        }
    }
}

impl fmt::Display for StorageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code)
    }
}

impl Error for StorageError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        self.cause.as_deref().map(|error| error as &dyn Error)
    }
}

impl From<io::Error> for StorageError {
    fn from(error: io::Error) -> Self {
        let code = if error.kind() == io::ErrorKind::PermissionDenied {
            "DATABASE_READ_ONLY"
        } else {
            "WORKSPACE_IO_ERROR"
        };
        Self::caused_by(code, error)
    }
}

impl From<rusqlite::Error> for StorageError {
    fn from(error: rusqlite::Error) -> Self {
        let code = match error.sqlite_error_code() {
            Some(rusqlite::ErrorCode::ReadOnly) => "DATABASE_READ_ONLY",
            Some(rusqlite::ErrorCode::DatabaseBusy | rusqlite::ErrorCode::DatabaseLocked) => {
                "DATABASE_BUSY"
            }
            _ => "DATABASE_ERROR",
        };
        Self::caused_by(code, error)
    }
}
pub(crate) mod credentials;

pub mod health;
