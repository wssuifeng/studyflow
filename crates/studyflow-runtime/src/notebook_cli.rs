use std::{fs::File, io::Read, path::Path, process::ExitCode};

use serde_json::{json, Value};
use studyflow_core::{
    infrastructure::{file_paths, StorageError},
    learning::notebook as service,
};

use crate::{
    cli::{display, parse_with_empty, preflight_error, usage_error, ParseResult},
    planning::workspace,
    ApiError,
};

pub(crate) const COMMANDS: &[(&str, &str, &str)] = &[
    ("plan_notebook_get", "studyflow plan notebook-get --id <plan-id> --format json", "read"),
    ("plan_notebook_save", "studyflow plan notebook-save --id <plan-id> --file <blocks.json> --expected-version <n> --idempotency-key <key> --format json", "write"),
    ("plan_notebook_read", "studyflow plan notebook-read --id <plan-id> --format json", "read"),
    ("plan_notebook_apply", "studyflow plan notebook-apply --id <plan-id> --file <operations.json> --expected-version <n> --idempotency-key <key> --format json", "write"),
    ("course_notes_get", "studyflow course notes-get --study-id <study-id> --format json", "read"),
    ("course_notes_save", "studyflow course notes-save --study-id <study-id> --lesson-id <lesson-id> --file <path> --expected-version <n> --idempotency-key <key> --format json", "write"),
];

fn file_text(path: &Path, limit: u64, error: &'static str) -> Result<String, ApiError> {
    let file = File::open(path).map_err(|_| StorageError::new(error))?;
    let mut bytes = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| StorageError::new(error))?;
    if bytes.len() as u64 > limit {
        return Err(ApiError::invalid_argument("笔记输入文件超限。"));
    }
    String::from_utf8(bytes)
        .map(|data| {
            data.strip_prefix('\u{feff}')
                .unwrap_or(&data)
                .replace("\r\n", "\n")
                .replace('\r', "\n")
        })
        .map_err(|_| StorageError::new(error).into())
}

fn entries(args: impl Iterator<Item = String>) -> Result<(Vec<String>, Vec<String>), ApiError> {
    let mut args = args.peekable();
    let mut forwarded = Vec::new();
    let mut entries = Vec::new();
    while let Some(arg) = args.next() {
        if arg == "--entry" {
            let id = args
                .next_if(|next| !next.starts_with("--"))
                .ok_or_else(|| ApiError::invalid_argument("--entry 需要记录 ID。"))?;
            entries.push(id);
        } else if let Some(id) = arg.strip_prefix("--entry=") {
            if id.is_empty() {
                return Err(ApiError::invalid_argument("--entry 需要记录 ID。"));
            }
            entries.push(id.into());
        } else {
            forwarded.push(arg);
        }
    }
    Ok((forwarded, entries))
}

