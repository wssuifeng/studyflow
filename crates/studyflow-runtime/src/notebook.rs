use std::sync::LazyLock;

use serde_json::{json, Value};
use studyflow_core::learning::notebook as service;

use crate::{
    planning::workspace,
    registry::{Params, PROTOCOL_VERSION},
    ApiError,
};

static SCHEMAS: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("notebook-schema.json")).expect("valid notebook contracts")
});

pub(crate) fn schema(method: &str) -> Option<Value> {
    SCHEMAS.get(method).cloned()
}

fn protocol(mut value: Value) -> Value {
    value["protocol_version"] = json!(PROTOCOL_VERSION);
    value
}

fn string<'a>(p: &'a Params, key: &str) -> &'a str {
    p[key].as_str().unwrap()
}

pub(crate) fn get(p: &Params) -> Result<Value, ApiError> {
    Ok(protocol(workspace()?.read_consistent(|db| {
        service::get_blocks(db, string(p, "plan_line_id"))
    })?))
}

pub(crate) fn save(p: &Params) -> Result<Value, ApiError> {
    Ok(protocol(service::save_blocks(
        &workspace()?,
        &json!(p),
        "USER_WEB",
    )?))
}

pub(crate) fn notes(p: &Params) -> Result<Value, ApiError> {
    Ok(protocol(workspace()?.read_consistent(|db| {
        service::get_notes(db, string(p, "study_session_id"))
    })?))
}

pub(crate) fn save_note(p: &Params) -> Result<Value, ApiError> {
    Ok(protocol(service::save_note(
        &workspace()?,
        &json!(p),
        "USER_WEB",
    )?))
}

pub(crate) fn read(p: &Params) -> Result<Value, ApiError> {
    Ok(workspace()?.read_consistent(|db| service::read(db, &json!(p)))?)
}

pub(crate) fn search(p: &Params) -> Result<Value, ApiError> {
    if p.get("query").is_some_and(|query| {
        query
            .as_str()
            .is_none_or(|query| query.chars().count() > 200)
    }) {
        return Err(ApiError::invalid_argument("搜索文本最多200字符。"));
    }
    Ok(workspace()?.read_consistent(|db| service::search(db, &json!(p)))?)
}

pub(crate) fn export(p: &Params) -> Result<Value, ApiError> {
    Ok(workspace()?.read_consistent(|db| service::export(db, string(p, "plan_line_id")))?)
}

pub(crate) fn apply(p: &Params) -> Result<Value, ApiError> {
    let valid_text = |field: &Value| field.as_str().is_some_and(|value| !value.is_empty());
    let nullable = |item: &Value, key: &str| item[key].is_null() || item[key].is_string();
    let scope = |item: &Value| {
        matches!(item["scope"].as_str(), Some("PLAN" | "COURSE" | "LESSON"))
            && nullable(item, "course_id")
            && nullable(item, "lesson_id")
    };
    let sources = p.get("new_sources").is_none_or(|items| {
        items.as_array().is_some_and(|items| {
            items.iter().all(|item| {
                ["course_id", "lesson_id", "source_study_id"]
                    .iter()
                    .all(|key| item.get(key).is_some_and(Value::is_string))
                    && nullable(item, "source_block_id")
                    && nullable(item, "source_section_id")
            })
        })
    });
    let operations = p
        .get("operations")
        .and_then(Value::as_array)
        .is_some_and(|items| {
            items.iter().all(|op| match op["type"].as_str() {
                Some("insert_entry") => {
                    valid_text(&op["entry"]["id"])
                        && scope(&op["entry"])
                        && nullable(op, "after_id")
                }
                Some("move_entry") => scope(op) && nullable(op, "after_id"),
                Some("replace_entry" | "remove_entry") => true,
                _ => false,
            })
        });
    if !sources || !operations {
        return Err(ApiError::invalid_argument("笔记操作参数无效。"));
    }
    Ok(service::apply(&workspace()?, &json!(p), "USER_WEB")?)
}
