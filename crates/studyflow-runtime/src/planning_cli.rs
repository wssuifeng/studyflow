use std::process::ExitCode;

use serde_json::{json, Value};
use studyflow_core::{
    planning::{self, NewTask},
    workspace::snapshot,
};

use crate::{
    cli::{display, help, parse, preflight_error, usage_error, ParseResult},
    planning as api, ApiError,
};

const FILTERS: &[(&str, bool)] = &[
    ("--date", false),
    ("--plan-line", false),
    ("--kind", false),
    ("--format", false),
];
const FORMAT: &[(&str, bool)] = &[("--format", false)];

pub fn plan(mut args: impl Iterator<Item = String>) -> ExitCode {
    match args.next().as_deref() {
        Some(action @ ("notebook-get" | "notebook-read" | "notebook-save" | "notebook-apply")) => {
            crate::notebook_cli::execute(action, args)
        }
        Some("list") => run(args, FORMAT, |_| {
            let mut plans = planning::list_plans(&api::workspace()?.inspect()?, false)?;
            plans.iter_mut().for_each(prune_plan);
            Ok(json!({"plans":plans}))
        }),
        Some("create") => run(
            args,
            &[("--name", true), ("--priority", false), ("--format", false)],
            |opts| {
                let priority = priority(opts.get("--priority"))?;
                let mut active = open_for_create()?;
                let mut value =
                    planning::create_plan(&mut active.connection, &opts["--name"], priority)?;
                prune_plan(&mut value);
                Ok(value)
            },
        ),
        Some("detail") => run(args, &[("--id", true), ("--format", false)], |opts| {
            api::read_detail(&opts["--id"], planning::today())
        }),
        Some("task-list") => tasks(false, args),
        Some("task-create") => tasks(true, args),
        Some("--help") | None => help(),
        _ => usage_error(),
    }
}

pub fn task(mut args: impl Iterator<Item = String>) -> ExitCode {
    match args.next().as_deref() {
        Some("list") => tasks(false, args),
        Some("create") => tasks(true, args),
        Some("--help") | None => help(),
        _ => usage_error(),
    }
}

fn open_for_create() -> Result<studyflow_core::workspace::ActiveWorkspace, ApiError> {
    let workspace = api::workspace()?;
    match workspace.open() {
        Err(error) if error.code == "WORKSPACE_NOT_INITIALIZED" => {
            workspace.upgrade()?;
            Ok(workspace.open()?)
        }
        result => Ok(result?),
    }
}

fn prune_plan(value: &mut Value) {
    let fields = value.as_object_mut().unwrap();
    fields.remove("version");
    fields.remove("focus_course_id");
}

fn tasks(create: bool, args: impl Iterator<Item = String>) -> ExitCode {
    if !create {
        return run(args, FILTERS, |opts| {
            let date = opts
                .get("--date")
                .map(|date| planning::parse_date(date))
                .transpose()?;
            let conn = api::workspace()?.inspect()?;
            Ok(
                json!({"tasks":planning::list_tasks(&conn, date, option(opts,"--plan-line"), option(opts,"--kind"), false)?}),
            )
        });
    }
    run(
        args,
        &[
            ("--title", true),
            ("--date", true),
            ("--plan-line", false),
            ("--kind", false),
            ("--description", false),
            ("--priority", false),
            ("--format", false),
        ],
        |opts| {
            let date = planning::parse_date(&opts["--date"])?;
            let priority = priority(opts.get("--priority"))?;
            let mut active = open_for_create()?;
            Ok(planning::create_task(
                &mut active.connection,
                NewTask {
                    title: &opts["--title"],
                    date,
                    kind: option(opts, "--kind").unwrap_or("OTHER"),
                    description: option(opts, "--description").unwrap_or_default(),
                    plan: option(opts, "--plan-line"),
                    priority,
                },
            )?)
        },
    )
}

pub fn today(args: impl Iterator<Item = String>) -> ExitCode {
    run(args, FILTERS, |opts| {
        let date = api::selected_day(option(opts, "--date"))?;
        let mut data = api::summarize(date, option(opts, "--plan-line"), option(opts, "--kind"))?;
        let current = data["current_course"].take();
        if !current.is_null() {
            data["current_course"] = json!({"id":current["id"],"title":current["title"],"sequence":current["sequence"],"total":current["total"]});
        }
        for course in data["courses"].as_array_mut().unwrap() {
            *course = json!({"id":course["id"],"title":course["title"],"sequence":course["sequence"],"total":course["total"],
                 "knowledge_total":course["knowledge_total"],"knowledge_completed":course["knowledge_completed"],"progress_percent":course["progress_percent"]});
        }
        for task in data["tasks"].as_array_mut().unwrap() {
            task.as_object_mut().unwrap().remove("date");
        }
        let settings = studyflow_core::infrastructure::config::Settings::from_env()?;
        data["protocol_version"] = json!(crate::registry::PROTOCOL_VERSION);
        data["workspace"] = json!({"root":settings.workspace,"exists":settings.workspace.is_dir()});
        data["database"] = json!({"url":settings.sqlite_url(),"driver":"sqlite","managed_by_app":true,"status":"not_checked","reachable":null});
        let commands = crate::cli::AUTHOR_COMMANDS.iter().map(|(name, _, _)| *name);
        let tools = [
            "plan_detail",
            "document_read",
            "version",
            "capabilities",
            "today",
            "snapshot_generate",
            "workspace_export",
            "workspace_import",
            "course_import",
            "course_detail",
            "course_update_preview",
            "course_update_apply",
        ];
        data["capabilities"] = json!(commands.chain(tools).collect::<Vec<_>>());
        data["next_action"] =
            json!("优先打开 current_course，或处理 assignment queue 中的待批改作答。");
        Ok(data)
    })
}

pub fn snapshots(mut args: impl Iterator<Item = String>) -> ExitCode {
    match args.next().as_deref() {
        Some("generate") => run(args, &[("--scope", false), ("--format", false)], |opts| {
            Ok(snapshot::generate(
                &api::workspace()?,
                planning::today(),
                option(opts, "--scope").unwrap_or("today"),
            )?)
        }),
        None | Some("--help") => help(),
        _ => usage_error(),
    }
}

type Options = std::collections::BTreeMap<String, String>;

fn option<'a>(opts: &'a Options, key: &str) -> Option<&'a str> {
    opts.get(key).map(String::as_str)
}

fn priority(value: Option<&String>) -> Result<i64, ApiError> {
    value
        .map(|value| value.parse())
        .transpose()
        .map(|value| value.unwrap_or(1))
        .map_err(|_| ApiError::invalid_argument("priority 必须使用整数。"))
}

fn run(
    args: impl Iterator<Item = String>,
    available: &[(&str, bool)],
    f: impl FnOnce(&Options) -> Result<Value, ApiError>,
) -> ExitCode {
    let (opts, format) = match parse(args, available) {
        ParseResult::Valid(opts, format) => (opts, format.unwrap_or(false)),
        ParseResult::Help => return help(),
        ParseResult::Invalid => return usage_error(),
    };
    match f(&opts) {
        Ok(mut data) => {
            data["ok"] = json!(true);
            display(data, format);
            ExitCode::SUCCESS
        }
        Err(error) => preflight_error(error),
    }
}
