use std::{fs::File, io::Read, path::Path, process::ExitCode};

use serde_json::{json, Value};
use studyflow_core::{
    courses::packages, documents, infrastructure::config::Settings, workspace::Workspace,
};

use crate::{
    author,
    registry::{Method, Params},
    ApiError,
};

const MAX_FILE: u64 = 4 * 1024 * 1024;
pub const USAGE: &str = "Usage: studyflow [--show-completion|--install-completion [powershell|pwsh]]\n       studyflow call --method <method> [--file <json>] [--format text|json]\n       studyflow version|capabilities|doctor [--format text|json]\n       studyflow init\n       studyflow db-upgrade [--format text|json]\n       studyflow plan|task|today|status|snapshot --help\n       studyflow workspace --help\n       studyflow authoring-workspace --help\n       studyflow document read|check --path <markdown> [--format text|json]\n       studyflow course import|import-package|validate-package|quality-check --file <json> [--format text|json]";

pub fn call(args: impl Iterator<Item = String>) -> ExitCode {
    let parsed = parse(
        args,
        &[("--method", true), ("--file", false), ("--format", false)],
    );
    let (mut options, format) = match parsed {
        ParseResult::Valid(options, format) => (options, format.unwrap_or(true)),
        ParseResult::Help => return help(),
        ParseResult::Invalid => return usage_error(),
    };
    let name = options.remove("--method").expect("required option");
    let filename = options.remove("--file");
    let params = match read_params(filename.as_deref()) {
        Ok(params) => params,
        Err(error) => return preflight_error(error),
    };
    invoke(&name, &params, format, false)
}

pub fn initialize(mut args: impl Iterator<Item = String>) -> ExitCode {
    match args.next().as_deref() {
        None => {}
        Some("--help") if args.next().is_none() => return help(),
        _ => return usage_error(),
    }
    match Settings::from_env().and_then(|settings| {
        studyflow_core::application::demo::initialize(&Workspace::new(settings))
    }) {
        Ok(result) => {
            println!("ok: True");
            println!(
                "created: {}",
                if result["created"] == true {
                    "True"
                } else {
                    "False"
                }
            );
            for key in ["plan_line_id", "task_id", "course_id", "exercise_id"] {
                if let Some(value) = result[key].as_str() {
                    println!("{key}: {value}");
                }
            }
            ExitCode::SUCCESS
        }
        Err(error) => preflight_error(error.into()),
    }
}

pub fn discovery(name: &str, args: impl Iterator<Item = String>) -> ExitCode {
    match parse(args, &[("--format", false)]) {
        ParseResult::Valid(_, format) => {
            invoke(name, &Params::new(), format.unwrap_or(false), true)
        }
        ParseResult::Help => help(),
        ParseResult::Invalid => usage_error(),
    }
}

pub fn course(mut args: impl Iterator<Item = String>) -> ExitCode {
    match args.next().as_deref() {
        Some("reset-learning") => return crate::maintenance_cli::execute("reset-learning", args),
        Some(action @ ("notes-get" | "notes-save")) => {
            return crate::notebook_cli::execute(action, args)
        }
        Some(action @ ("study-open" | "study-detail" | "answers")) => {
            return crate::learning_cli::course(action, args)
        }
        Some(
            action @ ("list" | "detail" | "readback-check" | "update-preview" | "update-apply"),
        ) => return crate::course::execute(action, args),
        Some("import-package") => return crate::course::import(args, true),
        Some("import") => return crate::course::import(args, false),
        Some("validate-package") => {}
        Some("quality-check") => return author::quality_check(args),
        Some("--help") | None => return help(),
        _ => return usage_error(),
    }
    let (options, as_json) = match parse(args, &[("--file", true), ("--format", false)]) {
        ParseResult::Valid(options, format) => (options, format.unwrap_or(false)),
        ParseResult::Help => return help(),
        ParseResult::Invalid => return usage_error(),
    };
    let path = Path::new(&options["--file"]);
    if !path.is_file() {
        return usage_error();
    }
    match packages::read(path).and_then(|package| packages::inspect(&package)) {
        Ok(mut receipt) => {
            receipt["ok"] = json!(true);
            display(receipt, as_json);
            ExitCode::SUCCESS
        }
        Err(error) => preflight_error(error.into()),
    }
}

