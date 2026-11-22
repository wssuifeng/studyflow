use std::env;
use std::path::{Path, PathBuf};

use percent_encoding::percent_decode_str;

use super::StorageError;

#[derive(Debug, Clone)]
pub struct Settings {
    pub workspace: PathBuf,
    pub database: PathBuf,
}

impl Settings {
    pub fn sqlite_url(&self) -> String {
        use percent_encoding::{utf8_percent_encode, NON_ALPHANUMERIC};
        const SQLITE_PATH: &percent_encoding::AsciiSet = &NON_ALPHANUMERIC
            .remove(b'/')
            .remove(b'-')
            .remove(b'_')
            .remove(b'.')
            .remove(b'~');
        let portable = self.database.to_string_lossy().replace('\\', "/");
        format!("sqlite:///{}", utf8_percent_encode(&portable, SQLITE_PATH))
    }
    pub fn from_env() -> Result<Self, StorageError> {
        let cwd = env::current_dir()?;
        let root = env::var_os("STUDYFLOW_WORKSPACE")
            .map(PathBuf::from)
            .unwrap_or_else(|| cwd.clone());
        let path = env::var_os("STUDYFLOW_DATABASE_PATH").map(PathBuf::from);
        let url = env::var("STUDYFLOW_DATABASE_URL")
            .map(Some)
            .or_else(|error| match error {
                env::VarError::NotPresent => Ok(None),
                _ => Err(StorageError::caused_by("UNSUPPORTED_DATABASE", error)),
            })?;
        Self::resolve(&cwd, &root, url.as_deref(), path.as_deref())
    }

    pub fn resolve(
        cwd: &Path,
        workspace: &Path,
        database_url: Option<&str>,
        database_path: Option<&Path>,
    ) -> Result<Self, StorageError> {
        let cwd = absolute(cwd)?;
        let workspace = absolute(&cwd.join(expand_home(workspace)?))?;
        let target = match database_url.filter(|value| !value.is_empty()) {
            Some(url) => {
                let encoded_path = url.strip_prefix("sqlite:///").ok_or_else(unsupported)?;
                let decoded = percent_decode_str(encoded_path)
                    .decode_utf8()
                    .map_err(|error| StorageError::caused_by("UNSUPPORTED_DATABASE", error))?;
                if decoded.is_empty()
                    || decoded == ":memory:"
                    || decoded.contains(['?', '#', '\0'])
                    || decoded.contains("://")
                {
                    return Err(unsupported());
                }
                workspace.join(expand_home(Path::new(decoded.as_ref()))?)
            }
            None => database_path
                .filter(|path| !path.as_os_str().is_empty())
                .map(|path| expand_home(path).map(|path| cwd.join(path)))
                .transpose()?
                .unwrap_or_else(|| {
                    let legacy = workspace.join("studyflow.db");
                    if workspace == cwd && legacy.is_file() {
                        legacy
                    } else {
                        workspace.join(".studyflow/studyflow.db")
                    }
                }),
        };
        let database = absolute(&target)?;
        if database == workspace || database.is_dir() {
            return Err(unsupported());
        }
        Ok(Self {
            workspace,
            database,
        })
    }
}

pub(crate) fn expand_home(path: &Path) -> Result<PathBuf, StorageError> {
    let mut parts = path.components();
    match parts.next() {
        Some(std::path::Component::Normal(name)) if name == "~" => {
            let home = env::home_dir()
                .filter(|path| path.is_absolute())
                .ok_or_else(|| StorageError::new("INVALID_WORKSPACE_PATH"))?;
            Ok(home.join(parts.as_path()))
        }
        Some(std::path::Component::Normal(name)) if name.to_string_lossy().starts_with('~') => {
            Err(StorageError::new("INVALID_WORKSPACE_PATH"))
        }
        _ => Ok(path.to_path_buf()),
    }
}

fn unsupported() -> StorageError {
    StorageError::new("UNSUPPORTED_DATABASE")
}

// Resolve existing ancestors even when discovery is aimed at a new workspace.
// Windows paths use the same unprefixed canonical form as Python pathlib.
pub(crate) fn absolute(path: &Path) -> Result<PathBuf, StorageError> {
    if !path.is_absolute() {
        return Err(StorageError::new("INVALID_WORKSPACE_PATH"));
    }
    match dunce::canonicalize(path) {
        Ok(path) => Ok(path),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let parent = path
                .parent()
                .ok_or_else(|| StorageError::caused_by("INVALID_WORKSPACE_PATH", error))?;
            let name = path.file_name().or_else(|| {
                (path.components().next_back() == Some(std::path::Component::ParentDir))
                    .then_some(std::ffi::OsStr::new(".."))
            });
            let mut canonical = absolute(parent)?;
            match name.and_then(|name| name.to_str()) {
                Some("..") => {
                    canonical.pop();
                }
                Some(name) => canonical.push(name),
                None => return Err(StorageError::new("INVALID_WORKSPACE_PATH")),
            }
            Ok(canonical)
        }
        Err(error) => Err(StorageError::caused_by("INVALID_WORKSPACE_PATH", error)),
    }
}

pub fn path_at_cwd(path: &Path) -> Result<PathBuf, StorageError> {
    absolute(&std::env::current_dir()?.join(path))
}
