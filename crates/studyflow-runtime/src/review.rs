use std::sync::LazyLock;

use serde_json::{json, Value};
use studyflow_core::{infrastructure::file_paths::is_sha256, reviews};

use crate::{
    planning::workspace,
    registry::{Params, PROTOCOL_VERSION},
    ApiError,
};

static SCHEMAS: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("review-schema.json")).expect("valid review contracts")
});

pub(crate) fn schema(method: &str) -> Option<Value> {
    SCHEMAS.get(method).cloned()
}

pub(crate) fn queue(params: &Params) -> Result<Value, ApiError> {
    let mut value = workspace()?.read_consistent(|db| {
        reviews::queue(db, params.get("plan_line_id").and_then(Value::as_str))
    })?;
    value["protocol_version"] = json!(PROTOCOL_VERSION);
    Ok(value)
}

pub(crate) fn summary(params: &Params) -> Result<Value, ApiError> {
    if params
        .get("history")
        .is_some_and(|value| !value.is_boolean())
    {
        return Err(ApiError::invalid_argument("history 必须是布尔值。"));
    }
    Ok(workspace()?.read_consistent(|db| reviews::summary(db, &json!(params)))?)
}

pub(crate) fn context(params: &Params) -> Result<Value, ApiError> {
    Ok(workspace()?.read_consistent(|db| reviews::context(db, &json!(params)))?)
}

pub(crate) fn write(params: &Params) -> Result<Value, ApiError> {
    if params
        .get("needs_revision")
        .is_some_and(|value| !value.is_boolean())
        || params
            .get("issue_count")
            .is_some_and(|value| value.as_i64().is_none_or(|count| count < 0))
        || params
            .get("reference_hash")
            .filter(|value| !value.is_null())
            .is_some_and(|value| value.as_str().is_none_or(|hash| !is_sha256(hash)))
        || params
            .get("reference_revision")
            .filter(|value| !value.is_null())
            .is_some_and(|value| value.as_i64().is_none_or(|revision| revision < 1))
    {
        return Err(ApiError::invalid_argument(
            "批改参数需要有效的版本、摘要哈希和状态。",
        ));
    }
    let mut value = reviews::write(&workspace()?, &json!(params))?;
    value["protocol_version"] = json!(PROTOCOL_VERSION);
    Ok(value)
}

pub(crate) fn publish(params: &Params) -> Result<Value, ApiError> {
    Ok(reviews::publish(&workspace()?, &json!(params))?)
}

pub(crate) fn notebooks(_: &Params) -> Result<Value, ApiError> {
    Ok(workspace()?.read_consistent(studyflow_core::mistakes::notebooks)?)
}

pub(crate) fn mistake_summary(params: &Params) -> Result<Value, ApiError> {
    Ok(workspace()?.read_consistent(|db| studyflow_core::mistakes::summary(db, &json!(params)))?)
}

pub(crate) fn mistake_list(params: &Params) -> Result<Value, ApiError> {
    Ok(workspace()?.read_consistent(|db| studyflow_core::mistakes::list(db, &json!(params)))?)
}

pub(crate) fn mistake_context(params: &Params) -> Result<Value, ApiError> {
    Ok(workspace()?.read_consistent(|db| studyflow_core::mistakes::context(db, &json!(params)))?)
}

pub(crate) fn mistake_review(params: &Params) -> Result<Value, ApiError> {
    Ok(studyflow_core::mistakes::select_review(
        &workspace()?,
        &json!(params),
    )?)
}

pub(crate) fn mistake_retest(params: &Params) -> Result<Value, ApiError> {
    Ok(studyflow_core::mistakes::request_retest(
        &workspace()?,
        &json!(params),
    )?)
}

pub(crate) fn archive_preview(params: &Params) -> Result<Value, ApiError> {
    Ok(workspace()?
        .read_consistent(|db| studyflow_core::mistakes::archive_preview(db, &json!(params)))?)
}

pub(crate) fn archive_apply(params: &Params) -> Result<Value, ApiError> {
    Ok(studyflow_core::mistakes::archive_apply(
        &workspace()?,
        &json!(params),
    )?)
}

pub(crate) fn remediation_preview(params: &Params) -> Result<Value, ApiError> {
    Ok(studyflow_core::application::remediation::preview(
        &workspace()?,
        &json!(params),
    )?)
}

pub(crate) fn remediation_publish(params: &Params) -> Result<Value, ApiError> {
    Ok(studyflow_core::application::remediation::publish(
        &workspace()?,
        &json!(params),
    )?)
}

pub(crate) fn remediation_list(params: &Params) -> Result<Value, ApiError> {
    let workspace = workspace()?;
    Ok(workspace.read_consistent(|db| {
        studyflow_core::mistakes::remediation::list(
            db,
            &workspace.settings().workspace,
            &json!(params),
        )
    })?)
}

pub(crate) fn remediation_get(params: &Params) -> Result<Value, ApiError> {
    let workspace = workspace()?;
    Ok(workspace.read_consistent(|db| {
        studyflow_core::mistakes::remediation::get(
            db,
            &workspace.settings().workspace,
            params["course_id"].as_str().unwrap(),
            true,
        )
    })?)
}
