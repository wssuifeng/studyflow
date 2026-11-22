use std::{fs, path::PathBuf};

use serde_json::{json, Value};
use studyflow_core::{
    application::course_publication::import_package,
    infrastructure::config::Settings,
    learning::{
        course_answers::{self, Operation, WriteRequest},
        study_sessions::{self, OpenRequest},
    },
    planning,
    workspace::Workspace,
};

struct Fixture(PathBuf);

impl Fixture {
    fn make() -> (Self, Workspace) {
        let root = std::env::temp_dir().join(format!("studyflow-round-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let workspace = Workspace::new(Settings {
            workspace: root.clone(),
            database: root.join(".studyflow/studyflow.db"),
        });
        workspace.upgrade().unwrap();
        planning::create_plan(&mut workspace.open().unwrap().connection, "Round tests", 1).unwrap();
        (Self(root), workspace)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn import(workspace: &Workspace, exercises: Value) -> Value {
    import_package(workspace, &json!({"schema":"studyflow.course-package/1","package_id":"round-tests","plan_line":"Round tests","course":{"title":"Review me"},
        "lessons":[{"id":"intro","title":"Intro","blocks":[{"id":"text","type":"concept","title":"Example","body":"Study this."}],"exercises":exercises}]})).unwrap()
}

fn open(
    workspace: &Workspace,
    course: &str,
    key: &str,
    new_version: bool,
    review_round: bool,
) -> Result<Value, studyflow_core::infrastructure::StorageError> {
    study_sessions::open(
        workspace,
        OpenRequest {
            course,
            key,
            new_version,
            review_round,
            plan: None,
        },
    )
}

#[test]
fn reading_complete_can_open_a_review_round_after_freezing_progress() {
    let (_fixture, workspace) = Fixture::make();
    let published = import(&workspace, json!([]));
    let course = published["course_id"].as_str().unwrap();
    let initial = open(&workspace, course, "open", false, false).unwrap();
    let id = initial["study"]["id"].as_str().unwrap();
    let lesson = initial["lessons"][0]["id"].as_str().unwrap();
    assert_eq!(
        study_sessions::complete_reading(&workspace, id)
            .unwrap_err()
            .code,
        "READING_INCOMPLETE"
    );
    assert_eq!(
        study_sessions::save_progress(&workspace, id, lesson, 100, "End", Some(1)).unwrap()
            ["version"],
        2
    );
    assert_eq!(
        study_sessions::save_progress(&workspace, id, lesson, 0, "Stale", Some(1))
            .unwrap_err()
            .code,
        "VERSION_CONFLICT"
    );
    assert_eq!(
        study_sessions::complete_reading(&workspace, id).unwrap()["course"]["study_status"],
        "READ_COMPLETED"
    );
    assert_eq!(
        open(&workspace, course, "no-changes", true, false)
            .unwrap_err()
            .code,
        "COURSE_VERSION_UNCHANGED"
    );
    let new = open(&workspace, course, "review", false, true).unwrap();
    assert_ne!(new["study"]["id"], id);
    assert_eq!(new["study"]["revision"], 2);
    assert_eq!(new["course"]["reading_percent"], 0);
    assert_eq!(
        study_sessions::save_progress(&workspace, id, lesson, 100, "Stale", Some(2))
            .unwrap_err()
            .code,
        "STUDY_ROUND_SUPERSEDED"
    );
    let old = open(&workspace, course, "open", false, false).unwrap();
    assert_eq!(old["study"]["id"], id);
    assert_eq!(old["study"]["is_current"], false);
}

#[test]
fn an_error_after_the_first_submission_rolls_back_answers_events_and_receipt() {
    let (_fixture, workspace) = Fixture::make();
    let published = import(
        &workspace,
        json!([{"id":"first","title":"First","prompt":"Explain."},{"id":"second","title":"Second","prompt":"Summarize."}]),
    );
    let course = published["course_id"].as_str().unwrap();
    let detail = open(&workspace, course, "opening", false, false).unwrap();
    let round = detail["study"]["id"].as_str().unwrap();
    let questions = detail["lessons"][0]["exercises"].as_array().unwrap();
    let entries = json!([{"exercise_id":questions[0]["id"],"answer_text":"First answer"},{"exercise_id":questions[1]["id"],"answer_text":"Second answer"}]);
    let db = workspace.open().unwrap();
    db.connection.execute_batch("CREATE TRIGGER reject_second BEFORE INSERT ON submissions WHEN NEW.answer_text='Second answer' BEGIN SELECT RAISE(ABORT,'Synthetic disk-write fault'); END;").unwrap();
    let command = || {
        course_answers::write(
            &workspace,
            WriteRequest {
                course,
                study: Some(round),
                key: "batch",
                source: "USER_WEB",
                operation: Operation::Submit,
                answers: &entries,
            },
        )
    };
    assert_eq!(command().unwrap_err().code, "DATABASE_ERROR");
    let counts = || {
        db.connection.query_row("SELECT (SELECT COUNT(*) FROM submissions),(SELECT COUNT(*) FROM event_logs WHERE object_type='submission'),(SELECT COUNT(*) FROM course_write_receipts WHERE operation='SUBMIT')",[],
        |row|Ok((row.get::<_,i64>(0)?,row.get::<_,i64>(1)?,row.get::<_,i64>(2)?))).unwrap()
    };
    assert_eq!(counts(), (0, 0, 0));
    db.connection
        .execute_batch("DROP TRIGGER reject_second;")
        .unwrap();
    let result = command().unwrap();
    assert_eq!(command().unwrap(), result);
    assert_eq!(counts(), (2, 2, 1));
    let read = course_answers::read(&db.connection, course, Some(round)).unwrap();
    assert_eq!(
        read["answers"][1]["submission"]["answer_text"],
        "Second answer"
    );
}
