pub mod archive;
pub mod snapshot;

use rusqlite::Connection;

use crate::infrastructure::{config::Settings, leases::Lease, sqlite, StorageError};

pub struct Workspace {
    settings: Settings,
}

pub struct ActiveWorkspace {
    pub connection: Connection,
    _lease: Lease,
}

impl Workspace {
    pub fn new(settings: Settings) -> Self {
        Self { settings }
    }

    pub fn settings(&self) -> &Settings {
        &self.settings
    }

    pub fn read_consistent<T>(
        &self,
        read: impl FnOnce(&Connection) -> Result<T, StorageError>,
    ) -> Result<T, StorageError> {
        let connection = self.inspect()?;
        let tx = connection.unchecked_transaction()?;
        read(&tx)
    }

    pub fn inspect(&self) -> Result<Connection, StorageError> {
        sqlite::read_existing(&self.settings.database)
    }

    pub fn open(&self) -> Result<ActiveWorkspace, StorageError> {
        let lease = Lease::shared(&self.settings.workspace)?;
        let connection = sqlite::write_existing(&self.settings.database)?;
        Ok(ActiveWorkspace {
            connection,
            _lease: lease,
        })
    }

    pub fn ensure_ready(&self) -> Result<(), StorageError> {
        match sqlite::check_current_read_only(&self.settings.database) {
            Ok(()) => Ok(()),
            Err(error)
                if matches!(
                    error.code,
                    "WORKSPACE_NOT_INITIALIZED" | "SCHEMA_UPGRADE_REQUIRED"
                ) =>
            {
                self.upgrade()?;
                Ok(())
            }
            Err(error) => Err(error),
        }
    }

    pub fn upgrade(&self) -> Result<sqlite::MigrationReceipt, StorageError> {
        let _lease = Lease::exclusive(&self.settings.workspace)?;
        sqlite::upgrade(&self.settings.database)
    }
}
