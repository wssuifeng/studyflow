use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use rusqlite::backup::{Backup, StepResult};
use rusqlite::{Connection, OpenFlags, OptionalExtension, TransactionBehavior};

use super::{connect, schema};
use crate::infrastructure::StorageError;

macro_rules! migration_files {
    ($($revision:literal),+ $(,)?) => {
        &[$(($revision, include_str!(concat!("migrations/", $revision, ".sql")))),+]
    };
}

const MIGRATIONS: &[(&str, &str)] = migration_files!(
    "0001_mvp_baseline",
    "0002_generic_metadata",
    "0003_learning_console_lifecycle",
    "0004_learning_progress",
    "0005_course_answers",
    "0006_course_study",
    "0007_learning_tools",
    "0008_plan_notebooks",
    "0009_write_contract",
    "0010_review_tasks",
    "0011_course_revisions",
    "0012_plan_management",
    "0013_english_specialty",
    "0014_study_restart",
    "0015_english_remediation",
    "0016_notebook_document",
    "0017_course_experience",
    "0018_plan_course_sequence",
);

const BASE_TABLES: &[&str] = &[
    "plan_lines",
    "stages",
    "tasks",
    "time_blocks",
    "courses",
    "lessons",
    "exercises",
    "submissions",
    "review_feedback",
    "documents",
    "context_snapshots",
    "event_logs",
];

pub const CURRENT_REVISION: &str = MIGRATIONS[MIGRATIONS.len() - 1].0;

#[derive(Debug)]
pub struct MigrationReceipt {
    pub status: &'static str,
    pub upgraded: bool,
    pub backup: Option<PathBuf>,
}

pub fn upgrade(path: &Path) -> Result<MigrationReceipt, StorageError> {
    let exists = path.is_file();
    if exists && fs::metadata(path)?.permissions().readonly() {
        return Err(StorageError::new("DATABASE_READ_ONLY"));
    }
    let mut connection = if exists {
        connect(path, OpenFlags::SQLITE_OPEN_READ_WRITE)?
    } else {
        let parent = path
            .parent()
            .ok_or_else(|| StorageError::new("INVALID_WORKSPACE_PATH"))?;
        fs::create_dir_all(parent)?;
        connect(
            path,
            OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_CREATE,
        )?
    };
    let tables = table_names(&connection)?;
    let version = read_revision(&connection, &tables)?;
    if version.as_deref() == Some(CURRENT_REVISION) {
        validate_current(&connection, "SCHEMA_REVISION_MISMATCH")?;
        return Ok(MigrationReceipt {
            status: "ALREADY_CURRENT",
            upgraded: false,
            backup: None,
        });
    }

    let (start, status) = migration_start(&connection, &tables, version.as_deref())?;
    let backup = (!tables.is_empty())
        .then(|| backup_database(&connection, path))
        .transpose()?;
    let tx = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));")?;
    for &(revision, sql) in &MIGRATIONS[start..] {
        apply_revision(&tx, revision, sql)?;
        tx.execute("DELETE FROM alembic_version", [])?;
        tx.execute(
            "INSERT INTO alembic_version(version_num) VALUES (?)",
            [revision],
        )?;
    }
    validate_current(&tx, "SCHEMA_REVISION_MISMATCH")?;
    let violations = tx.query_row("SELECT COUNT(*) FROM pragma_foreign_key_check", [], |row| {
        row.get::<_, i64>(0)
    })?;
    if violations != 0 {
        return Err(StorageError::new("SCHEMA_FOREIGN_KEY_VIOLATION"));
    }
    tx.commit()?;
    Ok(MigrationReceipt {
        status,
        upgraded: true,
        backup,
    })
}

fn migration_start(
    connection: &Connection,
    tables: &HashSet<String>,
    revision: Option<&str>,
) -> Result<(usize, &'static str), StorageError> {
    if tables.is_empty() {
        return Ok((0, "FRESH_DATABASE_MIGRATED"));
    }
    let present = BASE_TABLES
        .iter()
        .filter(|&&name| tables.contains(name))
        .count();
    if present != BASE_TABLES.len() {
        let code = if present == 0 {
            "UNKNOWN_SCHEMA"
        } else {
            "PARTIAL_SCHEMA_UNSUPPORTED"
        };
        return Err(StorageError::new(code));
    }
    if let Some(revision) = revision {
        return MIGRATIONS
            .iter()
            .position(|(known, _)| *known == revision)
            .map(|index| (index + 1, "LEGACY_UPGRADED"))
            .ok_or_else(|| unknown_revision(revision));
    }
    let modern_marker = tables.contains("plan_course_items")
        && tables.contains("course_schedule_items")
        && has_column(connection, "tasks", "course_schedule_item_id")?
        && has_column(connection, "submissions", "attempt_kind")?
        && has_column(connection, "courses", "subject")?
        && has_column(connection, "exercises", "exercise_type")?;
    if modern_marker {
        Ok((3, "LEGACY_STAMPED_UPGRADED"))
    } else {
        Ok((1, "LEGACY_UPGRADED"))
    }
}

