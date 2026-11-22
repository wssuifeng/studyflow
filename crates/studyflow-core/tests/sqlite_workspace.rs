use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::Connection;
use studyflow_core::{
    infrastructure::{config::Settings, leases::Lease, sqlite::CURRENT_REVISION},
    workspace::Workspace,
};

struct Scratch(PathBuf);

impl Scratch {
    fn new() -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory =
            std::env::temp_dir().join(format!("studyflow-sqlite-{}-{now}", std::process::id()));
        fs::create_dir(&directory).unwrap();
        Self(directory)
    }

    fn work(&self) -> Workspace {
        Workspace::new(Settings::resolve(&self.0, Path::new("学习 Workspace"), None, None).unwrap())
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn discovery_and_read_only_inspection_do_not_create_a_workspace() {
    let scratch = Scratch::new();
    let workspace = scratch.work();
    assert_eq!(
        workspace.inspect().unwrap_err().code,
        "WORKSPACE_NOT_INITIALIZED"
    );
    assert!(!workspace.settings().workspace.exists());
    assert!(fs::read_dir(&scratch.0).unwrap().next().is_none());
}

#[test]
fn alternate_database_path_and_sqlite_url_have_legacy_precedence() {
    let scratch = Scratch::new();
    let default = scratch.work();
    let root = &default.settings().workspace;
    let named = Settings::resolve(&scratch.0, root, None, Some(Path::new("alternate.db"))).unwrap();
    assert_eq!(named.database.file_name().unwrap(), "alternate.db");
    assert_eq!(named.database.parent().unwrap(), root.parent().unwrap());
    let with_url = Settings::resolve(
        &scratch.0,
        root,
        Some("sqlite:///db%20space/file.db"),
        Some(Path::new("ignored.db")),
    )
    .unwrap();
    assert_eq!(with_url.database, root.join("db space/file.db"));
    for bad in [
        "mysql://user:test@example.test/test",
        "sqlite://",
        "sqlite:///:memory:",
        "sqlite:///https://example.test",
    ] {
        assert_eq!(
            Settings::resolve(&scratch.0, root, Some(bad), None)
                .unwrap_err()
                .code,
            "UNSUPPORTED_DATABASE"
        );
    }
    assert!(fs::read_dir(&scratch.0).unwrap().next().is_none());
}

#[test]
fn standalone_legacy_database_is_used_only_in_the_default_directory() {
    let scratch = Scratch::new();
    let legacy = scratch.0.join("studyflow.db");
    fs::write(&legacy, []).unwrap();
    let default = Settings::resolve(&scratch.0, Path::new("."), None, None).unwrap();
    assert_eq!(default.database, legacy);
    let other = scratch.work();
    assert_eq!(
        other.settings().database,
        other.settings().workspace.join(".studyflow/studyflow.db")
    );
}

#[test]
fn explicit_upgrade_initializes_current_schema_and_configures_connections() {
    let scratch = Scratch::new();
    let workspace = scratch.work();
    let written = workspace.upgrade().unwrap();
    assert_eq!(written.status, "FRESH_DATABASE_MIGRATED");
    assert!(written.upgraded && written.backup.is_none());
    let still_current = workspace.upgrade().unwrap();
    assert_eq!(still_current.status, "ALREADY_CURRENT");
    assert!(!still_current.upgraded && still_current.backup.is_none());
    let read = workspace.inspect().unwrap();
    let get = |sql: &str| read.query_row(sql, [], |row| row.get::<_, i64>(0)).unwrap();
    assert_eq!(get("PRAGMA query_only"), 1);
    assert_eq!(get("PRAGMA foreign_keys"), 1);
    assert_eq!(get("PRAGMA temp_store"), 2);
    let revision: String = read
        .query_row("SELECT version_num FROM alembic_version", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(revision, CURRENT_REVISION);
    assert!(read.execute("DELETE FROM plan_lines", []).is_err());
}

#[test]
fn stamped_future_schema_and_inconsistent_current_schema_are_refused() {
    for (setup, expected) in [
        (
            "UPDATE alembic_version SET version_num='9999_future'",
            "NEWER_SCHEMA_UNSUPPORTED",
        ),
        (
            "ALTER TABLE learning_progress DROP COLUMN last_position",
            "SCHEMA_REVISION_MISMATCH",
        ),
    ] {
        let scratch = Scratch::new();
        let workspace = scratch.work();
        workspace.upgrade().unwrap();
        let db = &workspace.settings().database;
        Connection::open(db).unwrap().execute_batch(setup).unwrap();
        let before = fs::read(db).unwrap();
        assert_eq!(workspace.upgrade().unwrap_err().code, expected);
        assert_eq!(before, fs::read(db).unwrap());
    }
}

#[test]
fn failed_mid_migration_rolls_back_and_keeps_a_consistent_backup() {
    let scratch = Scratch::new();
    let workspace = scratch.work();
    let db = &workspace.settings().database;
    fs::create_dir_all(db.parent().unwrap()).unwrap();
    let connection = Connection::open(db).unwrap();
    connection
        .execute_batch(include_str!(
            "../src/infrastructure/sqlite/migrations/0001_mvp_baseline.sql"
        ))
        .unwrap();
    connection.execute_batch(
        "CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY);
         INSERT INTO alembic_version(version_num) VALUES('0001_mvp_baseline');
         INSERT INTO plan_lines(id,name,priority,status) VALUES('sentinel','Sentinel plan',1,'ACTIVE');
         CREATE VIEW plan_notebooks AS SELECT id FROM plan_lines;"
    ).unwrap();
    drop(connection);
    let original = fs::read(db).unwrap();
    assert!(workspace.upgrade().is_err());
    assert_eq!(original, fs::read(db).unwrap());
    let backup = fs::read_dir(db.parent().unwrap())
        .unwrap()
        .find_map(|entry| {
            let path = entry.unwrap().path();
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .contains(".backup-")
                .then_some(path)
        })
        .unwrap();
    let saved = Connection::open(backup).unwrap();
    let name: String = saved
        .query_row(
            "SELECT name FROM plan_lines WHERE id='sentinel'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(name, "Sentinel plan");
    assert!(saved.prepare("SELECT task_kind FROM tasks").is_err());
}

#[test]
fn shared_runs_and_exclusive_maintenance_are_cross_process() {
    let scratch = Scratch::new();
    let workspace = scratch.work();
    workspace.upgrade().unwrap();
    let local = workspace.open().unwrap();
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "lease_worker", "--nocapture"])
        .env(
            "STUDYFLOW_SQLITE_TEST_CHILD",
            &workspace.settings().workspace,
        )
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut reader = BufReader::new(child.stdout.take().unwrap());
    assert!(reader
        .by_ref()
        .lines()
        .any(|line| line.unwrap().ends_with("shared lease ready")));
    drop(local);
    assert_eq!(
        workspace.upgrade().unwrap_err().code,
        "WORKSPACE_MAINTENANCE_BUSY"
    );
    child.stdin.take().unwrap().write_all(b"x").unwrap();
    std::io::copy(&mut reader, &mut std::io::sink()).unwrap();
    assert!(child.wait().unwrap().success());
    let exclusive = Lease::exclusive(&workspace.settings().workspace).unwrap();
    assert_eq!(
        workspace.open().err().unwrap().code,
        "WORKSPACE_MAINTENANCE_BUSY"
    );
    drop(exclusive);
    assert!(workspace.open().is_ok());
}

#[test]
fn lease_worker() {
    if let Some(path) = std::env::var_os("STUDYFLOW_SQLITE_TEST_CHILD") {
        let _lease = Lease::shared(Path::new(&path)).unwrap();
        println!("shared lease ready");
        std::io::stdout().flush().unwrap();
        std::io::stdin().read_exact(&mut [0; 1]).unwrap();
    }
}
