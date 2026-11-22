use std::fs;

use serde_json::json;
use studyflow_core::{
    application::course_publication::import_package,
    infrastructure::config::Settings,
    learning::{
        course_answers::{self, Operation, WriteRequest},
        study_sessions::{self, OpenRequest},
    },
    planning, reviews,
    workspace::Workspace,
};

struct Fixture(std::path::PathBuf);

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn feedback_and_error_evidence_roll_back_when_feedback_cannot_be_written() {
    let root =
        Fixture(std::env::temp_dir().join(format!("studyflow-review-{}", uuid::Uuid::new_v4())));
    fs::create_dir(&root.0).unwrap();
    let workspace = Workspace::new(Settings {
        workspace: root.0.clone(),
        database: root.0.join(".studyflow/studyflow.db"),
    });
    workspace.upgrade().unwrap();
    planning::create_plan(&mut workspace.open().unwrap().connection, "Review tests", 1).unwrap();
    let course = import_package(&workspace, &json!({
        "schema":"studyflow.course-package/1", "package_id":"review-atomic", "plan_line":"Review tests",
        "course":{"title":"Feedback"}, "lessons":[{"id":"lesson","title":"Lesson",
        "blocks":[{"id":"intro","type":"concept","title":"Example","body":"Read the example."}],
        "exercises":[{"id":"question","title":"Question","prompt":"Explain the example."}]}]
    })).unwrap();
    let course = course["course_id"].as_str().unwrap();
    let round = study_sessions::open(
        &workspace,
        OpenRequest {
            course,
            plan: None,
            key: "open",
            new_version: false,
            review_round: false,
        },
    )
    .unwrap();
    let study = round["study"]["id"].as_str().unwrap();
    let answers = json!([{"exercise_id":round["lessons"][0]["exercises"][0]["id"],"answer_text":"An incomplete explanation."}]);
    let submitted = course_answers::write(
        &workspace,
        WriteRequest {
            course,
            study: Some(study),
            operation: Operation::Submit,
            key: "submit",
            source: "USER_WEB",
            answers: &answers,
        },
    )
    .unwrap();
    let id = submitted["submissions"][0]["id"].as_str().unwrap();
    let feedback = json!({"submission_id":id,"decision":"REVISION_REQUIRED","summary":"Add the mechanism.","idempotency_key":"feedback"});
    let db = workspace.open().unwrap().connection;
    db.execute_batch("CREATE TRIGGER fail_feedback BEFORE INSERT ON review_feedback BEGIN SELECT RAISE(ABORT,'Synthetic feedback write failure'); END;").unwrap();
    assert_eq!(
        reviews::write(&workspace, &feedback).unwrap_err().code,
        "DATABASE_ERROR"
    );
    let (status, version): (String, i64) = db
        .query_row(
            "SELECT status,version FROM submissions WHERE id=?",
            [id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    assert_eq!(status, "WAITING_REVIEW");
    assert_eq!(
        version,
        submitted["submissions"][0]["version"].as_i64().unwrap()
    );
    db.execute_batch("DROP TRIGGER fail_feedback;").unwrap();
    let receipt = reviews::write(&workspace, &feedback).unwrap();
    assert_eq!(reviews::write(&workspace, &feedback).unwrap(), receipt);
    let stored: i64 = db
        .query_row(
            "SELECT COUNT(*) FROM review_feedback WHERE submission_id=?",
            [id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(stored, 1);
}
