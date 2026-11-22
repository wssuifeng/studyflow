use serde_json::{json, Value};
use studyflow_core::{
    infrastructure::config::Settings,
    planning::{self, PlanEdit},
    workspace::{snapshot, Workspace},
};
use time::Date;

use crate::registry::{Params, PROTOCOL_VERSION};
use crate::ApiError;

pub(crate) fn workspace() -> Result<Workspace, ApiError> {
    Ok(Workspace::new(Settings::from_env()?))
}

pub(crate) fn selected_day(raw: Option<&str>) -> Result<Date, ApiError> {
    raw.filter(|date| !date.is_empty())
        .map(planning::parse_date)
        .transpose()
        .map(|date| date.unwrap_or_else(planning::today))
        .map_err(|_| ApiError::invalid_argument("date 必须使用 YYYY-MM-DD 格式。"))
}

pub(crate) fn changes(_: &Params) -> Result<Value, ApiError> {
    Ok(planning::change_token(&workspace()?.inspect()?)?)
}

pub(crate) fn list(params: &Params) -> Result<Value, ApiError> {
    let inactive = params
        .get("include_inactive")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let plans = planning::list_plans(&workspace()?.inspect()?, inactive)?;
    Ok(json!({"protocol_version":PROTOCOL_VERSION,"plans":plans}))
}

pub(crate) fn detail(params: &Params) -> Result<Value, ApiError> {
    let id = params["plan_line_id"].as_str().unwrap().trim();
    if id.is_empty() {
        return Err(ApiError::invalid_argument("缺少必填参数 plan_line_id。"));
    }
    let date = selected_day(params.get("date").and_then(Value::as_str))?;
    let mut value = read_detail(id, date)?;
    value["protocol_version"] = json!(PROTOCOL_VERSION);
    Ok(value)
}

pub(crate) fn read_detail(id: &str, date: Date) -> Result<Value, ApiError> {
    let workspace = workspace()?;
    let conn = workspace.inspect()?;
    let tx = conn
        .unchecked_transaction()
        .map_err(studyflow_core::infrastructure::StorageError::from)?;
    planning::plan_detail(&tx, id, date).map_err(|error| {
        if error.code == "OBJECT_NOT_FOUND" {
            ApiError {
                code: error.code,
                message: "学习计划不存在。".into(),
                next_action: "先读取 plan.list 确认计划 ID。".into(),
            }
        } else {
            error.into()
        }
    })
}

pub(crate) fn edit(params: &Params) -> Result<Value, ApiError> {
    let mut active = workspace()?.open()?;
    Ok(planning::edit_plan(
        &mut active.connection,
        PlanEdit {
            plan_line_id: params["plan_line_id"].as_str().unwrap(),
            expected_version: params["expected_version"].as_i64().unwrap(),
            idempotency_key: params["idempotency_key"].as_str().unwrap(),
            operation: params["operation"].as_str().unwrap(),
            values: params["values"].as_object().unwrap(),
        },
    )?)
}

pub(crate) fn schedules(params: &Params) -> Result<Value, ApiError> {
    Ok(planning::schedules(
        &workspace()?.inspect()?,
        params["plan_line_id"].as_str().unwrap(),
    )?)
}

pub(crate) fn summarize(
    date: Date,
    plan: Option<&str>,
    kind: Option<&str>,
) -> Result<Value, ApiError> {
    let conn = workspace()?.inspect()?;
    let tx = conn
        .unchecked_transaction()
        .map_err(studyflow_core::infrastructure::StorageError::from)?;
    Ok(planning::dashboard(&tx, date, plan, kind)?)
}

pub(crate) fn today(params: &Params) -> Result<Value, ApiError> {
    let date = selected_day(params.get("date").and_then(Value::as_str))?;
    let mut data = summarize(
        date,
        params.get("plan_line_id").and_then(Value::as_str),
        params.get("task_kind").and_then(Value::as_str),
    )?;
    for task in data["tasks"].as_array_mut().unwrap() {
        let fields = task.as_object_mut().unwrap();
        fields.remove("date");
        fields.remove("plan_line");
    }
    data["protocol_version"] = json!(PROTOCOL_VERSION);
    data["next_action"] = json!("优先打开 current_course，或处理 assignment.queue。");
    Ok(data)
}

pub(crate) fn snapshot(params: &Params) -> Result<Value, ApiError> {
    let date = selected_day(params.get("date").and_then(Value::as_str))?;
    let mut value = snapshot::generate(
        &workspace()?,
        date,
        params
            .get("scope")
            .and_then(Value::as_str)
            .unwrap_or("today"),
    )?;
    value["protocol_version"] = json!(PROTOCOL_VERSION);
    Ok(value)
}
