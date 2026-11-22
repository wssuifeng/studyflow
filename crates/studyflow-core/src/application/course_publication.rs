use std::path::Path;

use serde_json::Value;

use crate::{
    application::write_contract::atomic_write,
    audio::assets,
    courses::{
        packages,
        publication::{self, MarkdownSource},
    },
    infrastructure::StorageError,
    planning::Track,
    workspace::Workspace,
};

pub fn import_package(workspace: &Workspace, package: &Value) -> Result<Value, StorageError> {
    let root = &workspace.settings().workspace;
    let summary = validated_summary(root, package)?;
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        publication::import_package(db, root, package, summary, Track::Main)
    })
}

pub fn import_markdown(workspace: &Workspace, path: &Path) -> Result<Value, StorageError> {
    let root = &workspace.settings().workspace;
    let source = MarkdownSource::read(root, path)?;
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        publication::import_markdown(db, root, &source)
    })
}

pub fn preview_update(
    workspace: &Workspace,
    id: &str,
    package: &Value,
    expected: i64,
) -> Result<Value, StorageError> {
    let root = &workspace.settings().workspace;
    let summary = validated_summary(root, package)?;
    let connection = workspace.inspect()?;
    let db = connection.unchecked_transaction()?;
    crate::courses::revisions::Change {
        id,
        package,
        content_hash: summary["content_hash"].as_str().unwrap(),
        expected,
    }
    .preview(&db, root)
}

pub fn apply_update(
    workspace: &Workspace,
    id: &str,
    package: &Value,
    expected: i64,
    preview: &str,
    key: &str,
) -> Result<Value, StorageError> {
    let root = &workspace.settings().workspace;
    let summary = validated_summary(root, package)?;
    let mut active = workspace.open()?;
    let change = crate::courses::revisions::Change {
        id,
        package,
        content_hash: summary["content_hash"].as_str().unwrap(),
        expected,
    };
    atomic_write(&mut active.connection, |db| {
        change.apply(db, root, preview, key)
    })
}

fn validated_summary(root: &Path, package: &Value) -> Result<Value, StorageError> {
    let summary = packages::inspect(package)
        .map_err(|error| StorageError::caused_by("INVALID_COURSE_PACKAGE", error))?;
    assets::validate_package_assets(root, package)?;
    Ok(summary)
}
