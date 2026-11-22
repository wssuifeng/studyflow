use std::{fs::File, io::Read, process::ExitCode};

use serde_json::json;

use crate::{
    cli::{display, parse_with_empty, preflight_error, usage_error, ParseResult},
    review, ApiError,
};

pub(crate) const COMMANDS: &[(&str, &str, &str)] = &[
    (
        "review_write",
        "studyflow review write --submission <id> --summary <summary> --format json",
        "write",
    ),
    (
        "assignment_queue",
        "studyflow assignment queue --format json",
        "read",
    ),
];

pub fn execute(group: &str, mut args: impl Iterator<Item = String>) -> ExitCode {
    let index = usize::from(group == "assignment");
    let (name, help, _) = COMMANDS[index];
    let expected = name.split_once('_').unwrap().1;
    match args.next().as_deref() {
        None | Some("--help") => {
            println!("Usage: {help}");
            return ExitCode::SUCCESS;
        }
        Some(action) if action == expected => {}
        _ => return usage_error(),
    }
    let flag = if index == 0 {
        "--needs-revision"
    } else {
        "--full"
    };
    let allowed: &[(&str, bool)] = if index == 0 {
        &[
            ("--submission", true),
            ("--summary", true),
            ("--file", false),
            ("--issue-count", false),
            ("--needs-revision", false),
            ("--decision", false),
            ("--next-action", false),
            ("--idempotency-key", false),
            ("--format", false),
        ]
    } else {
        &[
            ("--plan-line", false),
            ("--full", false),
            ("--role", false),
            ("--limit", false),
            ("--format", false),
        ]
    };
    let args = args.map(|arg| {
        if arg == flag {
            format!("{flag}=true")
        } else {
            arg
        }
    });
    let (options, format) = match parse_with_empty(args, allowed, Some("--next-action")) {
        ParseResult::Valid(options, format) => (options, format.unwrap_or(false)),
        ParseResult::Help => {
            println!("Usage: {help}");
            return ExitCode::SUCCESS;
        }
        ParseResult::Invalid => return usage_error(),
    };
    if options.get(flag).is_some_and(|value| value != "true") {
        return usage_error();
    }
    let numeric = if index == 0 {
        "--issue-count"
    } else {
        "--limit"
    };
    let count = if let Some(value) = options.get(numeric) {
        match value.parse::<i64>() {
            Ok(n) => Some(n),
            Err(_) => return usage_error(),
        }
    } else {
        None
    };
    let result = if index == 0 {
        (|| {
            let detail = match options.get("--file") {
                Some(path) => {
                    let mut text = String::new();
                    File::open(path)
                        .and_then(|file| file.take(16_000_001).read_to_string(&mut text))
                        .map_err(|_| ApiError::invalid_argument("无法读取批改详情文件。"))?;
                    if text.len() > 16_000_000 {
                        return Err(ApiError::invalid_argument("批改详情文件超限。"));
                    }
                    text.replace("\r\n", "\n").replace('\r', "\n")
                }
                None => String::new(),
            };
            let params = json!({"submission_id":options["--submission"],"summary":options["--summary"],"detail_markdown":detail,"issue_count":count.unwrap_or(0),"needs_revision":options.contains_key(flag),"idempotency_key":options.get("--idempotency-key"),"decision":options.get("--decision"),"next_action":options.get("--next-action").map(String::as_str).unwrap_or_default()});
            review::write(params.as_object().unwrap())
        })()
    } else {
        let params = json!({"plan_line_id":options.get("--plan-line"),"role":options.get("--role").map_or("agent",String::as_str),"limit":count.unwrap_or(50)});
        if options.contains_key(flag) {
            review::queue(params.as_object().unwrap())
        } else {
            review::summary(params.as_object().unwrap())
        }
    };
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
