use serde_json::Value;
use studyflow_core::{
    application::english::{self as app, Command},
    infrastructure::StorageError,
    learning::english,
};

use crate::{planning::workspace, registry::Params, ApiError};

pub(crate) fn read(params: &Params, view: &str) -> Result<Value, ApiError> {
    let workspace = workspace()?;
    let db = workspace.inspect()?;
    let tx = db.unchecked_transaction().map_err(StorageError::from)?;
    let study = || params["study_session_id"].as_str().unwrap();
    Ok(match view {
        "get" => english::get(&tx, &workspace.settings().workspace, study()),
        "answer" => english::answer(&tx, study(), params["exercise_id"].as_str().unwrap()),
        "retest-get" => english::retest::get(&tx, params["task_id"].as_str().unwrap()),
        _ => unreachable!(),
    }?)
}

pub(crate) fn write(params: &Params, operation: &str) -> Result<Value, ApiError> {
    let study = params.get("study_session_id").and_then(Value::as_str);
    let key = params["idempotency_key"].as_str().unwrap();
    let exercise = || params["exercise_id"].as_str().unwrap();
    let answer = || params["answer_text"].as_str().unwrap();
    let expected = || params["expected_version"].as_i64().unwrap();
    let task = || params["task_id"].as_str().unwrap();
    let command = match operation {
        "save" => Command::Save {
            exercise: exercise(),
            answer: answer(),
            expected: expected(),
            skipped: params
                .get("skipped")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        },
        "check" => Command::Check {
            exercise: exercise(),
            expected: expected(),
        },
        "request-review" => Command::Review {
            exercise: exercise(),
            expected: expected(),
        },
        "reveal" => Command::Reveal {
            exercise: exercise(),
        },
        "navigate" => Command::Move {
            position: params["position"].as_i64().unwrap(),
            expected: expected(),
        },
        "submit" => Command::Submit {
            versions: params["expected_versions"].as_object().unwrap(),
        },
        "retest-save" => Command::RetestSave {
            task: task(),
            answer: answer(),
            expected: expected(),
        },
        "retest-check" => Command::RetestCheck {
            task: task(),
            answer: answer(),
            expected: expected(),
        },
        _ => unreachable!(),
    };
    Ok(app::write(&workspace()?, study, key, command)?)
}
