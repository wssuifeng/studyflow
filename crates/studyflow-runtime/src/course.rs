use std::{path::Path, process::ExitCode};

use serde_json::{json, Value};
use studyflow_core::{application::course_publication, courses::packages};

use crate::{
    cli::{display, help, parse, preflight_error, usage_error, ParseResult},
    planning::workspace,
    registry::{Params, PROTOCOL_VERSION},
    ApiError,
};

pub(crate) fn import_engine(params: &Params) -> Result<Value, ApiError> {
    let path = params
        .get("path")
        .and_then(Value::as_str)
        .filter(|path| !path.trim().is_empty())
        .or_else(|| {
            params
                .get("file")
                .and_then(Value::as_str)
                .filter(|path| !path.trim().is_empty())
        })
        .ok_or_else(|| ApiError::invalid_argument("course.import 需要 path。"))?;
    let mut result = course_publication::import_markdown(&workspace()?, Path::new(path))?;
    result["protocol_version"] = json!(PROTOCOL_VERSION);
    Ok(result)
}

pub(crate) fn import(args: impl Iterator<Item = String>, structured: bool) -> ExitCode {
    let (options, format) = match parse(args, &[("--file", true), ("--format", false)]) {
        ParseResult::Valid(options, format) => (options, format.unwrap_or(false)),
        ParseResult::Help => return help(),
        ParseResult::Invalid => return usage_error(),
    };
    let path = Path::new(&options["--file"]);
    if !path.is_file() {
        return usage_error();
    }
    let result = (|| -> Result<Value, ApiError> {
        let workspace = workspace()?;
        if structured {
            let package = packages::read(path)?;
            Ok(course_publication::import_package(&workspace, &package)?)
        } else {
            Ok(course_publication::import_markdown(&workspace, path)?)
        }
    })();
    match result {
        Ok(mut value) => {
            value["ok"] = json!(true);
            display(value, format);
            ExitCode::SUCCESS
        }
        Err(error) => preflight_error(error),
    }
}

use studyflow_core::{
    application::write_contract::atomic_write,
    courses::{
        catalog,
        references::{self, ReferenceRequest},
    },
    infrastructure::StorageError,
    learning::material,
    workspace::Workspace,
};

pub(crate) fn list_engine(params: &Params) -> Result<Value, ApiError> {
    let plans = params.get("plan_line_id").and_then(Value::as_str);
    let list = catalog::list(&workspace()?.inspect()?, plans)?;
    Ok(json!({"protocol_version":PROTOCOL_VERSION,"courses":list}))
}

pub(crate) fn detail_engine(params: &Params) -> Result<Value, ApiError> {
    let id = nonblank(&params["course_id"])?;
    let mut response = detail(&workspace()?, id)?;
    response["protocol_version"] = json!(PROTOCOL_VERSION);
    Ok(response)
}

fn detail(workspace: &Workspace, id: &str) -> Result<Value, ApiError> {
    let db = workspace.inspect()?;
    let tx = db.unchecked_transaction().map_err(StorageError::from)?;
    Ok(catalog::detail(&tx, &workspace.settings().workspace, id)?)
}

fn nonblank(value: &Value) -> Result<&str, ApiError> {
    value
        .as_str()
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .ok_or_else(|| ApiError::invalid_argument("需要非空标识。"))
}

pub(crate) fn preview_engine(params: &Params) -> Result<Value, ApiError> {
    update(params, false)
}

pub(crate) fn apply_engine(params: &Params) -> Result<Value, ApiError> {
    update(params, true)
}

fn update(params: &Params, apply: bool) -> Result<Value, ApiError> {
    let package = packages::read(Path::new(params["path"].as_str().unwrap()))?;
    let workspace = workspace()?;
    let id = params["course_id"].as_str().unwrap();
    let expected = params["expected_revision"].as_i64().unwrap();
    if apply {
        Ok(course_publication::apply_update(
            &workspace,
            id,
            &package,
            expected,
            params["preview_hash"].as_str().unwrap(),
            params["idempotency_key"].as_str().unwrap(),
        )?)
    } else {
        Ok(course_publication::preview_update(
            &workspace, id, &package, expected,
        )?)
    }
}

