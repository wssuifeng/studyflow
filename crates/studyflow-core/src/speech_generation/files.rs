use std::{
    fs::{self, OpenOptions},
    io::{self, Read, Write},
    path::{Path, PathBuf},
    thread,
    time::Duration,
};

use serde::{de::DeserializeOwned, Serialize};
use uuid::Uuid;

use crate::infrastructure::{file_paths::workspace_path, leases::Lease, StorageError};

pub(super) fn directory(root: &Path) -> Result<PathBuf, StorageError> {
    workspace_path(root, Path::new(".studyflow/speech"))
}

pub(super) fn path(directory: &Path, filename: &Path) -> Result<PathBuf, StorageError> {
    workspace_path(directory, filename)
}

pub(super) fn lock(directory: &Path, name: &str) -> Result<Lease, StorageError> {
    // Keep the same relative lock location as 1.8.27 while migrating existing profiles.
    Lease::exclusive_file(
        &path(directory, &Path::new(".studyflow").join(name))?,
        "SPEECH_BUSY",
    )
}

pub(super) fn read_json<T: DeserializeOwned>(path: &Path) -> Result<Option<T>, StorageError> {
    let file = match fs::File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let mut bytes = Vec::new();
    file.take(1024 * 1024 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > 1024 * 1024 {
        return Err(StorageError::new("INVALID_SPEECH_STORE"));
    }
    // Keep parse failures free of profile or request contents.
    serde_json::from_slice(&bytes)
        .map(Some)
        .map_err(|_| StorageError::new("INVALID_SPEECH_STORE"))
}

pub(super) fn write_json(path: &Path, data: &impl Serialize) -> Result<(), StorageError> {
    let bytes = serde_json::to_vec(data).map_err(|_| StorageError::new("INVALID_SPEECH_STORE"))?;
    write(path, &bytes)
}

pub(super) fn write(path: &Path, bytes: &[u8]) -> Result<(), StorageError> {
    let parent = path
        .parent()
        .ok_or_else(|| StorageError::new("INVALID_WORKSPACE_PATH"))?;
    fs::create_dir_all(parent)?;
    let temporary = parent.join(format!(".speech-{}.tmp", Uuid::new_v4()));
    let result = (|| -> io::Result<()> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        for attempt in 1..=8 {
            match fs::rename(&temporary, path) {
                Ok(()) => return Ok(()),
                Err(error)
                    if cfg!(windows)
                        && matches!(error.raw_os_error(), Some(5 | 32))
                        && attempt < 8 =>
                {
                    thread::sleep(Duration::from_millis(10 * attempt));
                }
                Err(error) => return Err(error),
            }
        }
        unreachable!()
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result.map_err(StorageError::from)
}
