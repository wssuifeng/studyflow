mod markdown;

use std::fs::{File, Metadata};
use std::io::Read;
use std::path::{Path, PathBuf};

use serde::Serialize;
use sha2::{Digest, Sha256};
use time::{macros::format_description, OffsetDateTime, UtcOffset};

use crate::infrastructure::{file_paths, StorageError};

pub use markdown::{parse_front_matter, render, validate_import_metadata};

const MAX_DOCUMENT_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Serialize)]
pub struct DocumentRead {
    pub path: String,
    pub status: &'static str,
    pub markdown: String,
    pub html: String,
    pub file_size: u64,
    pub modified_at: Option<String>,
    pub content_hash: String,
}

#[derive(Serialize)]
pub struct DocumentCheck {
    pub id: String,
    pub path: String,
    pub status: &'static str,
    pub size: u64,
}

pub fn markdown_import_path(
    root: &Path,
    request: &Path,
) -> Result<(PathBuf, String), StorageError> {
    let path = file_paths::workspace_path(root, request)?;
    if !path.is_file() {
        return Err(StorageError::new("DOCUMENT_NOT_FOUND"));
    }
    require_markdown(&path)?;
    let root = file_paths::workspace_path(root, Path::new("."))?;
    let relative = file_paths::relative_in_workspace(&path, &root)?;
    Ok((path.to_owned(), portable_path(&relative)?))
}

pub fn read(root: &Path, relative: &str, with_html: bool) -> Result<DocumentRead, StorageError> {
    if relative.trim().is_empty() {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let relative = Path::new(relative);
    if relative.components().any(|part| {
        !matches!(
            part,
            std::path::Component::Normal(_) | std::path::Component::CurDir
        )
    }) {
        return Err(StorageError::new("PATH_OUTSIDE_WORKSPACE"));
    }
    require_markdown(relative)?;
    let relative: PathBuf = relative
        .components()
        .filter_map(|part| match part {
            std::path::Component::Normal(value) => Some(value),
            _ => None,
        })
        .collect();
    let portable = portable_path(&relative)?;
    file_paths::portable_relative(&portable)
        .map_err(|_| StorageError::new("PATH_OUTSIDE_WORKSPACE"))?;
    let path = file_paths::workspace_path(root, &relative)?;
    let raw = File::open(&path).map_err(|error| {
        let code = if error.kind() == std::io::ErrorKind::NotFound {
            "DOCUMENT_NOT_FOUND"
        } else {
            "DOCUMENT_UNREADABLE"
        };
        StorageError::caused_by(code, error)
    })?;
    let metadata = raw.metadata()?;
    if !metadata.is_file() {
        return Err(StorageError::new("DOCUMENT_UNREADABLE"));
    }
    let markdown = read_text(raw)?;
    let content_hash = format!("{:x}", Sha256::digest(markdown.as_bytes()));
    let html = if with_html {
        render(&markdown, true)?
    } else {
        String::new()
    };
    let markdown = match parse_front_matter(&markdown) {
        Ok((metadata, body))
            if matches!(
                metadata["content_schema"].as_str(),
                Some("studyflow.course-package/7" | "studyflow.course-package/8")
            ) =>
        {
            body.to_owned()
        }
        _ => markdown,
    };
    Ok(DocumentRead {
        path: portable,
        status: "PRESENT",
        markdown,
        html,
        file_size: metadata.len(),
        modified_at: modified(&metadata),
        content_hash,
    })
}

pub fn read_text(file: File) -> Result<String, StorageError> {
    let mut data = Vec::new();
    file.take(MAX_DOCUMENT_BYTES + 1)
        .read_to_end(&mut data)
        .map_err(|error| StorageError::caused_by("DOCUMENT_UNREADABLE", error))?;
    if data.len() as u64 > MAX_DOCUMENT_BYTES {
        return Err(StorageError::new("DOCUMENT_TOO_LARGE"));
    }
    let body = String::from_utf8(data)
        .map_err(|error| StorageError::caused_by("DOCUMENT_UNREADABLE", error))?;
    Ok(body.replace("\r\n", "\n").replace('\r', "\n"))
}

pub fn check(
    root: &Path,
    db: &rusqlite::Connection,
    relative: &str,
) -> Result<DocumentCheck, StorageError> {
    register(root, db, relative, None)
}

pub(crate) fn register(
    root: &Path,
    db: &rusqlite::Connection,
    relative: &str,
    document_type: Option<&str>,
) -> Result<DocumentCheck, StorageError> {
    let path = file_paths::workspace_path(root, Path::new(relative))?;
    let (status, size, modified, digest) = match File::open(&path) {
        Ok(file) => {
            let metadata = file.metadata()?;
            match read_text(file) {
                Ok(text) if metadata.is_file() => (
                    "PRESENT",
                    metadata.len(),
                    modified(&metadata),
                    format!("{:x}", Sha256::digest(text.as_bytes())),
                ),
                _ => ("UNREADABLE", 0, None, String::new()),
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            ("MISSING", 0, None, String::new())
        }
        Err(_) => ("UNREADABLE", 0, None, String::new()),
    };
    let id = uuid::Uuid::new_v4().to_string();
    let id = db.query_row(
        "INSERT INTO documents(id, relative_path, document_type, status, file_size, modified_at, content_hash, summary)
         VALUES(?1, ?2, COALESCE(?3,'MARKDOWN'), ?4, ?5, ?6, ?7, '')
         ON CONFLICT(relative_path) DO UPDATE SET document_type=COALESCE(?3,documents.document_type), status=excluded.status, file_size=excluded.file_size,
           modified_at=excluded.modified_at, content_hash=excluded.content_hash, updated_at=CURRENT_TIMESTAMP
         RETURNING id",
        rusqlite::params![id, relative, document_type, status, size as i64, modified, digest],
        |row| row.get(0),
    )?;
    Ok(DocumentCheck {
        id,
        path: relative.to_owned(),
        status,
        size,
    })
}

fn require_markdown(path: &Path) -> Result<(), StorageError> {
    if path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|ext| ext.eq_ignore_ascii_case("md") || ext.eq_ignore_ascii_case("markdown"))
    {
        return Ok(());
    }
    Err(StorageError::new("UNSUPPORTED_DOCUMENT_TYPE"))
}

fn portable_path(path: &Path) -> Result<String, StorageError> {
    path.to_str()
        .map(|raw| raw.replace('\\', "/"))
        .ok_or_else(|| StorageError::new("PATH_OUTSIDE_WORKSPACE"))
}

fn modified(metadata: &Metadata) -> Option<String> {
    let utc = OffsetDateTime::from(metadata.modified().ok()?);
    let time = utc.to_offset(UtcOffset::local_offset_at(utc).unwrap_or(UtcOffset::UTC));
    let mut value = time
        .format(format_description!(
            "[year]-[month]-[day] [hour]:[minute]:[second]"
        ))
        .ok()?;
    if time.microsecond() != 0 {
        use std::fmt::Write;
        write!(value, ".{:06}", time.microsecond()).ok()?;
    }
    Some(value)
}
