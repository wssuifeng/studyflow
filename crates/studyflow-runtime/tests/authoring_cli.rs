use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{SystemTime, UNIX_EPOCH},
};

const CLI: &str = env!("CARGO_BIN_EXE_studyflow");

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let clock = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("studyflow-author-{}-{clock}", std::process::id()));
        fs::create_dir(&root).unwrap();
        fs::create_dir(root.join("materials")).unwrap();
        Self(root)
    }

    fn cli(&self, args: &[&str]) -> Output {
        Command::new(CLI)
            .args(args)
            .current_dir(&self.0)
            .env_remove("STUDYFLOW_DATABASE_PATH")
            .env_remove("STUDYFLOW_DATABASE_URL")
            .env("STUDYFLOW_WORKSPACE", self.0.join("learner"))
            .output()
            .expect("native CLI started")
    }

    fn author(&self, args: &[&str], expected: i32) -> Value {
        let output =
            self.cli(&[&["authoring-workspace", "--root", "materials"][..], args].concat());
        assert_eq!(output.status.code(), Some(expected), "{args:?}: {output:?}");
        serde_json::from_slice(&output.stdout).unwrap()
    }

    fn write(&self, path: &str, value: &Value) {
        fs::write(self.0.join("materials").join(path), value.to_string()).unwrap();
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn material_workflow_keeps_immutable_outputs_receipts_and_cursor_scope() {
    let fixture = Fixture::new();
    let root = fixture.0.join("materials");
    fs::write(
        root.join("基础.tsv"),
        "\u{feff}word\t音标\t释义\t来源\r\nＳｔｒａßｅ\t\t道路\t来源\r\nread\t\t读取\t来源\r\n",
    )
    .unwrap();
    let source = "base=基础.tsv";
    let browse = [
        "query",
        "--source",
        source,
        "--browse",
        "--purpose",
        "fixture",
        "--limit",
        "1",
    ];
    let page = fixture.author(&browse, 0);
    let cursor = page["next_cursor"].as_str().unwrap();
    let next = fixture.author(&[&browse[..], &["--cursor", cursor]].concat(), 0);
    assert_eq!(next["items"][0]["word"], "read");
    let selected = fixture.author(&["query", "--source", source, "--word", "STRASSE"], 0);
    assert_eq!(selected["items"][0]["word"], "Ｓｔｒａßｅ");
    fixture.write("recipe.json", &json!({"format":1,"selection_id":"fixture","revision":1,"stage_id":"stage","objective":"目的",
        "sources":page["sources"],"items":[{"entry_id":page["items"][0]["entry_id"],"meaning_verified":true,"role":"new","sense":"道路","reason":"练习"}]}));
    let select = [
        "select",
        "--recipe",
        "recipe.json",
        "--output",
        "selections/s1",
    ];
    assert_eq!(fixture.author(&select, 0)["created"], true);
    assert_eq!(fixture.author(&select, 0)["created"], false);
    fixture.write(
        "receipt.json",
        &json!({"ok":true,"course":{"id":"example","content_revision":1}}),
    );
    let link = [
        "link",
        "--selection",
        "selections/s1",
        "--receipt",
        "receipt.json",
        "--course",
        "example",
        "--content-revision",
        "1",
    ];
    assert_eq!(fixture.author(&link, 0)["replayed"], false);
    assert_eq!(fixture.author(&link, 0)["replayed"], true);
    let coverage = [
        "coverage",
        "--source",
        source,
        "--selections-dir",
        "selections",
    ];
    assert_eq!(fixture.author(&coverage, 0)["sources"][0]["remaining"], 1);
    fixture.write(
        "receipt.json",
        &json!({"ok":true,"course":{"id":"example","content_revision":2}}),
    );
    assert_eq!(
        fixture.author(&coverage, 1)["error"]["code"],
        "RECEIPT_CHANGED"
    );
    fs::write(
        root.join("基础.tsv"),
        "word\tphonetic\tmeaning\torigin\nnew\t\t新\t合成\n",
    )
    .unwrap();
    assert_eq!(
        fixture.author(&[&browse[..], &["--cursor", cursor]].concat(), 1)["error"]["code"],
        "CURSOR_MISMATCH"
    );
    assert_eq!(
        fixture.author(
            &[
                "query",
                "--source",
                "other=../outside.tsv",
                "--word",
                "read"
            ],
            1
        )["error"]["code"],
        "PATH_BOUNDARY"
    );
    assert!(!fixture.0.join("learner").exists());
}

#[test]
fn audit_and_doctor_keep_their_read_only_boundaries() {
    let fixture = Fixture::new();
    let root = fixture.0.join("materials");
    fs::write(root.join("state.md"), "[index](index.md)\n").unwrap();
    fs::write(root.join("index.md"), "[missing](no.md)\n").unwrap();
    fixture.write("stage.json", &json!({"stage_id":"fixture","exit_criteria":["one"],"excluded":[],"objectives":[{"id":"A"}],"next_stage":null}));
    fixture.write("config.json", &json!({"format":1,"current_stage_id":"fixture","state_file":"state.md","stage_file":"stage.json","index_file":"index.md"}));
    assert_eq!(
        fixture.author(&["audit", "--config", "config.json"], 1)["issues"],
        json!([{"code":"BROKEN_LINK","path":"index.md"}])
    );
    let doctor = fixture.cli(&["doctor", "--format", "json"]);
    assert!(doctor.status.success(), "{doctor:?}");
    let result: Value = serde_json::from_slice(&doctor.stdout).unwrap();
    assert_eq!(result["database"]["status"], "not_initialized");
    assert!(!fixture.0.join("learner").exists());
    let init = fixture.cli(&["init"]);
    assert!(init.status.success(), "{init:?}");
    assert!(String::from_utf8_lossy(&init.stdout).contains("created: True"));
    assert!(String::from_utf8_lossy(&fixture.cli(&["init"]).stdout).contains("created: False"));
    let output = fixture.cli(&["call", "--method", "system.doctor"]);
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["database"]["status"], "ready");
    assert_eq!(result["healthy"], true);
    assert!(fixture
        .0
        .join(Path::new("learner/content/lessons/java-reference.md"))
        .is_file());
}
