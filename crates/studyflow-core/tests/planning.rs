use std::fs;

use serde_json::json;
use studyflow_core::{
    infrastructure::config::Settings,
    planning::{self, NewTask, PlanEdit},
    workspace::Workspace,
};

#[test]
fn edits_commit_once_and_task_filters_share_plan_identity() {
    let root = std::env::temp_dir().join(format!("studyflow-plan-{}", uuid::Uuid::new_v4()));
    let workspace = Workspace::new(Settings {
        database: root.join(".studyflow/studyflow.db"),
        workspace: root.clone(),
    });
    workspace.upgrade().unwrap();
    let mut active = workspace.open().unwrap();
    let db = &mut active.connection;
    let plan = planning::create_plan(db, "Main plan", 1).unwrap();
    let plan_id = plan["id"].as_str().unwrap();
    let date = planning::parse_date("2099-01-01").unwrap();
    let values = json!({"name":"Revised plan"});
    let edit = |expected_version, idempotency_key| PlanEdit {
        plan_line_id: plan_id,
        expected_version,
        idempotency_key,
        operation: "UPDATE",
        values: values.as_object().unwrap(),
    };
    let first = planning::edit_plan(db, edit(1, "plan-1")).unwrap();
    assert_eq!(planning::edit_plan(db, edit(1, "plan-1")).unwrap(), first);
    assert_eq!(
        planning::edit_plan(db, edit(1, "stale")).unwrap_err().code,
        "VERSION_CONFLICT"
    );
    let second = planning::edit_plan(db, edit(2, "plan-2")).unwrap();
    assert_eq!(second["version"], 3);
    planning::create_task(
        db,
        NewTask {
            title: "Read text",
            date,
            kind: "reading",
            description: "",
            plan: Some(plan_id),
            priority: 1,
        },
    )
    .unwrap();
    let task = planning::list_tasks(db, Some(date), Some(plan_id), Some("READING"), false).unwrap();
    assert_eq!(task[0]["plan_line"], "Revised plan");
    assert!(
        planning::list_tasks(db, Some(date), Some(plan_id), Some("REVIEW"), false)
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        planning::dashboard(db, date, Some(plan_id), Some("READING")).unwrap()["primary_task"],
        "Read text"
    );
    assert_eq!(planning::change_token(db).unwrap()["event_count"], 4);
    drop(active);
    fs::remove_dir_all(root).unwrap();
}
