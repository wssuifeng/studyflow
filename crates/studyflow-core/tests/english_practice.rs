use std::{fs, path::PathBuf};

use serde_json::json;
use studyflow_core::{
    application::{
        course_publication::import_package,
        english::{self, Command},
    },
    courses::practice::{GroupKind, PreviewError},
    infrastructure::config::Settings,
    learning::{
        english as training,
        practice_groups::{self, WriteRequest},
        study_sessions::{self, OpenRequest},
    },
    planning,
    workspace::Workspace,
};

struct WorkspaceFixture(PathBuf);

impl Drop for WorkspaceFixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn focused_mixed_course_preserves_order_objective_confirmation_and_ungraded_essay() {
    let fixture = WorkspaceFixture(
        std::env::temp_dir().join(format!("studyflow-focused-{}", uuid::Uuid::new_v4())),
    );
    fs::create_dir(&fixture.0).unwrap();
    let workspace = Workspace::new(Settings {
        workspace: fixture.0.clone(),
        database: fixture.0.join(".studyflow/studyflow.db"),
    });
    workspace.upgrade().unwrap();
    let package = studyflow_core::courses::packages::parse(include_bytes!(
        "../../../skills/studyflow-agent/examples/course-package-v8.json"
    ))
    .unwrap();
    planning::create_plan(
        &mut workspace.open().unwrap().connection,
        package["plan_line"].as_str().unwrap(),
        1,
    )
    .unwrap();
    let imported = import_package(&workspace, &package).unwrap();
    let opened = study_sessions::open(
        &workspace,
        OpenRequest {
            course: imported["course_id"].as_str().unwrap(),
            plan: None,
            key: "start",
            new_version: false,
            review_round: false,
        },
    )
    .unwrap();
    let study = opened["study"]["id"].as_str().unwrap();
    let db = workspace.inspect().unwrap();
    let view = training::get(&db, &fixture.0, study).unwrap();
    let items = view["items"].as_array().unwrap();
    let kinds: Vec<_> = items
        .iter()
        .map(|item| item["kind"].as_str().unwrap())
        .collect();
    assert_eq!(kinds, ["READING_GROUP", "tokens", "ESSAY"]);
    assert!(opened["lessons"][0]["markdown"]
        .as_str()
        .is_some_and(|text| !text.contains("structured_lesson")));
    let reading = items[0]["exercise_id"].as_str().unwrap();
    let prompt = practice_groups::get(&db, study, reading, GroupKind::Reading).unwrap();
    assert!(prompt["result"].is_null());
    assert!(prompt["questions"][0].get("correct_option_id").is_none());
    let answers = json!({"where":"b","meeting-place":{"place":"  ＴＨＥ　ＬＩＢＲＡＲＹ  "}});
    let read = |key, answers: &serde_json::Value| {
        practice_groups::write(
            &workspace,
            WriteRequest {
                study,
                exercise: reading,
                answers: answers.as_object().unwrap(),
                key,
                position: 1,
                version: 0,
                kind: GroupKind::Reading,
                confirm: true,
            },
        )
    };
    assert!(matches!(
        read("incomplete", &json!({"where":"b"})),
        Err(PreviewError::Incomplete {
            code: "INCOMPLETE_READING_GROUP",
            ..
        })
    ));
    let confirmed = read("confirm", &answers).unwrap();
    assert_eq!(confirmed["result"]["correct"], 2);
    assert_eq!(read("confirm", &answers).unwrap(), confirmed);
    let item = items[1]["exercise_id"].as_str().unwrap();
    assert_eq!(
        training::answer(&db, study, item).unwrap_err().code,
        "REFERENCE_HIDDEN"
    );
    let answer = package["lessons"][0]["exercises"][1]["english"]["target"]
        .as_str()
        .unwrap();
    let save = english::write(
        &workspace,
        Some(study),
        "draft-word",
        Command::Save {
            exercise: item,
            answer,
            expected: 0,
            skipped: false,
        },
    )
    .unwrap();
    let version = save["answer_version"].as_i64().unwrap();
    assert_eq!(
        english::write(
            &workspace,
            Some(study),
            "check-word",
            Command::Check {
                exercise: item,
                expected: version
            }
        )
        .unwrap()["matched"],
        true
    );
    let essay = items[2]["exercise_id"].as_str().unwrap();
    let text = "My proposal has two ideas.\n\nThe library could offer a tour and a map.";
    english::write(
        &workspace,
        Some(study),
        "draft-essay",
        Command::Save {
            exercise: essay,
            answer: text,
            expected: 0,
            skipped: false,
        },
    )
    .unwrap();
    assert_eq!(
        english::write(
            &workspace,
            Some(study),
            "essay-local-check",
            Command::Check {
                exercise: essay,
                expected: 1
            }
        )
        .unwrap_err()
        .code,
        "COURSE_ITEM_TYPE_MISMATCH"
    );
    assert_eq!(
        english::write(
            &workspace,
            Some(study),
            "essay-review",
            Command::Review {
                exercise: essay,
                expected: 1
            }
        )
        .unwrap()["status"],
        "WAITING_REVIEW"
    );
    let versions = json!({reading:1,item:1,essay:2});
    let result = english::write(
        &workspace,
        Some(study),
        "submit",
        Command::Submit {
            versions: versions.as_object().unwrap(),
        },
    )
    .unwrap();
    assert_eq!(result["completed"], true);
    assert_eq!(result["waiting_review"], 1);
    let final_view = training::get(&db, &fixture.0, study).unwrap();
    assert_eq!(final_view["items"][2]["answer_text"], text);
    assert_eq!(final_view["items"][2]["matched"], false);
}