pub fn document(mut args: impl Iterator<Item = String>) -> ExitCode {
    let action = match args.next().as_deref() {
        Some("read") => "read",
        Some("check") => "check",
        None | Some("--help") => return help(),
        _ => return usage_error(),
    };
    let (options, as_json) = match parse(args, &[("--path", true), ("--format", false)]) {
        ParseResult::Valid(options, format) => (options, format.unwrap_or(false)),
        ParseResult::Help => return help(),
        ParseResult::Invalid => return usage_error(),
    };
    let path = &options["--path"];
    let result = (|| -> Result<Value, ApiError> {
        let workspace = Workspace::new(Settings::from_env()?);
        if action == "read" {
            return Ok(json!(documents::read(
                &workspace.settings().workspace,
                path,
                true
            )?));
        }
        let active = workspace.open()?;
        Ok(json!(documents::check(
            &workspace.settings().workspace,
            &active.connection,
            path,
        )?))
    })();
    match result {
        Ok(mut value) => {
            value["ok"] = json!(true);
            display(value, as_json);
            ExitCode::SUCCESS
        }
        Err(error) => preflight_error(error),
    }
}
fn invoke(name: &str, params: &Params, as_json: bool, named: bool) -> ExitCode {
    if name == "study.status" {
        return preflight_error(ApiError::missing_method(name));
    }
    let Some(method) = Method::from_name(name) else {
        return preflight_error(ApiError::missing_method(name));
    };
    if let Err(error) = method.validate(params) {
        return preflight_error(error);
    }
    match method.execute(params) {
        Ok(mut value) => {
            if named {
                write_named_capabilities(name, &mut value);
            }
            value["ok"] = Value::Bool(true);
            display(value, as_json);
            ExitCode::SUCCESS
        }
        Err(error) if name == "system.schema" => preflight_error(error),
        Err(error) => {
            let mut payload = error.payload();
            payload["ok"] = Value::Bool(false);
            display(payload, as_json);
            ExitCode::FAILURE
        }
    }
}

pub(crate) const AUTHOR_COMMANDS: &[(&str, &str, &str)] = &[
    (
        "course_package_import",
        "studyflow course import-package --file <package.json> --format json",
        "write",
    ),
    (
        "course_readback_check",
        "studyflow course readback-check --course <course-id> --plan-line <plan-id> --format json",
        "read",
    ),
    (
        "course_package_validate",
        "studyflow course validate-package --file <package.json> --format json",
        "read",
    ),
    (
        "course_quality_check",
        "studyflow course quality-check --file <package.json> --format json",
        "read",
    ),
];

const NAMED_COMMANDS: &[(&str, &str, &str)] = &[
    ("plan_detail", "studyflow plan detail --id <id> --format json", "read"),
    ("document_read", "studyflow document read --path <path> --format json", "read"),
    ("version", "studyflow version --format json", "read"),
    ("capabilities", "studyflow capabilities --format json", "read"),
    ("doctor", "studyflow doctor --format json", "diagnostic"),
    ("today", "studyflow today --format json", "read"),
    ("course_import", "studyflow course import --file <path> --format json", "write"),
    ("course_update_preview", "studyflow course update-preview --id <course-id> --file <package.json> --expected-revision <revision> --format json", "read"),
    ("course_update_apply", "studyflow course update-apply --id <course-id> --file <package.json> --expected-revision <revision> --preview-hash <hash> --idempotency-key <key> --format json", "write"),
    ("course_detail", "studyflow course detail --id <course-id> --format json", "read"),
    ("snapshot_generate", "studyflow snapshot generate --format json", "write"),
    ("workspace_export", "studyflow workspace export --output <backup.zip> --format json", "write"),
    ("workspace_import", "studyflow workspace import --file <backup.zip> --target <workspace-dir> --format json", "write"),
];

fn named_commands() -> impl Iterator<Item = &'static (&'static str, &'static str, &'static str)> {
    AUTHOR_COMMANDS
        .iter()
        .chain(NAMED_COMMANDS)
        .chain(crate::learning_cli::COMMANDS)
        .chain(crate::notebook_cli::COMMANDS)
        .chain(crate::review_cli::COMMANDS)
        .chain(crate::maintenance_cli::COMMANDS)
        .chain(crate::authoring_cli::capabilities())
}

