use std::{fs, path::PathBuf};

use serde_json::{json, Value};
use studyflow_core::{
    application::course_publication::{apply_update, import_package, preview_update},
    courses::catalog,
    infrastructure::config::Settings,
    planning,
    workspace::Workspace,
};

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> (Self, Workspace) {
        let root =
            std::env::temp_dir().join(format!("studyflow-publication-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let ws = Workspace::new(Settings {
            database: root.join(".studyflow/studyflow.db"),
            workspace: root.clone(),
        });
        ws.upgrade().unwrap();
        planning::create_plan(&mut ws.open().unwrap().connection, "Test plan", 1).unwrap();
        (Self(root), ws)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn package() -> Value {
    json!({"schema":"studyflow.course-package/1","package_id":"immutable-sample","plan_line":"Test plan",
        "course":{"title":"Sample"},"lessons":[{"id":"intro","title":"Intro","blocks":[{"id":"start","type":"concept","title":"Start","body":"Plain **sentence**."}]}]})
}

#[test]
fn release_and_revision_keep_order_ids_and_old_source() {
    let (_fixture, workspace) = Fixture::new();
    let initial = package();
    let imported = import_package(&workspace, &initial).unwrap();
    let id = imported["course_id"].as_str().unwrap();
    let first_path = workspace
        .settings()
        .workspace
        .join(imported["paths"][0].as_str().unwrap());
    let original_bytes = fs::read(&first_path).unwrap();
    let mut next = initial.clone();
    next["lessons"][0]["title"] = json!("Revised intro");
    let preview = preview_update(&workspace, id, &next, 1).unwrap();
    let token = preview["preview_hash"].as_str().unwrap();
    assert_eq!(preview["changed_lessons"], json!(["intro"]));
    assert_eq!(
        apply_update(&workspace, id, &next, 1, &"0".repeat(64), "wrong-preview")
            .unwrap_err()
            .code,
        "PREVIEW_CHANGED"
    );
    let applied = apply_update(&workspace, id, &next, 1, token, "revision-two").unwrap();
    assert_eq!(
        apply_update(&workspace, id, &next, 1, token, "revision-two").unwrap(),
        applied
    );
    assert_eq!(
        preview_update(&workspace, id, &next, 1).unwrap_err().code,
        "VERSION_CONFLICT"
    );
    assert_eq!(fs::read(first_path).unwrap(), original_bytes);
    let db = workspace.inspect().unwrap();
    let detail = catalog::detail(&db, &workspace.settings().workspace, id).unwrap();
    assert_eq!(detail["lessons"][0]["title"], "Revised intro");
    assert_eq!(detail["lessons"][0]["id"], imported["lesson_ids"][0]);
    assert_eq!(import_package(&workspace, &initial).unwrap()["revision"], 1);
    assert_eq!(import_package(&workspace, &next).unwrap()["revision"], 2);
}

#[test]
fn file_conflict_rolls_back_membership_and_document_rows() {
    let (_fixture, workspace) = Fixture::new();
    let mut next = package();
    let mut second = next["lessons"][0].clone();
    second["id"] = json!("second");
    next["lessons"].as_array_mut().unwrap().push(second);
    let digest = studyflow_core::courses::packages::inspect(&next).unwrap()["content_hash"]
        .as_str()
        .unwrap()
        .to_owned();
    let folder = workspace
        .settings()
        .workspace
        .join("content/course-packages/immutable-sample")
        .join(digest);
    fs::create_dir_all(&folder).unwrap();
    let conflict = folder.join("second.md");
    fs::write(&conflict, b"existing").unwrap();
    assert_eq!(
        import_package(&workspace, &next).unwrap_err().code,
        "COURSE_PACKAGE_FILE_CONFLICT"
    );
    let db = workspace.inspect().unwrap();
    let counts: (i64,i64,i64)=db.query_row("SELECT (SELECT COUNT(*) FROM courses),(SELECT COUNT(*) FROM plan_course_items),(SELECT COUNT(*) FROM documents)",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).unwrap();
    assert_eq!(counts, (0, 0, 0));
    assert_eq!(fs::read(&conflict).unwrap(), b"existing");
    fs::rename(&conflict, folder.join("second.preserved")).unwrap();
    assert_eq!(
        import_package(&workspace, &next).unwrap()["knowledge_total"],
        2
    );
}