pub(crate) fn execute(action: &str, args: impl Iterator<Item = String>) -> ExitCode {
    let args: Vec<_> = args.collect();
    if args.iter().any(|arg| arg == "--help") {
        let name = action.replace('-', "_");
        if let Some((_, usage, _)) = COMMANDS
            .iter()
            .find(|(command, _, _)| command.ends_with(&name))
        {
            println!("Usage: {usage}");
            if action == "notebook-read" {
                println!("  --course <id> --lesson <id> --entry <id> (repeatable) --query <text> --offset <n> --limit <n> --expected-version <n>");
            }
        }
        return ExitCode::SUCCESS;
    }
    let (args, entries) = if action == "notebook-read" {
        match entries(args.into_iter()) {
            Ok(parsed) => parsed,
            Err(_) => return usage_error(),
        }
    } else {
        (args, Vec::new())
    };
    let available: &[(&str, bool)] = match action {
        "notebook-get" => &[("--id", true), ("--format", false)],
        "notebook-read" => &[
            ("--id", true),
            ("--format", false),
            ("--course", false),
            ("--lesson", false),
            ("--query", false),
            ("--offset", false),
            ("--limit", false),
            ("--expected-version", false),
        ],
        "notebook-save" | "notebook-apply" => &[
            ("--id", true),
            ("--file", true),
            ("--idempotency-key", true),
            ("--expected-version", true),
            ("--format", false),
        ],
        "notes-get" => &[("--study-id", true), ("--format", false)],
        "notes-save" => &[
            ("--study-id", true),
            ("--lesson-id", true),
            ("--file", true),
            ("--idempotency-key", true),
            ("--expected-version", true),
            ("--format", false),
        ],
        _ => return usage_error(),
    };
    let ParseResult::Valid(options, format) =
        parse_with_empty(args.into_iter(), available, Some("--query"))
    else {
        return usage_error();
    };
    let mut input = json!({});
    for (option, key) in [
        ("--id", "plan_line_id"),
        ("--study-id", "study_session_id"),
        ("--lesson-id", "lesson_id"),
        ("--lesson", "lesson_id"),
        ("--course", "course_id"),
        ("--query", "query"),
        ("--idempotency-key", "idempotency_key"),
    ] {
        if let Some(value) = options.get(option) {
            input[key] = json!(value);
        }
    }
    for (option, key) in [
        ("--offset", "offset"),
        ("--limit", "limit"),
        ("--expected-version", "expected_version"),
    ] {
        if let Some(value) = options.get(option) {
            let Ok(value) = value.parse::<i64>() else {
                return usage_error();
            };
            input[key] = json!(value);
        }
    }
    if !entries.is_empty() {
        input["entry_ids"] = json!(entries);
    }
    let response = (|| {
        let workspace = workspace()?;
        let plan = input["plan_line_id"].as_str().unwrap_or_default();
        let study = input["study_session_id"].as_str().unwrap_or_default();
        match action {
            "notebook-get" => {
                return Ok(workspace.read_consistent(|db| service::get_blocks(db, plan))?)
            }
            "notebook-read" => {
                return Ok(workspace.read_consistent(|db| service::read(db, &input))?)
            }
            "notes-get" => {
                return Ok(workspace.read_consistent(|db| service::get_notes(db, study))?)
            }
            _ => {}
        }
        let path = file_paths::workspace_path(
            &workspace.settings().workspace,
            Path::new(&options["--file"]),
        )?;
        let suffix = path
            .extension()
            .and_then(|ext| ext.to_str())
            .map(str::to_ascii_lowercase)
            .unwrap_or_default();
        if action == "notes-save" {
            if !path.is_file() {
                return Err(StorageError::new("DOCUMENT_NOT_FOUND").into());
            }
            if !matches!(suffix.as_str(), "txt" | "md" | "markdown") {
                return Err(StorageError::new("UNSUPPORTED_DOCUMENT_TYPE").into());
            }
            input["text"] = json!(file_text(&path, 800_003, "DOCUMENT_UNREADABLE")?);
            return Ok(service::save_note(&workspace, &input, "AGENT_CLI")?);
        }
        let apply = action == "notebook-apply";
        if suffix != "json" || !path.is_file() {
            let error = if suffix != "json" && !apply {
                "UNSUPPORTED_DOCUMENT_TYPE"
            } else {
                "DOCUMENT_NOT_FOUND"
            };
            return Err(StorageError::new(error).into());
        }
        let payload: Value = serde_json::from_str(&file_text(
            &path,
            if apply { 8_000_000 } else { 5_000_000 },
            "INVALID_ARGUMENT",
        )?)
        .map_err(|_| ApiError::invalid_argument("笔记输入必须为 UTF-8 JSON。"))?;
        if apply {
            if !payload.as_object().is_some_and(|obj| {
                obj.keys()
                    .all(|key| matches!(key.as_str(), "operations" | "new_sources"))
            }) {
                return Err(ApiError::invalid_argument(
                    "仅允许 operations 和 new_sources 字段。",
                ));
            }
            input["operations"] = payload["operations"].clone();
            input["new_sources"] = payload["new_sources"].clone();
            Ok(service::apply(&workspace, &input, "AGENT_CLI")?)
        } else {
            input["blocks"] = if payload.is_object() {
                payload["blocks"].clone()
            } else {
                payload
            };
            Ok(service::save_blocks(&workspace, &input, "AGENT_CLI")?)
        }
    })();
    match response {
        Ok(mut result) => {
            result["ok"] = json!(true);
            display(result, format.unwrap_or(false));
            ExitCode::SUCCESS
        }
        Err(error) => preflight_error(error),
    }
}
