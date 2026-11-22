use std::{path::Path, process::ExitCode};

use serde_json::{json, Value};
use studyflow_core::{
    courses::purge,
    infrastructure::StorageError,
    learning::{lifecycle, notebook::cleanup},
};

use crate::{
    cli::{display, preflight_error},
    planning::workspace,
    ApiError,
};

pub const COMMANDS: &[(&str, &str, &str)] = &[
    (
        "course_reset_learning",
        "studyflow course reset-learning --id <course-id> --dry-run --format json",
        "maintenance",
    ),
    (
        "workspace_purge_legacy_notes",
        "studyflow workspace purge-legacy-notes --dry-run --format json",
        "maintenance",
    ),
    (
        "workspace_purge_courses",
        "studyflow workspace purge-courses --dry-run --format json",
        "maintenance",
    ),
];

const RESET_HELP: &str = "Usage: studyflow course reset-learning --id <course-id> --dry-run|--confirm [--state-hash <sha256>] [--content-hash <sha256>] [--idempotency-key <key>] [--format text|json]";
const NOTES_HELP: &str = "Usage: studyflow workspace purge-legacy-notes --dry-run|--confirm [--preview-token <token>] [--format text|json]";
const COURSES_HELP: &str = "Usage: studyflow workspace purge-courses --dry-run|--confirm [--id <course-id>]... [--backup <archive>] [--format text|json]";

pub(crate) fn execute(action: &str, mut args: impl Iterator<Item = String>) -> ExitCode {
    let (help, fields) = match action {
        "reset-learning" => (
            RESET_HELP,
            &[
                "--id",
                "--state-hash",
                "--content-hash",
                "--idempotency-key",
            ][..],
        ),
        "purge-legacy-notes" => (NOTES_HELP, &["--preview-token"][..]),
        "purge-courses" => (COURSES_HELP, &["--id", "--backup"][..]),
        _ => unreachable!(),
    };
    let invalid = || {
        eprintln!("{help}");
        ExitCode::from(2)
    };
    let mut values = std::collections::BTreeMap::new();
    let mut ids = Vec::new();
    let mut dry_run = false;
    let mut confirm = false;
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--help" => {
                println!("{help}");
                return ExitCode::SUCCESS;
            }
            "--dry-run" => dry_run = true,
            "--confirm" => confirm = true,
            "--format" => {
                let Some(format) = args
                    .next()
                    .filter(|arg| matches!(arg.as_str(), "text" | "json"))
                else {
                    return invalid();
                };
                if values.insert(flag, format).is_some() {
                    return invalid();
                }
            }
            _ if fields.contains(&flag.as_str()) => {
                let Some(value) = args.next().filter(|arg| !arg.starts_with("--")) else {
                    return invalid();
                };
                if flag == "--id" && action == "purge-courses" {
                    ids.push(value);
                } else if values.insert(flag, value).is_some() {
                    return invalid();
                }
            }
            _ => return invalid(),
        }
    }
    if action == "reset-learning" && !values.contains_key("--id") {
        return invalid();
    }
    if dry_run == confirm {
        let code = if dry_run && action == "purge-courses" {
            "INVALID_ARGUMENT"
        } else {
            "CONFIRMATION_REQUIRED"
        };
        return preflight_error(StorageError::new(code).into());
    }
    let run = || -> Result<Value, ApiError> {
        let workspace = workspace()?;
        let get = |name: &str| values.get(name).map(String::as_str);
        let mut receipt = match action {
            "reset-learning" => {
                let course = &values["--id"];
                if dry_run {
                    lifecycle::reset_preview(&workspace, course)?
                } else {
                    lifecycle::reset(
                        &workspace,
                        course,
                        &json!({"confirm":true,"expected_state_hash":get("--state-hash"),"expected_content_hash":get("--content-hash"),"idempotency_key":get("--idempotency-key")}),
                    )?
                }
            }
            "purge-legacy-notes" => {
                if dry_run {
                    cleanup::preview(&workspace)?
                } else {
                    cleanup::purge(
                        &workspace,
                        get("--preview-token")
                            .ok_or_else(|| StorageError::new("PREVIEW_REQUIRED"))?,
                    )?
                }
            }
            "purge-courses" => {
                let ids = (!ids.is_empty()).then_some(ids.as_slice());
                if dry_run {
                    purge::preview(&workspace, ids)?
                } else {
                    purge::purge(
                        &workspace,
                        ids,
                        Path::new(
                            get("--backup").ok_or_else(|| StorageError::new("BACKUP_REQUIRED"))?,
                        ),
                    )?
                }
            }
            _ => unreachable!(),
        };
        receipt["ok"] = json!(true);
        if action != "reset-learning" {
            receipt["mode"] = json!(if dry_run { "dry-run" } else { "purge" });
        }
        Ok(receipt)
    };
    match run() {
        Ok(receipt) => {
            display(receipt, values.get("--format").is_some_and(|f| f == "json"));
            ExitCode::SUCCESS
        }
        Err(error) => preflight_error(error),
    }
}
