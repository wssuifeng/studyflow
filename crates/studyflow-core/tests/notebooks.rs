use std::{fs, path::PathBuf};

use serde_json::{json, Value};
use studyflow_core::{
    application::course_publication::import_package,
    courses::packages,
    infrastructure::config::Settings,
    learning::{
        notebook,
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
fn notebook_upgrade_and_section_citation_are_atomic_and_replayable() {
    let fixture =
        Fixture(std::env::temp_dir().join(format!("studyflow-notebook-{}", uuid::Uuid::new_v4())));
    fs::create_dir(&fixture.0).unwrap();
    let workspace = Workspace::new(Settings {
        workspace: fixture.0.clone(),
        database: fixture.0.join(".studyflow/studyflow.db"),
    });
    workspace.upgrade().unwrap();
    let package = packages::parse(include_bytes!(
        "../../../skills/studyflow-agent/examples/course-package-v5.json"
    ))
    .unwrap();
    let plan = planning::create_plan(
        &mut workspace.open().unwrap().connection,
        package["plan_line"].as_str().unwrap(),
        1,
    )
    .unwrap();
    let plan_id = plan["plan_line"]["id"]
        .as_str()
        .or_else(|| plan["id"].as_str())
        .unwrap();
    let course = import_package(&workspace, &package).unwrap();
    let course_id = course["course_id"].as_str().unwrap();
    let round = study_sessions::open(
        &workspace,
        OpenRequest {
            course: course_id,
            plan: None,
            key: "round",
            new_version: false,
            review_round: false,
        },
    )
    .unwrap();
    let study = round["study"]["id"].as_str().unwrap();
    let lesson = round["lessons"][0]["id"].as_str().unwrap();
    let quote = "The CPU executes instructions.";
    let legacy = json!({"plan_line_id":plan_id,"blocks":[{"id":"legacy","text":"旧笔记"}],"expected_version":0,"idempotency_key":"legacy"});
    let legacy_receipt = notebook::save_blocks(&workspace, &legacy, "TEST").unwrap();
    let source = json!({"id":"clip","original":quote,"course_id":course_id,"lesson_id":lesson,"source_study_id":study,"source_block_id":"idea","source_section_id":"main"});
    let command = json!({"plan_line_id":plan_id,"new_sources":[source],"expected_version":1,"idempotency_key":"upgrade","operations":[{
        "type":"insert_entry","entry":{"id":"with-citation","scope":"LESSON","course_id":course_id,"lesson_id":lesson,"content":[{"type":"paragraph","content":[{"type":"text","text":quote,"marks":[{"type":"citation","attrs":{"sourceId":"clip","occurrenceId":"once"}}]}]}]}
    }]});
    let mut forged = command.clone();
    forged["new_sources"][0]["source_section_id"] = json!("more");
    assert_eq!(
        notebook::apply(&workspace, &forged, "TEST")
            .unwrap_err()
            .code,
        "INVALID_ARGUMENT"
    );
    let mut invalid = command.clone();
    invalid["operations"]
        .as_array_mut()
        .unwrap()
        .push(json!({"type":"remove_entry","entry_id":"absent"}));
    assert_eq!(
        notebook::apply(&workspace, &invalid, "TEST")
            .unwrap_err()
            .code,
        "INVALID_ARGUMENT"
    );
    let before = workspace
        .read_consistent(|db| notebook::read(db, &json!({"plan_line_id":plan_id})))
        .unwrap();
    assert_eq!(before["format_version"], 1);
    assert_eq!(before["entries"].as_array().unwrap().len(), 1);
    let result = notebook::apply(&workspace, &command, "TEST").unwrap();
    assert_eq!(result["version"], 2);
    assert_eq!(
        notebook::apply(&workspace, &command, "TEST").unwrap(),
        result
    );
    assert_eq!(
        notebook::save_blocks(&workspace, &legacy, "TEST").unwrap(),
        legacy_receipt
    );
    let page = workspace
        .read_consistent(|db| {
            notebook::read(
                db,
                &json!({"plan_line_id":plan_id,"entry_ids":["with-citation"],"expected_version":2}),
            )
        })
        .unwrap();
    assert_eq!(page["sources"][0], result["sources"][0]);
    assert_eq!(page["citations"][0]["state"], "ORIGINAL");
    let mut stale = command.clone();
    stale["idempotency_key"] = json!("other-window");
    stale["new_sources"] = Value::Array(vec![]);
    assert_eq!(
        notebook::apply(&workspace, &stale, "TEST")
            .unwrap_err()
            .code,
        "VERSION_CONFLICT"
    );
}
