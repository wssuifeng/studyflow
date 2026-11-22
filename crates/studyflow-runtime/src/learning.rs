use serde_json::{json, Value};
use studyflow_core::{
    infrastructure::StorageError,
    learning::{
        course_answers::{self, Operation, WriteRequest},
        study_sessions::{self, OpenRequest},
        submissions,
    },
};

use crate::{
    planning::workspace,
    registry::{Params, PROTOCOL_VERSION},
    ApiError,
};

fn text<'a>(params: &'a Params, key: &str) -> Result<&'a str, ApiError> {
    params
        .get(key)
        .and_then(Value::as_str)
        .filter(|text| !text.trim().is_empty())
        .ok_or_else(|| ApiError::invalid_argument(format!("{key} 必须是非空文本。")))
}

fn optional<'a>(params: &'a Params, key: &str) -> Option<&'a str> {
    params.get(key).and_then(Value::as_str)
}

fn protocol(mut response: Value) -> Value {
    response["protocol_version"] = json!(PROTOCOL_VERSION);
    response
}

pub(crate) fn open(params: &Params) -> Result<Value, ApiError> {
    Ok(protocol(study_sessions::open(
        &workspace()?,
        OpenRequest {
            course: text(params, "course_id")?,
            key: text(params, "idempotency_key")?,
            plan: optional(params, "plan_line_id"),
            new_version: params
                .get("new_version")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            review_round: params
                .get("review_round")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        },
    )?))
}

pub(crate) fn detail(params: &Params) -> Result<Value, ApiError> {
    let workspace = workspace()?;
    let db = workspace.inspect()?;
    let tx = db.unchecked_transaction().map_err(StorageError::from)?;
    Ok(protocol(study_sessions::detail(
        &tx,
        &workspace.settings().workspace,
        text(params, "study_session_id")?,
    )?))
}

pub(crate) fn save_progress(params: &Params) -> Result<Value, ApiError> {
    let version = match params.get("expected_version") {
        Some(value) if !value.is_null() => Some(
            value
                .as_i64()
                .ok_or_else(|| ApiError::from(StorageError::new("VERSION_CONFLICT")))?,
        ),
        _ => None,
    };
    let position = params
        .get("last_position")
        .map_or(Some(""), Value::as_str)
        .ok_or_else(|| ApiError::invalid_argument("last_position 必须是文本。"))?;
    let percent = params
        .get("progress_percent")
        .and_then(Value::as_i64)
        .ok_or_else(|| ApiError::invalid_argument("progress_percent 必须是整数。"))?;
    Ok(protocol(study_sessions::save_progress(
        &workspace()?,
        text(params, "study_session_id")?,
        text(params, "lesson_id")?,
        percent,
        position,
        version,
    )?))
}

pub(crate) fn complete_reading(params: &Params) -> Result<Value, ApiError> {
    Ok(protocol(study_sessions::complete_reading(
        &workspace()?,
        text(params, "study_session_id")?,
    )?))
}

pub(crate) fn answers(params: &Params) -> Result<Value, ApiError> {
    let db = workspace()?.inspect()?;
    let tx = db.unchecked_transaction().map_err(StorageError::from)?;
    Ok(protocol(course_answers::read(
        &tx,
        text(params, "course_id")?,
        optional(params, "study_session_id"),
    )?))
}

pub(crate) fn save_answers(params: &Params) -> Result<Value, ApiError> {
    write_answers(params, Operation::Save)
}

pub(crate) fn submit_answers(params: &Params) -> Result<Value, ApiError> {
    write_answers(params, Operation::Submit)
}

pub(crate) fn write_answers(params: &Params, operation: Operation) -> Result<Value, ApiError> {
    let source = params
        .get("source")
        .map_or(Some("USER_WEB"), Value::as_str)
        .ok_or_else(|| ApiError::invalid_argument("source 必须是文本。"))?;
    Ok(protocol(course_answers::write(
        &workspace()?,
        WriteRequest {
            course: text(params, "course_id")?,
            study: optional(params, "study_session_id"),
            key: text(params, "idempotency_key")?,
            source,
            operation,
            answers: params.get("answers").unwrap_or(&Value::Null),
        },
    )?))
}

pub(crate) fn submission(params: &Params) -> Result<Value, ApiError> {
    let db = workspace()?.inspect()?;
    let tx = db.unchecked_transaction().map_err(StorageError::from)?;
    Ok(protocol(submissions::detail(
        &tx,
        text(params, "submission_id")?,
        true,
    )?))
}

