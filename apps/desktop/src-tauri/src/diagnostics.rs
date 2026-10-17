//! Bounded metadata-only UI diagnostics, independent of the Engine/database.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{fs::{self, OpenOptions}, io::Write, path::Path, sync::Mutex, time::{SystemTime, UNIX_EPOCH}};
use tauri::{AppHandle, Manager};

const MAX_LOG_BYTES: u64 = 256 * 1024;
static LOG_LOCK: Mutex<()> = Mutex::new(());
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct UiDiagnostic {
    event_id: String,
    context: String,
    code: String,
    #[serde(skip_serializing_if="Option::is_none")] operation: Option<String>,
    #[serde(skip_serializing_if="Option::is_none")] request_id: Option<String>,
    #[serde(skip_serializing_if="Option::is_none")] response_id: Option<String>,
}
fn token(value: &str, max: usize) -> bool {
    !value.is_empty() && value.len() <= max && value.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
}
fn append(directory: &Path, event: &UiDiagnostic) -> Result<Value, String> {
    if !token(&event.event_id, 80) || !token(&event.code, 64)
        || !matches!(event.context.as_str(), "english-training" | "english-retest" | "engine-response")
        || [&event.request_id, &event.response_id].iter().any(|v| v.as_ref().is_some_and(|s| !token(s, 80)))
        || event.operation.as_ref().is_some_and(|s| s.is_empty() || s.len() > 80 || !s.bytes().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_.-".contains(&c))) {
        return Err("INVALID_DIAGNOSTIC_METADATA".into());
    }
    let _guard = LOG_LOCK.lock().map_err(|_| "DIAGNOSTIC_LOCK_UNAVAILABLE".to_string())?;
    fs::create_dir_all(directory).map_err(|_| "DIAGNOSTIC_LOG_UNAVAILABLE".to_string())?;
    let path = directory.join("ui-diagnostics.jsonl");
    if let Ok(meta) = fs::symlink_metadata(&path) {
        if meta.file_type().is_symlink() {return Err("DIAGNOSTIC_LINK_REJECTED".into());}
        if meta.len() >= MAX_LOG_BYTES {
            let previous = directory.join("ui-diagnostics.previous.jsonl");
            if previous.exists() {fs::remove_file(&previous).map_err(|_| "DIAGNOSTIC_ROTATION_FAILED".to_string())?;}
            fs::rename(&path, &previous).map_err(|_| "DIAGNOSTIC_ROTATION_FAILED".to_string())?;
        }
    }
    let mut record = serde_json::to_value(event).map_err(|_| "INVALID_DIAGNOSTIC_METADATA".to_string())?;
    record["recorded_at_unix"] = json!(SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs());
    let mut line = serde_json::to_vec(&record).map_err(|_| "INVALID_DIAGNOSTIC_METADATA".to_string())?;
    line.push(b'\n');
    OpenOptions::new().create(true).append(true).open(path).and_then(|mut f| f.write_all(&line)).map_err(|_| "DIAGNOSTIC_LOG_UNAVAILABLE".to_string())?;
    Ok(json!({"ok":true,"diagnostic_id":event.event_id}))
}
#[tauri::command]
pub(super) fn record_ui_diagnostic(app: AppHandle, event: UiDiagnostic) -> Result<Value, String> {
    // An explicitly isolated desktop run keeps diagnostics with its other test artifacts.
    let directory = match std::env::var_os("STUDYFLOW_DIAGNOSTICS_DIR") {
        Some(value) => {
            let path = std::path::PathBuf::from(value);
            if !path.is_absolute() {return Err("INVALID_DIAGNOSTIC_DIRECTORY".into());}
            path
        }
        None => app.path().app_log_dir().map_err(|_| "DIAGNOSTIC_LOG_UNAVAILABLE".to_string())?,
    };
    append(&directory, &event)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn event() -> UiDiagnostic {serde_json::from_value(json!({"event_id":"ui-test-1","context":"english-training","code":"INVALID_RESPONSE"})).unwrap()}
    fn directory() -> std::path::PathBuf {
        let p=std::env::temp_dir().join(format!("studyflow-ui-log-{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
        fs::create_dir(&p).unwrap_or_else(|e| panic!("cannot create test directory {}: {}",p.display(),e));p
    }
    fn cleanup(p: &Path) {assert!(p.starts_with(std::env::temp_dir()));assert!(p.file_name().unwrap().to_string_lossy().starts_with("studyflow-ui-log-"));fs::remove_dir_all(p).unwrap();}
    #[test] fn metadata_only_log_survives_without_engine() {
        let d=directory();append(&d,&event()).unwrap();let r:Value=serde_json::from_str(fs::read_to_string(d.join("ui-diagnostics.jsonl")).unwrap().trim()).unwrap();
        assert_eq!(r["code"],"INVALID_RESPONSE");assert_eq!(r.as_object().unwrap().len(),4);cleanup(&d);
    }
    #[test] fn raw_payloads_and_invalid_paths_are_rejected() {
        assert!(serde_json::from_value::<UiDiagnostic>(json!({"event_id":"ui-test","context":"english-training","code":"FAIL","answer":"private"})).is_err());
        let d=directory();let mut e=event();e.context="../../outside".into();assert!(append(&d,&e).is_err());assert!(!d.join("ui-diagnostics.jsonl").exists());cleanup(&d);
    }
    #[test] fn log_rotates_at_bounded_size() {
        let d=directory();let p=d.join("ui-diagnostics.jsonl");fs::write(&p,vec![b'x';MAX_LOG_BYTES as usize]).unwrap();append(&d,&event()).unwrap();
        assert_eq!(fs::metadata(d.join("ui-diagnostics.previous.jsonl")).unwrap().len(),MAX_LOG_BYTES);assert!(fs::metadata(&p).unwrap().len()<1024);cleanup(&d);
    }
}
