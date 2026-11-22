use std::collections::{BTreeSet, HashSet};
use std::fs::{self, File};
use std::io::{self, BufReader, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use rusqlite::OpenFlags;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};
use uuid::Uuid;
use zip::{result::ZipError, write::SimpleFileOptions, CompressionMethod, ZipArchive, ZipWriter};

use crate::infrastructure::{
    config::{absolute, path_at_cwd, Settings},
    file_paths::{available_bytes, is_link, is_sha256, portable_relative},
    leases::Lease,
    sqlite, StorageError,
};

const MANIFEST: &str = "manifest.json";
const ARCHIVED_DB: &str = "database/studyflow.db";
const WORKSPACE_DB: &str = ".studyflow/studyflow.db";
const MANIFEST_LIMIT: u64 = 2 * 1024 * 1024;

#[derive(Debug, Serialize, Deserialize)]
pub struct ArchiveMember {
    pub archive_path: String,
    pub size: u64,
    pub sha256: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ArchiveFile {
    pub relative_path: String,
    #[serde(flatten)]
    pub member: ArchiveMember,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Manifest {
    pub format: String,
    pub format_version: String,
    pub generated_at: String,
    pub schema_revision: String,
    pub workspace_name: String,
    pub database: ArchiveMember,
    pub files: Vec<ArchiveFile>,
}

#[derive(Debug, Serialize)]
pub struct ExportReceipt {
    pub ok: bool,
    pub archive_path: PathBuf,
    pub format_version: String,
    pub schema_revision: String,
    pub file_count: usize,
    pub database_size: u64,
    pub manifest: Manifest,
}

#[derive(Debug, Serialize)]
pub struct ValidationReceipt {
    pub ok: bool,
    pub valid: bool,
    pub schema_revision: String,
    pub file_count: usize,
    pub required_bytes: u64,
}

#[derive(Debug, Serialize)]
pub struct RestoreReceipt {
    pub ok: bool,
    pub workspace_root: PathBuf,
    pub schema_revision: String,
    pub file_count: usize,
    pub replaced_existing: bool,
    pub previous_workspace: Option<PathBuf>,
    pub manifest: Manifest,
}

pub fn export(settings: &Settings, destination: &Path) -> Result<ExportReceipt, StorageError> {
    if !settings.database.is_file() {
        return Err(StorageError::new("DATABASE_NOT_FOUND"));
    }
    // Hold the normal activity lease so maintenance cannot replace files
    // while the database snapshot and archive members are being collected.
    let _lease = Lease::shared(&settings.workspace)?;
    let mut path = path_at_cwd(destination)?;
    if !path
        .extension()
        .and_then(|v| v.to_str())
        .is_some_and(|ext| ext.eq_ignore_ascii_case("zip") || ext.eq_ignore_ascii_case("studyflow"))
    {
        path.set_extension("studyflow.zip");
    }
    if path == settings.database {
        return Err(StorageError::new("BACKUP_PATH_INVALID"));
    }
    let parent = path
        .parent()
        .ok_or_else(|| StorageError::new("BACKUP_PATH_INVALID"))?;
    fs::create_dir_all(parent)?;
    let staging = Staging::new(parent, "export")?;
    let snapshot = staging.0.join("snapshot.db");
    let source = sqlite::connect(&settings.database, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    sqlite::copy_database(&source, &snapshot)?;
    let db = sqlite::connect(&snapshot, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let revision = sqlite::archive_revision(&db)?;
    let paths = document_paths(&settings.workspace, &db)?;
    let staged_zip = staging.0.join("archive.zip");
    let mut zip = ZipWriter::new(File::create_new(&staged_zip)?);
    let database = add_file(&mut zip, ARCHIVED_DB.to_owned(), &snapshot)?;
    let files = paths
        .into_iter()
        .map(|relative_path| {
            let source = checked_workspace_file(&settings.workspace, &relative_path)?;
            let member = add_file(&mut zip, format!("files/{relative_path}"), &source)?;
            Ok(ArchiveFile {
                relative_path,
                member,
            })
        })
        .collect::<Result<Vec<_>, StorageError>>()?;
    let manifest = Manifest {
        format: "studyflow-workspace".into(),
        format_version: "1".into(),
        generated_at: OffsetDateTime::now_utc()
            .format(&Rfc3339)
            .map_err(manifest_invalid)?,
        schema_revision: revision,
        workspace_name: settings
            .workspace
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or_default()
            .to_owned(),
        database,
        files,
    };
    validate_manifest(&manifest)?;
    let encoded = serde_json::to_vec_pretty(&manifest).map_err(manifest_invalid)?;
    if encoded.len() as u64 > MANIFEST_LIMIT {
        return Err(StorageError::new("BACKUP_MANIFEST_INVALID"));
    }
    zip.start_file(MANIFEST, zip_options(encoded.len() as u64))
        .map_err(archive_error)?;
    zip.write_all(&encoded)?;
    zip.finish().map_err(archive_error)?.sync_all()?;
    fs::rename(&staged_zip, &path)?;
    Ok(ExportReceipt {
        ok: true,
        archive_path: path,
        format_version: manifest.format_version.clone(),
        schema_revision: manifest.schema_revision.clone(),
        file_count: manifest.files.len(),
        database_size: manifest.database.size,
        manifest,
    })
}

pub fn validate(path: &Path) -> Result<ValidationReceipt, StorageError> {
    let mut backup = OpenArchive::read(path)?;
    process_members(&mut backup.zip, &backup.manifest, None)?;
    Ok(ValidationReceipt {
        ok: true,
        valid: true,
        schema_revision: backup.manifest.schema_revision,
        file_count: backup.manifest.files.len(),
        required_bytes: backup.required_bytes,
    })
}

pub fn restore(path: &Path, target: &Path) -> Result<RestoreReceipt, StorageError> {
    restore_with_space_check(path, target, available_bytes)
}

fn restore_with_space_check(
    path: &Path,
    target: &Path,
    space: impl FnOnce(&Path) -> io::Result<u64>,
) -> Result<RestoreReceipt, StorageError> {
    if fs::symlink_metadata(target).is_ok_and(|metadata| is_link(&metadata)) {
        return Err(StorageError::new("BACKUP_PATH_INVALID"));
    }
    let mut backup = OpenArchive::read(path)?;
    let target = path_at_cwd(target)?;
    let parent = target
        .parent()
        .ok_or_else(|| StorageError::new("BACKUP_PATH_INVALID"))?;
    fs::create_dir_all(parent)?;
    let threshold = backup
        .required_bytes
        .saturating_mul(2)
        .saturating_add(10 * 1024 * 1024);
    if space(parent)? < threshold {
        return Err(StorageError::new("WORKSPACE_DISK_FULL"));
    }
    let _lease = Lease::exclusive(&target)?;
    let staging = Staging::new(parent, "restore")?;
    process_members(&mut backup.zip, &backup.manifest, Some(&staging.0))?;
    drop(backup.zip);
    let restored_db = sqlite::connect(
        &staging.0.join(WORKSPACE_DB),
        OpenFlags::SQLITE_OPEN_READ_ONLY,
    )?;
    restored_db.execute_batch("PRAGMA trusted_schema=OFF")?;
    if sqlite::archive_revision(&restored_db)? != backup.manifest.schema_revision {
        return Err(StorageError::new("BACKUP_SCHEMA_MISMATCH"));
    }
    let integrity: String = restored_db.query_row("PRAGMA quick_check(1)", [], |row| row.get(0))?;
    if integrity != "ok" {
        return Err(StorageError::new("DATABASE_UNREADABLE"));
    }
    drop(restored_db);
    let previous = replace_directory(&staging.0, &target)?;
    Ok(RestoreReceipt {
        ok: true,
        workspace_root: target,
        schema_revision: backup.manifest.schema_revision.clone(),
        file_count: backup.manifest.files.len(),
        replaced_existing: previous.is_some(),
        previous_workspace: previous,
        manifest: backup.manifest,
    })
}

struct OpenArchive {
    zip: ZipArchive<File>,
    manifest: Manifest,
    required_bytes: u64,
}

impl OpenArchive {
    fn read(path: &Path) -> Result<Self, StorageError> {
        let file =
            File::open(path).map_err(|error| StorageError::caused_by("BACKUP_NOT_FOUND", error))?;
        let mut central = file.try_clone()?;
        let mut zip = ZipArchive::new(file).map_err(archive_error)?;
        let manifest: Manifest = {
            let entry = zip.by_name(MANIFEST).map_err(manifest_invalid)?;
            if entry.size() > MANIFEST_LIMIT {
                return Err(StorageError::new("BACKUP_MANIFEST_INVALID"));
            }
            serde_json::from_reader(BufReader::new(entry.take(MANIFEST_LIMIT + 1)))
                .map_err(manifest_invalid)?
        };
        let required_bytes = validate_manifest(&manifest)?;
        check_members(&mut zip, &mut central, &manifest)?;
        Ok(Self {
            zip,
            manifest,
            required_bytes,
        })
    }
}

fn validate_manifest(manifest: &Manifest) -> Result<u64, StorageError> {
    if manifest.format != "studyflow-workspace" || manifest.format_version != "1" {
        return Err(StorageError::new("BACKUP_FORMAT_UNSUPPORTED"));
    }
    if !sqlite::is_known_revision(&manifest.schema_revision) {
        return Err(StorageError::new("UNKNOWN_SCHEMA"));
    }
    if manifest.database.archive_path != ARCHIVED_DB || !is_sha256(&manifest.database.sha256) {
        return Err(StorageError::new("BACKUP_MANIFEST_INVALID"));
    }
    let mut paths = HashSet::new();
    let mut total = manifest.database.size;
    for file in &manifest.files {
        portable_relative(&file.relative_path)?;
        if file.member.archive_path != format!("files/{}", file.relative_path)
            || !is_sha256(&file.member.sha256)
            || !paths.insert(file.relative_path.to_lowercase())
            || !allowed_content(&file.relative_path)
        {
            return Err(StorageError::new("BACKUP_MANIFEST_INVALID"));
        }
        total = total
            .checked_add(file.member.size)
            .ok_or_else(|| StorageError::new("BACKUP_MANIFEST_INVALID"))?;
    }
    Ok(total)
}

fn check_members(
    zip: &mut ZipArchive<File>,
    central: &mut File,
    manifest: &Manifest,
) -> Result<(), StorageError> {
    let mut expected: HashSet<&str> = manifest
        .files
        .iter()
        .map(|item| item.member.archive_path.as_str())
        .collect();
    expected.extend([MANIFEST, ARCHIVED_DB]);
    let mut offset = zip.central_directory_start();
    for index in 0..zip.len() {
        let entry = zip.by_index_raw(index).map_err(archive_error)?;
        // zip's name map keeps the last member when a central name is repeated.
        // Require the mapped entries to cover the physical central directory.
        if entry.central_header_start() != offset {
            return Err(StorageError::new("BACKUP_ARCHIVE_UNEXPECTED_FILE"));
        }
        central.seek(SeekFrom::Start(offset))?;
        let mut header = [0u8; 46];
        central.read_exact(&mut header)?;
        for field in [28, 30, 32] {
            offset += u64::from(u16::from_le_bytes([header[field], header[field + 1]]));
        }
        offset += header.len() as u64;
        if entry.is_symlink() {
            return Err(StorageError::new("BACKUP_SYMLINK_UNSUPPORTED"));
        }
        portable_relative(entry.name().trim_end_matches('/'))?;
        if !entry.is_dir() && !expected.remove(entry.name()) {
            return Err(StorageError::new("BACKUP_ARCHIVE_UNEXPECTED_FILE"));
        }
    }
    central.seek(SeekFrom::Start(offset))?;
    let mut tag = [0; 4];
    central.read_exact(&mut tag)?;
    if tag == *b"PK\x01\x02" {
        return Err(StorageError::new("BACKUP_ARCHIVE_UNEXPECTED_FILE"));
    }
    if expected.contains(ARCHIVED_DB) {
        return Err(StorageError::new("BACKUP_DATABASE_MISSING"));
    }
    if !expected.is_empty() {
        return Err(StorageError::new("BACKUP_FILE_MISSING"));
    }
    Ok(())
}

fn process_members(
    zip: &mut ZipArchive<File>,
    manifest: &Manifest,
    target: Option<&Path>,
) -> Result<(), StorageError> {
    let entries = std::iter::once((WORKSPACE_DB, &manifest.database)).chain(
        manifest
            .files
            .iter()
            .map(|file| (file.relative_path.as_str(), &file.member)),
    );
    for (relative, meta) in entries {
        let entry = zip.by_name(&meta.archive_path).map_err(archive_error)?;
        if entry.size() != meta.size {
            return Err(StorageError::new("BACKUP_HASH_MISMATCH"));
        }
        let mut input = entry.take(meta.size.saturating_add(1));
        let result = if let Some(target) = target {
            let destination = target.join(relative);
            fs::create_dir_all(destination.parent().expect("validated relative path"))?;
            let mut file = File::create_new(destination)?;
            let result = copy_hash(&mut input, &mut file)?;
            file.sync_all()?;
            result
        } else {
            copy_hash(&mut input, &mut io::sink())?
        };
        if result != (meta.size, meta.sha256.clone()) {
            return Err(StorageError::new("BACKUP_HASH_MISMATCH"));
        }
    }
    Ok(())
}

fn document_paths(
    root: &Path,
    db: &rusqlite::Connection,
) -> Result<BTreeSet<String>, StorageError> {
    let mut stmt = db.prepare("SELECT relative_path FROM documents ORDER BY relative_path")?;
    let mut paths = stmt
        .query_map([], |row| row.get::<_, String>(0))?
        .collect::<Result<BTreeSet<_>, _>>()?;
    for path in &paths {
        portable_relative(path)?;
        if !allowed_content(path) {
            return Err(StorageError::new("BACKUP_PATH_INVALID"));
        }
    }
    let mut pending = vec![root.join("content")];
    while let Some(directory) = pending.pop() {
        let listing = match fs::read_dir(&directory) {
            Ok(entries) => entries,
            Err(error)
                if error.kind() == io::ErrorKind::NotFound && directory == root.join("content") =>
            {
                continue
            }
            Err(error) => return Err(error.into()),
        };
        if is_link(&fs::symlink_metadata(&directory)?) {
            return Err(StorageError::new("WORKSPACE_SYMLINK_UNSUPPORTED"));
        }
        for entry in listing {
            let entry = entry?;
            let path = entry.path();
            let metadata = fs::symlink_metadata(&path)?;
            if is_link(&metadata) {
                return Err(StorageError::new("WORKSPACE_SYMLINK_UNSUPPORTED"));
            }
            if metadata.is_dir() {
                pending.push(path);
            } else if metadata.is_file() {
                let relative = path
                    .strip_prefix(root)
                    .expect("walk inside workspace")
                    .to_str()
                    .ok_or_else(|| StorageError::new("BACKUP_PATH_INVALID"))?
                    .replace('\\', "/");
                if allowed_content(&relative) {
                    portable_relative(&relative)?;
                    paths.insert(relative);
                }
            }
        }
    }
    Ok(paths)
}

fn allowed_content(relative: &str) -> bool {
    if relative
        .split('/')
        .next()
        .is_some_and(|part| part.eq_ignore_ascii_case(".studyflow"))
    {
        return false;
    }
    let Some((stem, ext)) = relative.rsplit_once('.') else {
        return false;
    };
    if ext.eq_ignore_ascii_case("md") || ext.eq_ignore_ascii_case("markdown") {
        return true;
    }
    matches!(ext, "wav" | "mp3")
        && stem
            .strip_prefix("content/audio-assets/")
            .is_some_and(is_sha256)
}

fn checked_workspace_file(root: &Path, relative: &str) -> Result<PathBuf, StorageError> {
    let mut candidate = root.to_path_buf();
    for part in relative.split('/') {
        candidate.push(part);
        let metadata = fs::symlink_metadata(&candidate)
            .map_err(|error| StorageError::caused_by("DOCUMENT_MISSING", error))?;
        if is_link(&metadata) {
            return Err(StorageError::new("WORKSPACE_SYMLINK_UNSUPPORTED"));
        }
    }
    if !candidate.is_file() || !absolute(&candidate)?.starts_with(root) {
        return Err(StorageError::new("BACKUP_PATH_INVALID"));
    }
    Ok(candidate)
}

fn copy_hash(
    source: &mut impl Read,
    destination: &mut impl Write,
) -> Result<(u64, String), StorageError> {
    let mut sha = Sha256::new();
    let mut size = 0u64;
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let read = source.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        destination.write_all(&buffer[..read])?;
        sha.update(&buffer[..read]);
        size += read as u64;
    }
    Ok((size, format!("{:x}", sha.finalize())))
}

fn zip_options(size: u64) -> SimpleFileOptions {
    SimpleFileOptions::default()
        .compression_method(CompressionMethod::Deflated)
        .large_file(size >= u32::MAX.into())
}

fn add_file(
    zip: &mut ZipWriter<File>,
    archive_path: String,
    source: &Path,
) -> Result<ArchiveMember, StorageError> {
    let mut source = File::open(source)?;
    zip.start_file(&archive_path, zip_options(source.metadata()?.len()))
        .map_err(archive_error)?;
    let (size, sha256) = copy_hash(&mut source, zip)?;
    Ok(ArchiveMember {
        archive_path,
        size,
        sha256,
    })
}

fn replace_directory(staging: &Path, target: &Path) -> Result<Option<PathBuf>, StorageError> {
    let previous = if target.exists() {
        if !target.is_dir() || is_link(&fs::symlink_metadata(target)?) {
            return Err(StorageError::new("BACKUP_PATH_INVALID"));
        }
        let name = target
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| StorageError::new("BACKUP_PATH_INVALID"))?;
        let previous = target.with_file_name(format!(
            ".{name}.before-restore-{}",
            Uuid::new_v4().simple()
        ));
        rename_with_retry(target, &previous)?;
        Some(previous)
    } else {
        None
    };
    if let Err(error) = rename_with_retry(staging, target) {
        if let Some(previous) = &previous {
            rename_with_retry(previous, target).map_err(|rollback| {
                StorageError::caused_by("WORKSPACE_RESTORE_ROLLBACK_FAILED", rollback)
            })?;
        }
        return Err(error.into());
    }
    Ok(previous)
}

fn rename_with_retry(source: &Path, target: &Path) -> io::Result<()> {
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        match fs::rename(source, target) {
            Err(error)
                if cfg!(windows)
                    && error.kind() == io::ErrorKind::PermissionDenied
                    && Instant::now() < deadline =>
            {
                std::thread::sleep(Duration::from_millis(50));
            }
            result => return result,
        }
    }
}

struct Staging(PathBuf);

impl Staging {
    fn new(parent: &Path, purpose: &str) -> Result<Self, StorageError> {
        let path = parent.join(format!(".studyflow-{purpose}-{}", Uuid::new_v4().simple()));
        fs::create_dir(&path)?;
        Ok(Self(path))
    }
}

impl Drop for Staging {
    fn drop(&mut self) {
        if fs::symlink_metadata(&self.0)
            .is_ok_and(|metadata| metadata.is_dir() && !is_link(&metadata))
        {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
}

fn archive_error(error: ZipError) -> StorageError {
    StorageError::caused_by("BACKUP_ARCHIVE_INVALID", error)
}

fn manifest_invalid(error: impl std::error::Error + Send + Sync + 'static) -> StorageError {
    StorageError::caused_by("BACKUP_MANIFEST_INVALID", error)
}

#[cfg(test)]
mod workspace_archive {
    use super::*;
    use crate::workspace::Workspace;

    #[test]
    fn checked_restore_respects_disk_and_preserves_the_prior_directory() {
        let test = Staging::new(&std::env::temp_dir(), "archive-test").unwrap();
        let source =
            Workspace::new(Settings::resolve(&test.0, Path::new("source"), None, None).unwrap());
        source.upgrade().unwrap();
        let output = test.0.join("archive.zip");
        let receipt = export(source.settings(), &output).unwrap();
        let validation = validate(&output).unwrap();
        assert!(validation.valid && validation.required_bytes == receipt.database_size);
        let target = test.0.join("protected");
        fs::create_dir(&target).unwrap();
        fs::write(target.join("sentinel"), "prior directory").unwrap();
        let error = restore_with_space_check(&output, &target, |_| Ok(0)).unwrap_err();
        assert_eq!(error.code, "WORKSPACE_DISK_FULL");
        assert!(target.join("sentinel").is_file());

        let active = Lease::shared(&target).unwrap();
        let error = restore(&output, &target).unwrap_err();
        assert_eq!(error.code, "WORKSPACE_MAINTENANCE_BUSY");
        assert!(target.join("sentinel").is_file());
        drop(active);

        let restored = restore(&output, &target).unwrap();
        assert!(restored.replaced_existing);
        assert!(restored
            .previous_workspace
            .unwrap()
            .join("sentinel")
            .is_file());
        assert!(target.join(WORKSPACE_DB).is_file());
    }

    #[test]
    fn failed_staging_rename_restores_the_original_target() {
        let test = Staging::new(&std::env::temp_dir(), "archive-rollback-test").unwrap();
        let target = test.0.join("original");
        fs::create_dir(&target).unwrap();
        fs::write(target.join("sentinel"), "prior directory").unwrap();
        assert!(replace_directory(&test.0.join("unavailable-staging"), &target).is_err());
        assert_eq!(
            fs::read_to_string(target.join("sentinel")).unwrap(),
            "prior directory"
        );
        assert_eq!(fs::read_dir(&test.0).unwrap().count(), 1);
    }
}
