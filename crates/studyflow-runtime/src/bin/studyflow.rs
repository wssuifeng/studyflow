use std::{env, process::ExitCode};

use serde_json::json;
use studyflow_core::{infrastructure::config::Settings, workspace::Workspace};
use studyflow_runtime::{archive_cli, cli, learning_cli, planning_cli, review_cli};

fn main() -> ExitCode {
    let mut args: Vec<_> = env::args().skip(1).collect();
    if args
        .last()
        .is_some_and(|flag| flag == "--help" || flag == "-h")
    {
        if let Some(result) = studyflow_runtime::cli_help::print(&args[..args.len() - 1]) {
            return result;
        }
        if let Some(flag) = args.last_mut() {
            *flag = "--help".to_owned();
        }
    }
    let mut args = args.into_iter();
    match args.next().as_deref() {
        Some("--show-completion") => studyflow_runtime::completion::run(false, args),
        Some("--install-completion") => studyflow_runtime::completion::run(true, args),
        Some("authoring-workspace") => studyflow_runtime::authoring_cli::execute(args),
        Some("call") => cli::call(args),
        Some("doctor") => cli::discovery("system.doctor", args),
        Some("init") => cli::initialize(args),
        Some("version") => cli::discovery("system.version", args),
        Some("capabilities") => cli::discovery("system.capabilities", args),
        Some("workspace") => archive_cli::execute(args),
        Some("document") => cli::document(args),
        Some("course") => cli::course(args),
        Some(group @ ("review" | "assignment")) => review_cli::execute(group, args),
        Some("submission") => learning_cli::submission(args),
        Some("plan") => planning_cli::plan(args),
        Some("task") => planning_cli::task(args),
        Some("status" | "today") => planning_cli::today(args),
        Some("snapshot") => planning_cli::snapshots(args),
        Some("db-upgrade") => match (args.next().as_deref(), args.next().as_deref(), args.next()) {
            (None, None, None) | (Some("--format"), Some("text"), None) => upgrade(false),
            (Some("--format"), Some("json"), None) => upgrade(true),
            (Some("--help"), None, None) => cli::help(),
            _ => cli::usage_error(),
        },
        Some("--help") | None => cli::help(),
        _ => cli::usage_error(),
    }
}

fn upgrade(as_json: bool) -> ExitCode {
    match Settings::from_env().and_then(|settings| Workspace::new(settings).upgrade()) {
        Ok(receipt) => {
            if as_json {
                println!(
                    "{}",
                    json!({"ok": true, "upgraded": receipt.upgraded, "status": receipt.status, "backup": receipt.backup})
                );
            } else {
                println!("{}", receipt.status);
                if let Some(backup) = receipt.backup {
                    println!("备份 {}", backup.display());
                }
            }
            ExitCode::SUCCESS
        }
        Err(error) => {
            let (message, next_action) = match error.code {
                "UNSUPPORTED_DATABASE" => (
                    "数据库配置需要有效的 SQLite 文件路径。",
                    "检查 STUDYFLOW_DATABASE_URL 或 STUDYFLOW_DATABASE_PATH。",
                ),
                "WORKSPACE_MAINTENANCE_BUSY" => {
                    ("工作区正在使用或维护。", "关闭使用工作区的程序后重试。")
                }
                "NEWER_SCHEMA_UNSUPPORTED" => {
                    ("工作区由更新版本创建。", "使用与工作区匹配的应用版本。")
                }
                _ => ("无法完成 SQLite 升级。", "核对数据库状态和备份后重试。"),
            };
            eprintln!(
                "{}",
                json!({"ok": false, "error_code": error.code, "message": message, "next_action": next_action})
            );
            ExitCode::FAILURE
        }
    }
}
