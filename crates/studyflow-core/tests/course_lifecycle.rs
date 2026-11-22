use std::{fs, path::PathBuf};

use serde_json::json;
use studyflow_core::{
    application::course_publication::import_package,
    infrastructure::config::Settings,
    learning::{
        lifecycle,
        study_sessions::{self, OpenRequest},
    },
    planning,
    workspace::Workspace,
};

struct Fixture(PathBuf);

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn course_reset_does_not_seal_the_round_if_its_receipt_fails() {
    let fixture =
        Fixture(std::env::temp_dir().join(format!("studyflow-reset-{}", uuid::Uuid::new_v4())));
    fs::create_dir(&fixture.0).unwrap();
    let root = fixture.0.clone();
    let workspace = Workspace::new(Settings {
        workspace: root.clone(),
        database: root.join(".studyflow/studyflow.db"),
    });
    workspace.upgrade().unwrap();
    planning::create_plan(&mut workspace.open().unwrap().connection, "Reset tests", 1).unwrap();
    let course = import_package(&workspace, &json!({
        "schema":"studyflow.course-package/1", "package_id":"reset-atomic", "plan_line":"Reset tests",
        "course":{"title":"Reset"}, "lessons":[{"id":"lesson","title":"Lesson",
        "blocks":[{"id":"intro","type":"concept","title":"Example","body":"Read the example."}],
        "exercises":[{"id":"question","title":"Question","prompt":"Explain the example."}]}]
    })).unwrap();
    let course_id = course["course_id"].as_str().unwrap();
    let initial = study_sessions::open(
        &workspace,
        OpenRequest {
            course: course_id,
            plan: None,
            key: "original",
            new_version: false,
            review_round: false,
        },
    )
    .unwrap();
    let session = initial["study"]["id"].as_str().unwrap();
    let preview = lifecycle::reset_preview(&workspace, course_id).unwrap();
    let command = json!({"confirm":true,"expected_state_hash":preview["state_hash"],"expected_content_hash":preview["content_hash"],"idempotency_key":"reset"});
    let db = workspace.open().unwrap().connection;
    db.execute_batch("CREATE TRIGGER fail_reset BEFORE INSERT ON course_write_receipts WHEN new.operation='LEARNING_RESET' BEGIN SELECT RAISE(ABORT,'Synthetic reset receipt failure'); END;").unwrap();
    assert_eq!(
        lifecycle::reset(&workspace, course_id, &command)
            .unwrap_err()
            .code,
        "DATABASE_ERROR"
    );
    assert_eq!(
        lifecycle::reset_preview(&workspace, course_id).unwrap(),
        preview
    );
    assert_eq!(
        study_sessions::detail(&db, &root, session).unwrap(),
        initial
    );
    db.execute_batch("DROP TRIGGER fail_reset;").unwrap();
    let receipt = lifecycle::reset(&workspace, course_id, &command).unwrap();
    assert_eq!(receipt["reset_study_sessions"], json!([session]));
    assert_eq!(
        lifecycle::reset(&workspace, course_id, &command).unwrap(),
        receipt
    );
    assert_ne!(receipt["study_session_id"], session);
    assert_eq!(
        study_sessions::detail(&db, &root, session).unwrap()["study"]["is_current"],
        false
    );
}

#[test]
fn purge_respects_workspace_lease_and_a_document_shared_with_a_retained_course() {
    use studyflow_core::{courses::purge, infrastructure::leases::Lease, workspace::archive};

    let fixture =
        Fixture(std::env::temp_dir().join(format!("studyflow-purge-{}", uuid::Uuid::new_v4())));
    let root = fixture.0.join("workspace");
    fs::create_dir_all(&root).unwrap();
    let workspace = Workspace::new(Settings {
        workspace: root.clone(),
        database: root.join(".studyflow/studyflow.db"),
    });
    workspace.upgrade().unwrap();
    let db = workspace.open().unwrap().connection;
    planning::create_plan(&mut workspace.open().unwrap().connection, "Purge tests", 1).unwrap();
    let publish = |key: &str| {
        import_package(&workspace, &json!({
        "schema":"studyflow.course-package/1", "package_id":key, "plan_line":"Purge tests",
        "course":{"title":key}, "lessons":[{"id":"lesson","title":"Lesson",
        "blocks":[{"id":"intro","type":"concept","title":"Example","body":"Read the example."}]}]
    })).unwrap()
    };
    let first = publish("first");
    let second = publish("second");
    let ids = [first["course_id"].as_str().unwrap().to_owned()];
    let shared = first["paths"][0].as_str().unwrap();
    // Model a shared relative path left by a pre-versioned course import.
    db.execute(
        "UPDATE lessons SET markdown_path=? WHERE course_id=?",
        [shared, second["course_id"].as_str().unwrap()],
    )
    .unwrap();
    let initial = purge::preview(&workspace, Some(&ids)).unwrap();
    assert_eq!(initial["protected_document_paths"], json!([shared]));
    let backup = fixture.0.join("before-purge.zip");
    archive::export(workspace.settings(), &backup).unwrap();
    let in_use = Lease::shared(&root).unwrap();
    assert_eq!(
        purge::purge(&workspace, Some(&ids), &backup)
            .unwrap_err()
            .code,
        "WORKSPACE_MAINTENANCE_BUSY"
    );
    assert_eq!(purge::preview(&workspace, Some(&ids)).unwrap(), initial);
    drop(in_use);
    let receipt = purge::purge(&workspace, Some(&ids), &backup).unwrap();
    assert_eq!(receipt["files_removed"], json!([]));
    assert_eq!(receipt["deleted"], true);
    assert!(root.join(shared).is_file());
    assert_eq!(
        db.query_row(
            "SELECT COUNT(*) FROM documents WHERE relative_path=?",
            [shared],
            |row| row.get::<_, i64>(0)
        )
        .unwrap(),
        1
    );
}
