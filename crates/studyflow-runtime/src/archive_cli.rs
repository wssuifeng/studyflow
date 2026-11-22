use std::{path::PathBuf, process::ExitCode};

use serde_json::json;

use crate::cli::display;
use studyflow_core::{infrastructure::config::Settings, workspace::archive};

const HELP: &str = "Usage: studyflow workspace export --output <archive> [--format text|json]\n       studyflow workspace import --file <archive> --target <workspace> [--format text|json]\n       studyflow workspace purge-courses|purge-legacy-notes --help";

pub fn execute(mut args: impl Iterator<Item = String>) -> ExitCode {
    let mode = match args.next().as_deref() {
        Some(action @ ("purge-courses" | "purge-legacy-notes")) => {
            return crate::maintenance_cli::execute(action, args)
        }
        Some("export") => "export",
        Some("import") => "import",
        Some("--help") | None => {
            println!("{HELP}");
            return ExitCode::SUCCESS;
        }
        _ => return invalid_arguments(),
    };
    let mut path: Option<PathBuf> = None;
    let mut target: Option<PathBuf> = None;
    let mut format = None;
    while let Some(flag) = args.next() {
        if flag == "--help" {
            println!("{HELP}");
            return ExitCode::SUCCESS;
        }
        let Some(value) = args.next().filter(|arg| !arg.starts_with("--")) else {
            return invalid_arguments();
        };
        match flag.as_str() {
            "--output" if mode == "export" && path.is_none() => path = Some(value.into()),
            "--file" if mode == "import" && path.is_none() => path = Some(value.into()),
            "--target" if mode == "import" && target.is_none() => target = Some(value.into()),
            "--format" if format.is_none() && matches!(value.as_str(), "text" | "json") => {
                format = Some(value);
            }
            _ => return invalid_arguments(),
        }
    }
    let Some(path) = path else {
        return invalid_arguments();
    };
    let result = if mode == "export" {
        Settings::from_env()
            .and_then(|settings| archive::export(&settings, &path))
            .map(|receipt| json!(receipt))
    } else {
        let Some(target) = target else {
            return invalid_arguments();
        };
        archive::restore(&path, &target).map(|receipt| json!(receipt))
    };
    match result {
        Ok(value) => {
            display(value, format.as_deref() == Some("json"));
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!(
                "{}",
                json!({
                    "ok":false, "error_code":error.code,
                    "message":"工作区归档操作未完成。",
                    "next_action":"核对备份、恢复目标和运行中的 StudyFlow 进程。"
                })
            );
            ExitCode::FAILURE
        }
    }
}

fn invalid_arguments() -> ExitCode {
    eprintln!("{HELP}");
    ExitCode::from(2)
}
