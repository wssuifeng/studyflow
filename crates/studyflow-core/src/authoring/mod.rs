//! Explicit author-material operations. This module never opens the learner database.

mod governance;
mod selections;
mod vocabulary;

use crate::infrastructure::{file_paths, fingerprint::JsonFingerprint};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{self, Read},
    path::{Component, Path, PathBuf},
};

pub use vocabulary::Query;

#[derive(Debug)]
pub struct Error {
    pub code: &'static str,
    pub message: String,
}

type Result<T> = std::result::Result<T, Error>;
type Sources = Vec<(String, String)>;

fn error(code: &'static str, message: &str) -> Error {
    Error {
        code,
        message: format!("{code}: {message}"),
    }
}

impl From<io::Error> for Error {
    fn from(value: io::Error) -> Self {
        let code = match value.kind() {
            io::ErrorKind::NotFound => "FileNotFoundError",
            io::ErrorKind::AlreadyExists => "FileExistsError",
            io::ErrorKind::PermissionDenied => "PermissionError",
            _ => "OSError",
        };
        Self {
            code,
            message: value.to_string(),
        }
    }
}

pub struct MaterialRoot(PathBuf);

impl MaterialRoot {
    pub fn open(root: &Path) -> Result<Self> {
        if !root.is_dir() {
            return Err(error(
                "ROOT_REQUIRED",
                "existing author-material root required",
            ));
        }
        let absolute = std::env::current_dir()?.join(root);
        for path in absolute.ancestors() {
            check_link(path)?;
        }
        let root = dunce::canonicalize(absolute)?;
        if root.ancestors().any(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.eq_ignore_ascii_case("local.studyflow.desktop"))
                || path.join(".studyflow").exists()
        }) {
            return Err(error(
                "DATA_WORKSPACE",
                "do not run author helpers on an application data root",
            ));
        }
        Ok(Self(root))
    }

    pub fn query(&self, input: &Query) -> Result<Value> {
        vocabulary::query(self, input)
    }
    pub fn select(&self, recipe: &str, output: &str) -> Result<Value> {
        selections::create(self, recipe, output)
    }
    pub fn coverage(&self, sources: &Sources, selections: &str) -> Result<Value> {
        selections::coverage(self, sources, selections)
    }
    pub fn link(
        &self,
        selection: &str,
        receipt: &str,
        course: &str,
        revision: i64,
    ) -> Result<Value> {
        selections::link(self, selection, receipt, course, revision)
    }
    pub fn audit(&self, config: &str) -> Result<Value> {
        governance::audit(self, config)
    }

    fn path(&self, requested: impl AsRef<Path>) -> Result<PathBuf> {
        let requested = requested.as_ref();
        let relative = if requested.is_absolute() {
            file_paths::relative_in_workspace(requested, &self.0).map_err(|_| {
                error(
                    "PATH_BOUNDARY",
                    "path must stay inside the explicit author root",
                )
            })?
        } else {
            requested.to_owned()
        };
        let mut path = self.0.clone();
        for part in relative.components() {
            match part {
                Component::CurDir => (),
                Component::ParentDir if path != self.0 => {
                    path.pop();
                }
                Component::Normal(name)
                    if name
                        .to_str()
                        .is_some_and(|name| file_paths::portable_relative(name).is_ok()) =>
                {
                    path.push(name);
                    check_link(&path)?;
                }
                _ => {
                    return Err(error(
                        "PATH_BOUNDARY",
                        "path must stay inside the explicit author root",
                    ))
                }
            }
        }
        Ok(path)
    }

    fn relative(&self, path: &Path) -> String {
        path.strip_prefix(&self.0)
            .expect("resolved author path")
            .to_string_lossy()
            .replace('\\', "/")
    }

    fn json(&self, requested: impl AsRef<Path>) -> Result<Value> {
        let bytes = bounded_read(&self.path(requested)?, 262144, "split the selected input")?;
        let json: Value = serde_json::from_slice(without_bom(&bytes))
            .map_err(|_| error("FORMAT", "expected valid UTF-8 JSON"))?;
        if !json.is_object() {
            return Err(error("FORMAT", "expected a JSON object"));
        }
        Ok(json)
    }
}

fn check_link(path: &Path) -> Result<()> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if file_paths::is_link(&metadata) => Err(error(
            "LINKED_PATH",
            "linked author resources are not accepted",
        )),
        Ok(_) => Ok(()),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e.into()),
    }
}

fn bounded_read(path: &Path, limit: u64, message: &str) -> Result<Vec<u8>> {
    let file = fs::File::open(path)?;
    if !file.metadata()?.is_file() {
        return Err(error("FORMAT", "expected a regular author resource"));
    }
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(error("INPUT_BUDGET", message));
    }
    Ok(bytes)
}

fn without_bom(bytes: &[u8]) -> &[u8] {
    bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(bytes)
}

fn utf8(bytes: &[u8]) -> Result<&str> {
    std::str::from_utf8(without_bom(bytes)).map_err(|_| error("FORMAT", "expected valid UTF-8"))
}

fn digest(value: &Value) -> String {
    JsonFingerprint::CompactUtf8.hash(value)
}
fn sha(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn text<'a>(object: &'a Value, field: &str) -> Result<&'a str> {
    object[field]
        .as_str()
        .ok_or_else(|| error("FORMAT", "expected a string field"))
}

fn nonblank(value: &Value) -> bool {
    value.as_str().is_some_and(|text| !text.trim().is_empty())
}