pub(crate) fn source_engine(params: &Params) -> Result<Value, ApiError> {
    let workspace = workspace()?;
    Ok(material::source(
        &workspace.inspect()?,
        &workspace.settings().workspace,
        nonblank(&params["study_session_id"])?,
        nonblank(&params["lesson_id"])?,
        params.get("block_id").and_then(Value::as_str),
        params.get("section_id").and_then(Value::as_str),
    )?)
}

fn reference_request(params: &Params) -> ReferenceRequest<'_> {
    ReferenceRequest {
        study_session_id: params.get("study_session_id").and_then(Value::as_str),
        exercise_id: params.get("exercise_id").and_then(Value::as_str),
        submission_id: params.get("submission_id").and_then(Value::as_str),
        reference_revision: params.get("reference_revision").and_then(Value::as_i64),
    }
}

pub(crate) fn reference_read(params: &Params) -> Result<Value, ApiError> {
    let db = workspace()?.inspect()?;
    let tx = db.unchecked_transaction().map_err(StorageError::from)?;
    Ok(references::resolve(&tx, reference_request(params))?)
}

pub(crate) fn reference_view(params: &Params) -> Result<Value, ApiError> {
    let mut active = workspace()?.open()?;
    Ok(atomic_write(&mut active.connection, |db| {
        references::view(db, reference_request(params))
    })?)
}

pub(crate) fn execute(action: &str, args: impl Iterator<Item = String>) -> ExitCode {
    let fields: &[(&str, bool)] = match action {
        "list" => &[("--plan-line", false), ("--format", false)],
        "detail" => &[("--id", true), ("--format", false)],
        "readback-check" => &[
            ("--course", true),
            ("--plan-line", false),
            ("--format", false),
        ],
        "update-preview" => &[
            ("--id", true),
            ("--file", true),
            ("--expected-revision", true),
            ("--format", false),
        ],
        "update-apply" => &[
            ("--id", true),
            ("--file", true),
            ("--expected-revision", true),
            ("--preview-hash", true),
            ("--idempotency-key", true),
            ("--format", false),
        ],
        _ => unreachable!(),
    };
    let (options, format) = match parse(args, fields) {
        ParseResult::Valid(options, format) => (options, format.unwrap_or(false)),
        ParseResult::Help => return help(),
        ParseResult::Invalid => return usage_error(),
    };
    let result = (|| -> Result<Value, ApiError> {
        let workspace = workspace()?;
        let plan = options.get("--plan-line").map(String::as_str);
        match action {
            "list" => Ok(json!({"courses":catalog::list(&workspace.inspect()?,plan)?})),
            "detail" => detail(&workspace, &options["--id"]),
            "readback-check" => {
                let db = workspace.inspect()?;
                let tx = db.unchecked_transaction().map_err(StorageError::from)?;
                Ok(material::readback(
                    &tx,
                    &workspace.settings().workspace,
                    &options["--course"],
                    plan,
                )?)
            }
            _ => {
                let apply = action == "update-apply";
                let expected = options["--expected-revision"]
                    .parse::<i64>()
                    .ok()
                    .filter(|n| *n >= 1)
                    .ok_or_else(|| {
                        ApiError::invalid_argument("expected_revision 必须是正整数。")
                    })?;
                let mut params = json!({"course_id":options["--id"],"path":options["--file"],"expected_revision":expected});
                if apply {
                    params["preview_hash"] = json!(options["--preview-hash"]);
                    params["idempotency_key"] = json!(options["--idempotency-key"]);
                }
                update(params.as_object().unwrap(), apply)
            }
        }
    })();
    match result {
        Ok(mut value) => {
            if action != "update-preview" {
                value["ok"] = json!(true);
            }
            display(value, format);
            ExitCode::SUCCESS
        }
        Err(error) => preflight_error(error),
    }
}
