use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

const CLI: &str = env!("CARGO_BIN_EXE_studyflow");

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let clock = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("studyflow-contract-{}-{clock}", std::process::id()));
        fs::create_dir(&root).unwrap();
        Self(root)
    }

    fn cli(&self, args: &[&str]) -> Output {
        Command::new(CLI)
            .args(args)
            .current_dir(&self.0)
            .env_remove("STUDYFLOW_DATABASE_PATH")
            .env_remove("STUDYFLOW_DATABASE_URL")
            .env("STUDYFLOW_WORKSPACE", self.0.join("workspace"))
            .output()
            .expect("native CLI started")
    }

    fn payload(&self, method: &str, params: Value, filename: &str, bom: bool) -> Output {
        let mut bytes = if bom {
            b"\xef\xbb\xbf".to_vec()
        } else {
            Vec::new()
        };
        bytes.extend(serde_json::to_vec(&params).unwrap());
        fs::write(self.0.join(filename), bytes).unwrap();
        self.cli(&["call", "--method", method, "--file", filename])
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn read(output: &Output) -> Value {
    serde_json::from_slice(&output.stdout).unwrap()
}
fn error(output: &Output) -> Value {
    serde_json::from_slice(&output.stderr).unwrap()
}

#[test]
fn doctor_recognizes_an_empty_writable_workspace_without_initializing_it() {
    let fixture = Fixture::new();
    let workspace = fixture.0.join("workspace");
    fs::create_dir(&workspace).unwrap();
    let result = read(&fixture.cli(&["doctor", "--format", "json"]));
    assert_eq!(result["healthy"], true);
    assert_eq!(result["database"]["status"], "not_initialized");
    assert_eq!(result["database"]["writable"], true);
    assert!(workspace.read_dir().unwrap().next().is_none());
}

#[test]
fn discovery_is_read_only_and_reports_registered_methods() {
    let fixture = Fixture::new();
    let output = fixture.cli(&["capabilities", "--format", "json"]);
    assert!(output.status.success());
    let capabilities = read(&output);
    assert_eq!(capabilities["workspace"]["exists"], false);
    assert_eq!(capabilities["database"]["driver"], "sqlite");
    let records = capabilities["capabilities"].as_array().unwrap();
    let supplied: Vec<_> = capabilities["engine_capabilities"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|row| row["method"].as_str())
        .collect();
    for method in [
        "system.version",
        "system.capabilities",
        "system.schema",
        "system.installation",
        "workspace.export",
        "workspace.validate",
        "workspace.restore",
    ] {
        assert!(supplied.contains(&method));
    }
    for name in ["engine_call", "workspace_import", "plan_detail", "doctor"] {
        assert!(records
            .iter()
            .any(|row| row["name"] == name && row["command"].is_string()));
    }
    assert!(records.iter().all(|row| row.get("method").is_none()));
    let discovery = read(&fixture.cli(&["call", "--method", "system.capabilities"]));
    assert_eq!(
        capabilities["engine_capabilities"],
        discovery["capabilities"]
    );
    assert!(records
        .iter()
        .any(|row| row["name"] == "course_quality_check"
            && row["command"]
                .as_str()
                .is_some_and(|command| command.contains("quality-check"))));
    let info = fixture.cli(&["call", "--method", "system.installation"]);
    assert!(info.status.success());
    let info = read(&info);
    assert_eq!(info["workspace_exists"], false);
    assert_eq!(info["agent_ready"], false);
    let cli_parent = Path::new(CLI).parent().unwrap();
    let bundled = cli_parent.join("studyflow-agent/SKILL.md").is_file();
    let has_source = !bundled
        && cli_parent.ancestors().any(|path| {
            path.join("crates/studyflow-runtime/Cargo.toml").is_file()
                && path.join("skills").is_dir()
        });
    assert_eq!(
        info["skill_kind"],
        if has_source {
            "repository"
        } else {
            "installed"
        }
    );
    assert_eq!(info["skill_available"], bundled || has_source);
    assert!(
        read(&fixture.cli(&["version", "--format", "json"]))["capabilities"]
            .as_array()
            .unwrap()
            .len()
            == records.len() - 1
    );
    assert!(fixture.0.read_dir().unwrap().next().is_none());
}

#[test]
fn bom_envelope_and_error_channels_keep_old_exit_conventions() {
    let fixture = Fixture::new();
    let schema = fixture.payload(
        "system.schema",
        json!({"method":"workspace.restore"}),
        "schema.json",
        true,
    );
    assert!(schema.status.success());
    assert_eq!(
        read(&schema)["methods"]["workspace.restore"]["required"],
        json!(["path", "target_root"])
    );
    let extra = fixture.payload(
        "workspace.validate",
        json!({"path":"missing.zip","extra":true}),
        "extra.json",
        true,
    );
    assert_eq!(extra.status.code(), Some(1));
    assert!(extra.stdout.is_empty());
    assert_eq!(error(&extra)["error_code"], "INVALID_ARGUMENT");
    let missing = fixture.payload(
        "workspace.validate",
        json!({"path":"missing.zip"}),
        "file.json",
        false,
    );
    assert_eq!(missing.status.code(), Some(1));
    assert!(missing.stderr.is_empty());
    assert_eq!(read(&missing)["error_code"], "BACKUP_NOT_FOUND");
    let unknown = fixture.payload(
        "system.schema",
        json!({"method":"course.study.open"}),
        "schema.json",
        false,
    );
    assert_eq!(unknown.status.code(), Some(1));
    assert_eq!(error(&unknown)["error_code"], "METHOD_NOT_FOUND");

    for (filename, bytes) in [
        ("invalid.json", vec![0xff]),
        ("large.json", vec![b' '; 4 * 1024 * 1024 + 1]),
        ("array.json", b"[]".to_vec()),
    ] {
        fs::write(fixture.0.join(filename), bytes).unwrap();
        let result = fixture.cli(&["call", "--method", "system.schema", "--file", filename]);
        assert_eq!(result.status.code(), Some(1));
        assert!(result.stdout.is_empty());
        assert_eq!(error(&result)["error_code"], "INVALID_ARGUMENT");
    }
}

#[test]
fn rust_request_schemas_match_vue_archive_types() {
    let fixture = Fixture::new();
    let output = fixture.cli(&["call", "--method", "system.schema"]);
    assert!(output.status.success());
    let schema = read(&output);
    let methods = schema["methods"].as_object().unwrap();
    let typescript = include_str!("../../../apps/desktop/src/shared/api/contracts/workspace.ts");
    let block = typescript
        .split_once("export type WorkspaceArchiveRequests = {")
        .unwrap()
        .1;
    let mut actual = block
        .split_once('\n')
        .unwrap()
        .1
        .lines()
        .take_while(|line| *line != "}")
        .collect::<Vec<_>>();
    actual.sort_unstable();
    let mut expected = methods
        .iter()
        .filter(|(method, _)| method.starts_with("workspace."))
        .map(|(method, definition)| {
            let props = definition["properties"].as_object().unwrap();
            let required = definition["required"].as_array().unwrap();
            let fields = props
                .iter()
                .map(|(key, value)| {
                    let field_type = value["type"].as_str().unwrap();
                    let optional = if required.contains(&json!(key)) {
                        ""
                    } else {
                        "?"
                    };
                    format!("{key}{optional}: {field_type}")
                })
                .collect::<Vec<_>>()
                .join("; ");
            format!("  '{method}': {{ {fields} }}")
        })
        .collect::<Vec<_>>();
    expected.sort_unstable();
    assert_eq!(actual, expected);
}

#[test]
fn archive_dispatch_uses_shared_services_and_protects_active_workspace() {
    let fixture = Fixture::new();
    assert!(fixture
        .cli(&["db-upgrade", "--format", "json"])
        .status
        .success());
    let export = fixture.payload(
        "workspace.export",
        json!({"path":"archive.studyflow"}),
        "request.json",
        false,
    );
    assert!(export.status.success());
    assert!(fixture.0.join("archive.studyflow").is_file());
    let restore = |target: &Path| {
        fixture.payload(
            "workspace.restore",
            json!({"path":"archive.studyflow","target_root":target}),
            "request.json",
            false,
        )
    };
    let active = restore(Path::new("workspace"));
    assert_eq!(active.status.code(), Some(1));
    assert_eq!(
        read(&active)["error_code"],
        "ACTIVE_WORKSPACE_RESTORE_FORBIDDEN"
    );
    let other = restore(Path::new("恢复目录"));
    assert!(other.status.success());
    assert!(fixture.0.join("恢复目录/.studyflow/studyflow.db").is_file());
}

#[test]
fn resolves_packaged_cli_and_rejects_invalid_agent_pointers() {
    use studyflow_core::infrastructure::installation;
    let fixture = Fixture::new();
    let binaries = fixture.0.join("package/binaries");
    let skill = binaries.join("studyflow-agent/SKILL.md");
    fs::create_dir_all(skill.parent().unwrap()).unwrap();
    fs::write(skill, "test").unwrap();
    let cli = binaries.join(format!("studyflow{}", std::env::consts::EXE_SUFFIX));
    fs::write(&cli, "test").unwrap();
    let workspace = fixture.0.join("workspace");
    fs::create_dir(&workspace).unwrap();
    let pointer = fixture.0.join("workspace.json");
    let inspect = || {
        serde_json::to_value(installation::inspect(&cli, &workspace, Some(&pointer)).unwrap())
            .unwrap()
    };
    let missing = inspect();
    assert_eq!(
        fs::canonicalize(missing["cli_path"].as_str().unwrap()).unwrap(),
        fs::canonicalize(&cli).unwrap()
    );
    assert_eq!(missing["skill_kind"], "installed");
    assert_eq!(missing["agent_ready"], true);
    assert_eq!(missing["agent_workspace_entry_status"], "missing");
    let agent = fixture.0.join("协作目录");
    fs::create_dir(&agent).unwrap();
    fs::write(agent.join("AGENTS.md"), "test").unwrap();
    fs::write(
        &pointer,
        format!("\u{feff}{}", json!({"format":1,"agent_workspace":agent})),
    )
    .unwrap();
    assert_eq!(inspect()["agent_workspace_entry_status"], "found");
    for value in [
        json!({"format":1,"agent_workspace":workspace}),
        json!({"format":1,"agent_workspace":"relative"}),
        json!({"format":true,"agent_workspace":agent}),
    ] {
        fs::write(&pointer, value.to_string()).unwrap();
        assert_eq!(inspect()["agent_workspace_entry_status"], "invalid");
    }
    fs::write(&pointer, vec![b' '; 16_385]).unwrap();
    assert_eq!(inspect()["agent_workspace_entry_status"], "invalid");
}
