use serde_json::Value;
use studyflow_core::{
    courses::practice::GroupKind,
    infrastructure::StorageError,
    learning::{
        course_answers::Operation,
        practice_groups::{self, WriteRequest},
    },
};

use crate::{learning, planning::workspace, registry::Params, ApiError};

pub(crate) fn read_group(params: &Params, kind: GroupKind) -> Result<Value, ApiError> {
    let db = workspace()?.inspect()?;
    let tx = db.unchecked_transaction().map_err(StorageError::from)?;
    Ok(practice_groups::get(
        &tx,
        params["study_session_id"].as_str().unwrap(),
        params["exercise_id"].as_str().unwrap(),
        kind,
    )?)
}

pub(crate) fn write_group(
    params: &Params,
    kind: GroupKind,
    confirm: bool,
) -> Result<Value, ApiError> {
    Ok(practice_groups::write(
        &workspace()?,
        WriteRequest {
            study: params["study_session_id"].as_str().unwrap(),
            exercise: params["exercise_id"].as_str().unwrap(),
            answers: params["answers"].as_object().unwrap(),
            key: params["idempotency_key"].as_str().unwrap().trim(),
            position: params["position"].as_u64().unwrap() as usize,
            version: params["expected_version"].as_i64().unwrap(),
            kind,
            confirm,
        },
    )?)
}

pub(crate) fn asset(params: &Params, captions: bool) -> Result<Value, ApiError> {
    let workspace = workspace()?;
    Ok(practice_groups::listening_asset(
        &workspace.inspect()?,
        &workspace.settings().workspace,
        params["study_session_id"].as_str().unwrap(),
        params["exercise_id"].as_str().unwrap(),
        captions,
    )?)
}

pub(crate) fn essay(params: &Params) -> Result<Value, ApiError> {
    let mut result = learning::write_answers(params, Operation::Essay)?;
    result.as_object_mut().unwrap().remove("protocol_version");
    Ok(result)
}