fn unknown_revision(revision: &str) -> StorageError {
    let current = MIGRATIONS.len() as u32;
    let number = revision
        .split('_')
        .next()
        .and_then(|part| part.parse::<u32>().ok());
    StorageError::new(if number.is_some_and(|number| number > current) {
        "NEWER_SCHEMA_UNSUPPORTED"
    } else {
        "SCHEMA_REVISION_MISMATCH"
    })
}

const ARCHIVE_TABLES: &[&str] = &[
    "plan_lines",
    "courses",
    "lessons",
    "exercises",
    "submissions",
    "review_feedback",
    "documents",
];

pub(crate) fn is_known_revision(revision: &str) -> bool {
    revision == "UNSTAMPED" || MIGRATIONS.iter().any(|(known, _)| *known == revision)
}

pub(crate) fn archive_revision(connection: &Connection) -> Result<String, StorageError> {
    let tables = table_names(connection)?;
    if ARCHIVE_TABLES.iter().any(|table| !tables.contains(*table)) {
        return Err(StorageError::new("UNKNOWN_SCHEMA"));
    }
    if !tables.contains("alembic_version") {
        return Ok("UNSTAMPED".into());
    }
    read_revision(connection, &tables)?
        .filter(|revision| is_known_revision(revision) && revision != "UNSTAMPED")
        .ok_or_else(|| StorageError::new("UNKNOWN_SCHEMA"))
}

fn table_names(connection: &Connection) -> Result<HashSet<String>, StorageError> {
    let mut statement = connection.prepare(
        "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'",
    )?;
    let tables = statement
        .query_map([], |row| row.get::<_, String>(0))?
        .collect::<Result<_, _>>()?;
    Ok(tables)
}

fn read_revision(
    connection: &Connection,
    tables: &HashSet<String>,
) -> Result<Option<String>, StorageError> {
    if !tables.contains("alembic_version") {
        return Ok(None);
    }
    if !has_column(connection, "alembic_version", "version_num")? {
        return Err(StorageError::new("SCHEMA_REVISION_MISMATCH"));
    }
    let count: i64 =
        connection.query_row("SELECT COUNT(*) FROM alembic_version", [], |row| row.get(0))?;
    if count > 1 {
        return Err(StorageError::new("SCHEMA_REVISION_MISMATCH"));
    }
    Ok(connection
        .query_row("SELECT version_num FROM alembic_version", [], |row| {
            row.get(0)
        })
        .optional()?)
}

pub(super) fn validate_current(
    connection: &Connection,
    code: &'static str,
) -> Result<(), StorageError> {
    validate_read_schema(connection, code)?;
    let valid: bool = connection.query_row("SELECT EXISTS(SELECT 1 FROM pragma_index_list('plan_course_items') WHERE name='uq_plan_course_item_position' AND [unique]=1)", [], |row| row.get(0))?;
    let index = index_columns(connection, "uq_plan_course_item_position")?;
    if !valid || index != ["plan_line_id", "track", "sequence_number"] {
        return Err(StorageError::new(code));
    }
    Ok(())
}

pub(super) fn validate_read_schema(
    connection: &Connection,
    code: &'static str,
) -> Result<(), StorageError> {
    let tables = table_names(connection)?;
    if let Some(revision) = read_revision(connection, &tables)? {
        if revision != CURRENT_REVISION {
            let unknown = unknown_revision(&revision);
            return Err(if unknown.code == "NEWER_SCHEMA_UNSUPPORTED" {
                unknown
            } else {
                StorageError::new(code)
            });
        }
    }
    for &(table, expected) in schema::TABLES {
        if !tables.contains(table) {
            return Err(StorageError::new(code));
        }
        let mut query = connection.prepare("SELECT name FROM pragma_table_info(?)")?;
        let actual: HashSet<String> = query
            .query_map([table], |row| row.get(0))?
            .collect::<Result<_, _>>()?;
        if expected.iter().any(|col| !actual.contains(*col)) {
            return Err(StorageError::new(code));
        }
    }
    Ok(())
}

fn has_column(connection: &Connection, table: &str, column: &str) -> Result<bool, StorageError> {
    Ok(connection.query_row(
        "SELECT EXISTS(SELECT 1 FROM pragma_table_info(?) WHERE name=?)",
        [table, column],
        |row| row.get(0),
    )?)
}

fn index_columns(connection: &Connection, index: &str) -> Result<Vec<String>, StorageError> {
    let mut query = connection.prepare("SELECT name FROM pragma_index_info(?) ORDER BY seqno")?;
    let columns = query
        .query_map([index], |row| row.get::<_, Option<String>>(0))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(columns.into_iter().flatten().collect())
}

fn backup_database(connection: &Connection, path: &Path) -> Result<PathBuf, StorageError> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("studyflow");
    let suffix = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("db");
    let file = path.with_file_name(format!(
        "{stem}.backup-{now}-{}.{suffix}",
        std::process::id()
    ));
    drop(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&file)?,
    );
    if let Err(error) = copy_database(connection, &file) {
        let _ = fs::remove_file(&file);
        return Err(StorageError::caused_by("DATABASE_BACKUP_FAILED", error));
    }
    Ok(file)
}

