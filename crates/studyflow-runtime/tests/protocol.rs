use std::io::Write;
use std::process::{Command, Stdio};

use serde_json::{json, Value};

const CLI: &str = env!("CARGO_BIN_EXE_studyflow");
const ENGINE: &str = env!("CARGO_BIN_EXE_studyflow-engine");

fn engine_exchange(input: &[u8]) -> Vec<Value> {
    let mut child = Command::new(ENGINE)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("launch native engine");
    child.stdin.take().unwrap().write_all(input).unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

#[test]
fn version_flows_through_both_native_transports() {
    let result = Command::new(CLI)
        .args(["call", "--method", "system.version", "--format", "json"])
        .output()
        .unwrap();
    assert!(result.status.success());
    assert!(result.stderr.is_empty());
    let mut cli: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(cli.as_object_mut().unwrap().remove("ok"), Some(json!(true)));
    assert_eq!(cli["app_version"], studyflow_core::APP_VERSION);
    assert_eq!(cli["protocol_version"], "1.2");
    assert!(cli["capabilities"]
        .as_array()
        .unwrap()
        .contains(&json!("version")));

    let replies =
        engine_exchange(b"{\"id\":\"fixture-1\",\"method\":\"system.version\",\"params\":{}}\n");
    assert_eq!(
        replies,
        vec![json!({"id":"fixture-1","ok":true,"data":cli})]
    );
}

#[test]
fn engine_keeps_request_ids_and_continues_after_errors() {
    let requests = concat!(
        " \n",
        "{\"id\":1,\"method\":\"unknown\"}\r\n",
        "{\"id\":2,\"method\":\"system.version\",\"params\":[]}\n",
        "{garbled}\n",
        "{\"id\":\"版本\",\"method\":\"system.version\"}"
    );
    let replies = engine_exchange(requests.as_bytes());
    assert_eq!(replies.len(), 4);
    assert_eq!(replies[0]["id"], 1);
    assert_eq!(replies[0]["ok"], false);
    assert_eq!(replies[0]["error"]["code"], "METHOD_NOT_FOUND");
    assert_eq!(replies[1]["id"], 2);
    assert_eq!(replies[1]["error"]["error_code"], "INVALID_REQUEST");
    assert!(replies[2]["id"].is_null());
    assert_eq!(replies[2]["error"]["error_code"], "INVALID_REQUEST");
    assert_eq!(replies[3]["id"], "版本");
    assert_eq!(replies[3]["ok"], true);
}

#[test]
fn cli_domain_error_and_bad_arguments_keep_separate_exit_codes() {
    let missing = Command::new(CLI)
        .args(["call", "--method", "unknown", "--format", "json"])
        .output()
        .unwrap();
    assert_eq!(missing.status.code(), Some(1));
    assert!(missing.stdout.is_empty());
    let error: Value = serde_json::from_slice(&missing.stderr).unwrap();
    assert_eq!(error["ok"], false);
    assert_eq!(error["error_code"], "METHOD_NOT_FOUND");
    assert!(error.get("error").is_none());

    let invalid = Command::new(CLI).arg("call").output().unwrap();
    assert_eq!(invalid.status.code(), Some(2));
    assert!(invalid.stdout.is_empty());
    assert!(String::from_utf8(invalid.stderr)
        .unwrap()
        .contains("Usage:"));
}

#[test]
fn oversized_frames_are_rejected_and_the_next_request_survives() {
    use std::io::{BufReader, Cursor};
    let mut requests = vec![b'x'; 16 * 1024 * 1024 + 1];
    requests.extend(b"\n{\"id\":\"after oversized\",\"method\":\"system.schema\"}\n");
    let mut output = Vec::new();
    studyflow_runtime::serve_engine(BufReader::new(Cursor::new(requests)), &mut output).unwrap();
    let rows: Vec<Value> = String::from_utf8(output)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0]["error"]["code"], "INVALID_REQUEST");
    assert_eq!(rows[1]["id"], "after oversized");
    assert_eq!(rows[1]["ok"], true);
}

#[test]
fn managed_handshake_prepares_only_the_matching_native_workspace() {
    use std::{
        fs,
        time::{SystemTime, UNIX_EPOCH},
    };
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::temp_dir().join(format!("studyflow-managed-{stamp}"));
    let workspace = root.join("workspace");
    fs::create_dir(&root).unwrap();
    let launch = |version: &str| {
        let mut child = Command::new(ENGINE)
            .args(["--managed-desktop", version, "1.2"])
            .env("STUDYFLOW_WORKSPACE", &workspace)
            .env_remove("STUDYFLOW_DATABASE_PATH")
            .env_remove("STUDYFLOW_DATABASE_URL")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(b"{\"id\":\"managed\",\"method\":\"system.version\"}\n")
            .unwrap();
        let result = child.wait_with_output().unwrap();
        assert!(result.status.success());
        serde_json::from_slice::<Value>(&result.stdout).unwrap()
    };
    let mismatch = launch("0.0.0");
    assert_eq!(mismatch["error"]["code"], "ENGINE_VERSION_MISMATCH");
    assert!(!workspace.exists());
    let ready = launch(studyflow_core::APP_VERSION);
    assert_eq!(ready["id"], "managed");
    assert_eq!(ready["data"]["runtime"], "rust");
    assert!(workspace.join(".studyflow/studyflow.db").is_file());
    fs::remove_dir_all(root).unwrap();
}
