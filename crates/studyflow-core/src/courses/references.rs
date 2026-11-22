use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use super::{
    presentation::{question_fingerprint, reference_fingerprint},
    store::load_json,
};
use crate::{
    documents,
    infrastructure::{events, StorageError},
};

#[derive(Default)]
pub struct ReferenceRequest<'a> {
    pub study_session_id: Option<&'a str>,
    pub exercise_id: Option<&'a str>,
    pub submission_id: Option<&'a str>,
    pub reference_revision: Option<i64>,
}

pub fn resolve(db: &Connection, request: ReferenceRequest<'_>) -> Result<Value, StorageError> {
    let (study, exercise) = if let Some(submission) =
        request.submission_id.filter(|id| !id.is_empty())
    {
        if request.study_session_id.is_some_and(|s| !s.is_empty())
            || request.exercise_id.is_some_and(|s| !s.is_empty())
        {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        let (study, ex, retest) = db
            .query_row(
                "SELECT study_session_id,exercise_id,retest_task_id FROM submissions WHERE id=?",
                [submission],
                |r| {
                    Ok((
                        r.get::<_, Option<String>>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, Option<String>>(2)?,
                    ))
                },
            )
            .optional()?
            .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
        if retest.is_some() {
            return Ok(
                json!({"available":false,"reason":"独立复测题不复用原题解析，请读取复测任务依据。"}),
            );
        }
        (study, Some(ex))
    } else {
        (
            request.study_session_id.map(str::to_owned),
            request.exercise_id.map(str::to_owned),
        )
    };
    let Some(study) = study.filter(|value| !value.is_empty()) else {
        return Ok(json!({"available":false,"reason":"旧作答没有冻结材料，不能推定参考版本。"}));
    };
    let exercise = exercise
        .filter(|value| !value.is_empty())
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    let (course,raw,hint_tracking): (String,String,bool) = db.query_row("SELECT course_id,snapshot_json,hint_tracking_enabled FROM course_study_sessions WHERE id=?",[&study],
        |r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?.ok_or_else(||StorageError::new("OBJECT_NOT_FOUND"))?;
    let content = load_json(&raw)?;
    let question = content["lessons"]
        .as_array()
        .into_iter()
        .flatten()
        .flat_map(|l| l["exercises"].as_array().into_iter().flatten())
        .find(|e| e["id"] == exercise)
        .ok_or_else(|| StorageError::new("SCOPE_MISMATCH"))?;
    let original = content["course"]["content_revision"].as_i64().unwrap_or(1);
    let revision = request.reference_revision.unwrap_or(original);
    if revision < 1 {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let question_hash = question_fingerprint(question);
    let reference = if request.reference_revision.is_some() {
        let (stored,mapped): (String,String) = db.query_row("SELECT package_json,mapping_json FROM course_revisions WHERE course_id=? AND number=?",params![course,revision],
            |r|Ok((r.get(0)?,r.get(1)?))).optional()?.ok_or_else(||StorageError::new("OBJECT_NOT_FOUND"))?;
        let package = load_json(&stored)?;
        let mapping = load_json(&mapped)?;
        let candidate = package["lessons"]
            .as_array()
            .into_iter()
            .flatten()
            .find_map(|lesson| {
                let lid = lesson["id"].as_str()?;
                lesson["exercises"].as_array()?.iter().find(|e| {
                    e["id"]
                        .as_str()
                        .is_some_and(|eid| mapping["exercises"][format!("{lid}:{eid}")] == exercise)
                })
            })
            .filter(|candidate| question_fingerprint(candidate) == question_hash)
            .ok_or_else(|| StorageError::new("REFERENCE_MISMATCH"))?;
        candidate["review_reference"].clone()
    } else {
        question["review_reference"].clone()
    };
    if reference.is_null() {
        return Ok(
            json!({"available":false,"reason":"这道题尚未配置答案解析。","content_revision":revision,"question_hash":question_hash}),
        );
    }
    let digest = reference_fingerprint(&reference, &question_hash);
    let used:bool = db.query_row("SELECT EXISTS(SELECT 1 FROM course_reference_views WHERE study_session_id=? AND exercise_id=?)",params![study,exercise],|r|r.get(0))?;
    let render = |key: &str| documents::render(reference[key].as_str().unwrap_or_default(), false);
    Ok(
        json!({"available":true,"study_session_id":study,"exercise_id":exercise,"course_id":course,"content_revision":revision,
        "frozen_content_revision":original,"question_hash":question_hash,"reference_hash":digest,"reference":reference,
        "rendered":{"answer":render("answer")?,"explanation":render("explanation")?},"is_correction":revision!=original,
        "hint_used":used,"hint_information":if hint_tracking {"recorded_since_1.8"} else {"legacy_unknown"}}),
    )
}

pub fn view(db: &Connection, request: ReferenceRequest<'_>) -> Result<Value, StorageError> {
    let mut value = resolve(db, request)?;
    if value["available"] == true {
        let study = value["study_session_id"].as_str().unwrap();
        let exercise = value["exercise_id"].as_str().unwrap();
        let digest = value["reference_hash"].as_str().unwrap();
        if db.execute("INSERT INTO course_reference_views(study_session_id,exercise_id,reference_hash) VALUES(?,?,?) ON CONFLICT DO NOTHING",params![study,exercise,digest])?==1 {
            let old_event:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM event_logs WHERE source='USER_ENGINE' AND object_type='course_study' AND object_id=? AND action='VIEW_REFERENCE' AND summary=?)",params![study,exercise],|r|r.get(0))?;
            let summary = if old_event {format!("{exercise}:{digest}")} else {exercise.to_owned()};
            events::record(db,"USER_ENGINE","course_study",study,"VIEW_REFERENCE",&summary)?;
        }
        value["hint_used"] = json!(true);
    }
    Ok(value)
}