pub(crate) fn copy_database(source: &Connection, target: &Path) -> Result<(), StorageError> {
    let mut destination = Connection::open(target)?;
    let backup = Backup::new(source, &mut destination)?;
    let mut busy_count = 0;
    loop {
        match backup.step(256)? {
            StepResult::Done => return Ok(()),
            StepResult::More => busy_count = 0,
            _ => {
                busy_count += 1;
                if busy_count >= 25 {
                    return Err(StorageError::new("DATABASE_BUSY"));
                }
                std::thread::sleep(Duration::from_millis(20));
            }
        }
    }
}

fn apply_revision(connection: &Connection, revision: &str, sql: &str) -> Result<(), StorageError> {
    if revision == "0007_learning_tools" {
        let (rebuild, add_notes) = sql
            .split_once("CREATE TABLE study_notes")
            .expect("checked-in event migration");
        if has_old_event_constraint(connection)? {
            let mut statement = connection.prepare("SELECT sql FROM sqlite_schema WHERE tbl_name='event_logs' AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type")?;
            let dependent_ddl = statement
                .query_map([], |row| row.get::<_, String>(0))?
                .collect::<Result<Vec<_>, _>>()?;
            connection.execute_batch(rebuild)?;
            for ddl in dependent_ddl {
                connection.execute_batch(&ddl)?;
            }
        }
        execute_additive(connection, &format!("CREATE TABLE study_notes{add_notes}"))?;
    } else {
        if revision == CURRENT_REVISION {
            normalize_course_sequence(connection)?;
        }
        execute_additive(connection, sql)?;
        if revision == "0003_learning_console_lifecycle" {
            populate_memberships(connection)?;
        }
    }
    Ok(())
}

fn execute_additive(connection: &Connection, sql: &str) -> Result<(), StorageError> {
    let sql = sql.replace("\r\n", "\n");
    for statement in sql
        .split(";\n")
        .map(str::trim)
        .filter(|line| !line.is_empty())
    {
        if let Some(rest) = statement.strip_prefix("ALTER TABLE ") {
            if let Some((table, definition)) = rest.split_once(" ADD COLUMN ") {
                let column = definition
                    .split_whitespace()
                    .next()
                    .expect("checked-in column migration");
                if has_column(connection, table, column)? {
                    continue;
                }
            }
        }
        let guarded = ["CREATE UNIQUE INDEX ", "CREATE INDEX ", "CREATE TABLE "]
            .iter()
            .find_map(|prefix| {
                statement
                    .strip_prefix(prefix)
                    .map(|rest| format!("{prefix}IF NOT EXISTS {rest}"))
            });
        connection.execute_batch(guarded.as_deref().unwrap_or(statement))?;
    }
    Ok(())
}

fn has_old_event_constraint(connection: &Connection) -> Result<bool, StorageError> {
    let mut statement = connection.prepare(
        "SELECT name FROM pragma_index_list('event_logs') WHERE [unique] = 1 AND origin='u'",
    )?;
    let names = statement
        .query_map([], |row| row.get::<_, String>(0))?
        .collect::<Result<Vec<_>, _>>()?;
    for name in names {
        let mut columns = index_columns(connection, &name)?;
        columns.sort();
        if columns == ["action", "object_id", "object_type", "source", "summary"] {
            return Ok(true);
        }
    }
    Ok(false)
}

fn populate_memberships(connection: &Connection) -> Result<(), StorageError> {
    connection.execute_batch(r#"
        WITH missing AS (
            SELECT id, plan_line_id, ROW_NUMBER() OVER (PARTITION BY plan_line_id ORDER BY created_at,id) AS seq
            FROM courses AS c WHERE plan_line_id IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM plan_course_items WHERE plan_line_id=c.plan_line_id AND course_id=c.id)
        )
        INSERT INTO plan_course_items(id, plan_line_id, course_id, sequence_number, status)
        SELECT lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)),2) || '-8' || substr(hex(randomblob(2)),2) || '-' || hex(randomblob(6))),
               plan_line_id, id, seq, 'PLANNED' FROM missing;
    "#)?;
    Ok(())
}

fn normalize_course_sequence(connection: &Connection) -> Result<(), StorageError> {
    connection.execute_batch(r#"
        CREATE TEMP TABLE sf_0018_positions(id TEXT PRIMARY KEY, seq INTEGER NOT NULL);
        INSERT INTO sf_0018_positions
        SELECT id, ROW_NUMBER() OVER(PARTITION BY plan_line_id, COALESCE(NULLIF(track,''),'MAIN') ORDER BY track,sequence_number,id)
        FROM plan_course_items;
        UPDATE plan_course_items SET sequence_number=-(SELECT seq FROM sf_0018_positions WHERE id=plan_course_items.id);
        UPDATE plan_course_items SET sequence_number=-sequence_number;
        DROP TABLE sf_0018_positions;
    "#)?;
    Ok(())
}