pub(crate) fn save_single(params: &Params) -> Result<Value, ApiError> {
    single(params, false)
}
pub(crate) fn submit_single(params: &Params) -> Result<Value, ApiError> {
    single(params, true)
}

fn single(params: &Params, submit: bool) -> Result<Value, ApiError> {
    use studyflow_core::learning::single_answer::{self, Request};
    if !submit {
        text(params, "exercise_id")?;
    }
    let version = match params
        .get("expected_version")
        .filter(|value| !value.is_null())
    {
        Some(value) => Some(
            value
                .as_i64()
                .ok_or_else(|| ApiError::from(StorageError::new("VERSION_CONFLICT")))?,
        ),
        None => None,
    };
    let answer = match params.get("answer_text") {
        Some(Value::Null) if submit => None,
        Some(Value::String(text)) => Some(text.as_str()),
        None => None,
        _ => return Err(ApiError::invalid_argument("answer_text 必须是文本。")),
    };
    Ok(protocol(single_answer::write(
        &workspace()?,
        Request {
            exercise: optional(params, "exercise_id"),
            submission: optional(params, "submission_id"),
            task: optional(params, "task_id"),
            expected_version: version,
            answer,
            key: optional(params, "idempotency_key"),
            source: optional(params, "source").unwrap_or("USER_WEB"),
            submit,
        },
    )?))
}

pub(crate) fn revise(params: &Params) -> Result<Value, ApiError> {
    followup(params, false)
}
pub(crate) fn retest(params: &Params) -> Result<Value, ApiError> {
    followup(params, true)
}

fn followup(params: &Params, retest: bool) -> Result<Value, ApiError> {
    Ok(protocol(studyflow_core::learning::single_answer::followup(
        &workspace()?,
        text(params, "parent_submission_id")?,
        text(params, "answer_text")?,
        optional(params, "idempotency_key"),
        optional(params, "source").unwrap_or("USER_WEB"),
        retest,
    )?))
}

pub(crate) fn resolve_branch(params: &Params) -> Result<Value, ApiError> {
    Ok(studyflow_core::learning::single_answer::resolve_branch(
        &workspace()?,
        text(params, "parent_submission_id")?,
        text(params, "child_submission_id")?,
        text(params, "reason")?,
    )?)
}

pub(crate) fn evidence(params: &Params) -> Result<Value, ApiError> {
    let db = workspace()?.inspect()?;
    let tx = db.unchecked_transaction().map_err(StorageError::from)?;
    Ok(studyflow_core::learning::evidence::read(
        &tx,
        text(params, "plan_line_id")?,
        optional(params, "course_id"),
        optional(params, "learning_mode"),
        params.get("limit").and_then(Value::as_u64).unwrap_or(20) as usize,
        optional(params, "cursor"),
    )?)
}

pub(crate) fn save_legacy_progress(params: &Params) -> Result<Value, ApiError> {
    let percent = params
        .get("progress_percent")
        .and_then(Value::as_i64)
        .ok_or_else(|| ApiError::invalid_argument("progress_percent 必须是整数。"))?;
    Ok(protocol(study_sessions::save_legacy_progress(
        &workspace()?,
        text(params, "course_id")?,
        text(params, "lesson_id")?,
        percent,
        optional(params, "last_position").unwrap_or_default(),
        optional(params, "source").unwrap_or("USER_WEB"),
    )?))
}

pub(crate) fn reset_preview(params: &Params) -> Result<Value, ApiError> {
    Ok(studyflow_core::learning::lifecycle::reset_preview(
        &workspace()?,
        text(params, "course_id")?,
    )?)
}

pub(crate) fn reset(params: &Params) -> Result<Value, ApiError> {
    Ok(studyflow_core::learning::lifecycle::reset(
        &workspace()?,
        text(params, "course_id")?,
        &Value::Object(params.clone()),
    )?)
}

pub(crate) fn restart_preview(params: &Params) -> Result<Value, ApiError> {
    Ok(protocol(
        studyflow_core::learning::lifecycle::restart_preview(
            &workspace()?,
            text(params, "study_session_id")?,
            params.get("reset_current_state") == Some(&Value::Bool(true)),
        )?,
    ))
}

pub(crate) fn restart(params: &Params) -> Result<Value, ApiError> {
    Ok(protocol(studyflow_core::learning::lifecycle::restart(
        &workspace()?,
        text(params, "study_session_id")?,
        &Value::Object(params.clone()),
    )?))
}