fn write_named_capabilities(method: &str, value: &mut Value) {
    if method == "system.capabilities" {
        value["engine_capabilities"] = value["capabilities"].take();
        let records = named_commands()
            .map(|(name, command, kind)| json!({"name": name, "command": command, "kind": kind}))
            .chain(std::iter::once(json!({
                "name": "engine_call", "command": "call --method <method> --file <json> --format json", "kind": "transport"
            })))
            .collect::<Vec<_>>();
        value["capabilities"] = json!(records);
    } else {
        value["capabilities"] = json!(named_commands()
            .map(|(name, _, _)| name)
            .collect::<Vec<_>>());
    }
}

fn read_params(filename: Option<&str>) -> Result<Params, ApiError> {
    let Some(filename) = filename else {
        return Ok(Params::new());
    };
    let file = File::open(filename)
        .map_err(|_| ApiError::invalid_argument("找不到可读的 JSON 请求文件。"))?;
    let mut data = Vec::new();
    file.take(MAX_FILE + 1)
        .read_to_end(&mut data)
        .map_err(|_| ApiError::invalid_argument("无法读取 JSON 请求文件。"))?;
    if data.len() as u64 > MAX_FILE {
        return Err(ApiError::invalid_argument("JSON 请求超过 4 MiB。"));
    }
    let bytes = data.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&data);
    let value: Value = serde_json::from_slice(bytes)
        .map_err(|_| ApiError::invalid_argument("call 请求必须是有效的 UTF-8 JSON。"))?;
    match value {
        Value::Object(params) => Ok(params),
        _ => Err(ApiError::invalid_argument(
            "call 请求参数必须是 JSON 对象。",
        )),
    }
}

pub(crate) enum ParseResult {
    Valid(std::collections::BTreeMap<String, String>, Option<bool>),
    Help,
    Invalid,
}

pub(crate) fn parse(args: impl Iterator<Item = String>, available: &[(&str, bool)]) -> ParseResult {
    parse_with_empty(args, available, None)
}

pub(crate) fn parse_with_empty(
    mut args: impl Iterator<Item = String>,
    available: &[(&str, bool)],
    accept_empty: Option<&str>,
) -> ParseResult {
    let mut options = std::collections::BTreeMap::new();
    while let Some(arg) = args.next() {
        if arg == "--help" {
            return ParseResult::Help;
        }
        let (key, value) = arg
            .split_once('=')
            .map_or((arg.as_str(), None), |(key, val)| (key, Some(val)));
        if !available.iter().any(|(allowed, _)| *allowed == key) || options.contains_key(key) {
            return ParseResult::Invalid;
        }
        let value = value
            .map(str::to_owned)
            .or_else(|| args.next().filter(|val| !val.starts_with("--")));
        let Some(value) = value.filter(|val| !val.is_empty() || accept_empty == Some(key)) else {
            return ParseResult::Invalid;
        };
        options.insert(key.to_owned(), value);
    }
    if available
        .iter()
        .any(|(key, required)| *required && !options.contains_key(*key))
    {
        return ParseResult::Invalid;
    }
    let format = match options.remove("--format").as_deref() {
        Some("json") => Some(true),
        Some("text") => Some(false),
        Some(_) => return ParseResult::Invalid,
        None => None,
    };
    ParseResult::Valid(options, format)
}

pub fn help() -> ExitCode {
    println!("{USAGE}");
    ExitCode::SUCCESS
}

pub fn usage_error() -> ExitCode {
    eprintln!("{USAGE}");
    ExitCode::from(2)
}

pub(crate) fn preflight_error(error: ApiError) -> ExitCode {
    eprintln!(
        "{}",
        json!({"ok":false,"error_code":error.code,"message":error.message,"next_action":error.next_action})
    );
    ExitCode::FAILURE
}

pub(crate) fn display(value: Value, as_json: bool) {
    if as_json {
        println!("{value:#}");
    } else if let Some(fields) = value.as_object() {
        for (key, value) in fields {
            if let Some(text) = value.as_str() {
                println!("{key}: {text}");
            } else {
                println!("{key}: {value}");
            }
        }
    }
}
