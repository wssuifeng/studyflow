use std::{fs::File, io::Read, process::ExitCode};

use serde_json::{json, Value};
use studyflow_core::{infrastructure::StorageError, reviews};

use crate::{
    cli::{display, help, parse, preflight_error, usage_error, ParseResult},
    learning,
    planning::workspace,
    registry::Params,
    ApiError,
};

pub(crate) const COMMANDS: &[(&str,&str,&str)] = &[
    ("course_answers_get","studyflow course answers get --id <course-id> --format json","read"),
    ("course_answers_save","studyflow course answers save --id <course-id> --file <answers.json> --idempotency-key <key> --format json","write"),
    ("course_answers_submit","studyflow course answers submit --id <course-id> --file <answers.json> --idempotency-key <key> --format json","write"),
    ("course_study_open","studyflow course study-open --id <course-id> --idempotency-key <key> --format json","write"),
    ("course_study_get","studyflow course study-detail --study-id <study-id> --format json","read"),
    ("submission_get","studyflow submission get --id <submission-id> --format json","read"),
    ("submission_revise","studyflow submission revise --parent <id> --file <path> --format json","write"),
    ("submission_retest","studyflow submission retest --parent <id> --file <path> --format json","write"),
];

fn output(result: Result<Value, ApiError>, format: bool) -> ExitCode {
    match result {
        Ok(mut value) => {
            value.as_object_mut().unwrap().remove("protocol_version");
            value["ok"] = json!(true);
            display(value, format);
            ExitCode::SUCCESS
        }
        Err(error) => preflight_error(error),
    }
}

pub(crate) fn course(action: &str, mut args: impl Iterator<Item = String>) -> ExitCode {
    let lookups = &[("--id", true), ("--format", false)];
    let write_options = &[
        ("--id", true),
        ("--file", true),
        ("--idempotency-key", true),
        ("--format", false),
    ];
    let action = if action == "answers" {
        match args.next().as_deref() {
            Some("get") => "get",
            Some("save") => "save",
            Some("submit") => "submit",
            None | Some("--help") => return help(),
            _ => return usage_error(),
        }
    } else {
        action
    };
    let options: &[(&str, bool)] = match action {
        "study-open" => &[
            ("--id", true),
            ("--idempotency-key", true),
            ("--new-version", false),
            ("--format", false),
        ],
        "study-detail" => &[("--study-id", true), ("--format", false)],
        "get" => lookups,
        "save" | "submit" => write_options,
        _ => return usage_error(),
    };
    let args = args.map(|arg| {
        if action == "study-open" && arg == "--new-version" {
            "--new-version=true".into()
        } else {
            arg
        }
    });
    let (options, format) = match parse(args, options) {
        ParseResult::Valid(options, format) => (options, format.unwrap_or(false)),
        ParseResult::Help => return help(),
        ParseResult::Invalid => return usage_error(),
    };
    let result = match action {
        "study-open" => {
            let requested = options.get("--new-version");
            if requested.is_some_and(|value| value != "true") {
                return usage_error();
            }
            learning::open(json!({"course_id":options["--id"],"idempotency_key":options["--idempotency-key"],"new_version":requested.is_some()}).as_object().unwrap())
        }
        "study-detail" => learning::detail(
            json!({"study_session_id":options["--study-id"]})
                .as_object()
                .unwrap(),
        ),
        "get" => learning::answers(json!({"course_id":options["--id"]}).as_object().unwrap()),
        _ => (|| {
            let bytes = read_file(&options["--file"])?;
            let payload: Value =
                serde_json::from_slice(bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&bytes))
                    .map_err(|_| ApiError::invalid_argument("答案文件必须是 UTF-8 JSON。"))?;
            let (answers, study) = if payload.is_object() {
                (&payload["answers"], payload["study_session_id"].as_str())
            } else {
                (&payload, None)
            };
            if payload.is_object() && !payload["study_session_id"].is_null() && study.is_none() {
                return Err(ApiError::invalid_argument("study_session_id 必须是文本。"));
            }
            let params = json!({"course_id":options["--id"],"idempotency_key":options["--idempotency-key"],"source":"AGENT_CLI","study_session_id":study,"answers":answers});
            if action == "save" {
                learning::save_answers(params.as_object().unwrap())
            } else {
                learning::submit_answers(params.as_object().unwrap())
            }
        })(),
    };
    output(result, format)
}

pub fn submission(mut args: impl Iterator<Item = String>) -> ExitCode {
    let action = match args.next().as_deref() {
        Some("get") => "get",
        Some("list-pending") => "list-pending",
        Some("revise") => "revise",
        Some("retest") => "retest",
        None | Some("--help") => return help(),
        _ => return usage_error(),
    };
    let flags: &[(&str, bool)] = match action {
        "get" => &[("--id", true), ("--format", false)],
        "list-pending" => &[("--format", false)],
        _ => &[
            ("--parent", true),
            ("--file", true),
            ("--idempotency-key", false),
            ("--format", false),
        ],
    };
    let (options, format) = match parse(args, flags) {
        ParseResult::Valid(options, format) => (options, format.unwrap_or(false)),
        ParseResult::Help => return help(),
        ParseResult::Invalid => return usage_error(),
    };
    let result = (|| match action {
        "get" => {
            let mut item = learning::submission(
                json!({"submission_id":options["--id"]})
                    .as_object()
                    .unwrap(),
            )?;
            item.as_object_mut().unwrap().remove("protocol_version");
            Ok(json!({"submission":item}))
        }
        "list-pending" => {
            let db = workspace()?.inspect()?;
            let tx = db.unchecked_transaction().map_err(StorageError::from)?;
            let queue = reviews::queue(&tx, None)?;
            Ok(json!({"submissions":queue["waiting_review"],"queue":queue}))
        }
        _ => {
            let text = String::from_utf8(read_file(&options["--file"])?)
                .map_err(|_| ApiError::invalid_argument("答案文件必须为 UTF-8。"))?;
            let params: Params = json!({"parent_submission_id":options["--parent"],"idempotency_key":options.get("--idempotency-key"),"source":"AGENT_CLI","answer_text":text}).as_object().unwrap().clone();
            if action == "revise" {
                learning::revise(&params)
            } else {
                learning::retest(&params)
            }
        }
    })();
    output(result, format)
}

fn read_file(path: &str) -> Result<Vec<u8>, ApiError> {
    const LIMIT: u64 = 16 * 1024 * 1024;
    let file =
        File::open(path).map_err(|_| ApiError::invalid_argument("找不到可读的答案文件。"))?;
    let mut bytes = Vec::new();
    file.take(LIMIT + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| ApiError::invalid_argument("无法读取答案文件。"))?;
    if bytes.len() as u64 > LIMIT {
        return Err(ApiError::invalid_argument("答案文件超过 16 MiB。"));
    }
    Ok(bytes)
}
