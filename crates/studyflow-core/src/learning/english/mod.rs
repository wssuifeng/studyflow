use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use super::{
    english_check,
    study_sessions::{self, Round},
    submissions,
};
use crate::{infrastructure::StorageError, planning};

mod answers;
mod mistakes;
pub mod retest;

pub(crate) use answers::{check, navigate, request_review, reveal, save, submit};

pub(crate) fn context(db: &Connection, study: &str, active: bool) -> Result<Round, StorageError> {
    let round = study_sessions::require(db, study, None, active)?;
    if round.snapshot["course"]["learning_mode"] != "english" {
        return Err(StorageError::new("COURSE_MODE_MISMATCH"));
    }
    Ok(round)
}

pub(super) fn items(round: &Round) -> impl Iterator<Item = (&Value, &Value)> {
    round.snapshot["lessons"]
        .as_array()
        .into_iter()
        .flatten()
        .flat_map(|lesson| {
            lesson["exercises"]
                .as_array()
                .into_iter()
                .flatten()
                .map(move |item| (lesson, item))
        })
}

fn item<'a>(round: &'a Round, exercise: &str) -> Result<&'a Value, StorageError> {
    items(round)
        .find(|(_, item)| item["id"] == exercise)
        .map(|(_, item)| item)
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))
}

fn spec(item: &Value) -> Result<&Value, StorageError> {
    item.get("english")
        .filter(|spec| spec.is_object())
        .ok_or_else(|| StorageError::new("COURSE_ITEM_TYPE_MISMATCH"))
}

#[derive(Default)]
struct State {
    position: i64,
    version: i64,
    completed: bool,
}

fn state(db: &Connection, study: &str) -> Result<State, StorageError> {
    Ok(db
        .query_row(
            "SELECT position,version,completed FROM english_study_states WHERE study_session_id=?",
            [study],
            |row| {
                Ok(State {
                    position: row.get(0)?,
                    version: row.get(1)?,
                    completed: row.get(2)?,
                })
            },
        )
        .optional()?
        .unwrap_or_default())
}

fn initialize(db: &Connection, round: &Round) -> Result<(), StorageError> {
    db.execute("INSERT INTO english_study_states(study_session_id,plan_line_id,position,version,completed) VALUES(?,?,0,1,0) ON CONFLICT(study_session_id) DO NOTHING",
        params![round.id,round.snapshot["course"]["plan_line_id"].as_str()])?;
    Ok(())
}

fn latest(db: &Connection, study: &str, exercise: &str) -> Result<Option<Value>, StorageError> {
    let id:Option<String>=db.query_row("SELECT id FROM submissions WHERE study_session_id=? AND exercise_id=? AND retest_task_id IS NULL ORDER BY attempt_number DESC,created_at DESC,id DESC LIMIT 1",params![study,exercise],|row|row.get(0)).optional()?;
    id.map(|id| submissions::summary_by_id(db, &id))
        .transpose()
        .map(Option::flatten)
}

fn body(db: &Connection, submission: &str) -> Result<String, StorageError> {
    Ok(db.query_row(
        "SELECT answer_text FROM submissions WHERE id=?",
        [submission],
        |row| row.get(0),
    )?)
}

struct Feedback {
    checked: Value,
    assisted: bool,
    skipped: bool,
}

fn feedback(db: &Connection, submission: Option<&str>) -> Result<Feedback, StorageError> {
    let row = if let Some(id) = submission {
        db.query_row("SELECT a.result_json,d.assisted,d.skipped FROM english_submission_details d LEFT JOIN english_check_attempts a ON a.id=d.last_attempt_id WHERE d.submission_id=?",[id],
            |row|Ok((row.get::<_,Option<String>>(0)?,row.get::<_,bool>(1)?,row.get::<_,bool>(2)?))).optional()?
    } else {
        None
    };
    let (text, assisted, skipped) = row.unwrap_or_default();
    Ok(Feedback {
        checked: text
            .map(|text| serde_json::from_str(&text))
            .transpose()
            .map_err(|err| StorageError::caused_by("DATABASE_ERROR", err))?
            .unwrap_or(Value::Null),
        assisted,
        skipped,
    })
}

pub fn get(db: &Connection, root: &std::path::Path, study: &str) -> Result<Value, StorageError> {
    let round = context(db, study, false)?;
    let state = state(db, study)?;
    let mut rows = Vec::new();
    for (lesson, item) in items(&round) {
        let exercise = item["id"].as_str().unwrap();
        let row = latest(db, study, exercise)?.unwrap_or(Value::Null);
        let submission = row["id"].as_str();
        let feedback = feedback(db, submission)?;
        let spec = item.get("english");
        let text = if spec.is_some() || item["type"] == "ESSAY" {
            submission
                .map(|id| body(db, id))
                .transpose()?
                .unwrap_or_default()
        } else {
            String::new()
        };
        let mut view = json!({"exercise_id":exercise,"lesson_id":lesson["id"],"title":item["title"],"prompt":item["prompt"],"group_title":lesson["title"],
            "kind":if spec.is_some() {"tokens"} else {item["type"].as_str().unwrap()},"answer_text":text,"answer_version":row["version"].as_i64().unwrap_or(0),
            "submission_id":submission,"status":row["status"].as_str().unwrap_or("NOT_STARTED"),"matched":feedback.checked["matched"].as_bool().unwrap_or(false),
            "differences":feedback.checked["differences"].as_array().map(Vec::as_slice).unwrap_or_default(),"assisted":feedback.assisted,"skipped":feedback.skipped});
        if let Some(spec) = spec {
            let counts: Vec<_> = english_check::variants(spec)
                .map(|variant| english_check::tokens(variant).len())
                .collect();
            view.as_object_mut().unwrap().extend(json!({"progression":spec["progression"],"token_count":counts.first(),"min_token_count":counts.iter().min(),"max_token_count":counts.iter().max(),
                "error_count":feedback.checked["error_count"].as_i64().unwrap_or(0),"evaluation_mode":spec["evaluation_mode"].as_str().unwrap_or("local_exact"),
                "objective_ids":spec["objective_ids"].as_array().map(Vec::as_slice).unwrap_or_default()}).as_object().unwrap().clone());
        } else if item["type"] == "ESSAY" {
            view["essay"] = item.get("essay").cloned().unwrap_or_else(|| json!({}));
            view["requirements"] = item["requirements"].clone();
        }
        rows.push(view);
    }
    let mut course = round.snapshot["course"].clone();
    planning::add_membership(db, &round.course, &mut course)?;
    let version: Option<i64> = db
        .query_row(
            "SELECT version FROM courses WHERE id=?",
            [&round.course],
            |row| row.get(0),
        )
        .optional()?;
    course["source_changed"] = json!(course["content_revision"]
        .as_i64()
        .is_some_and(|rev| rev != 0 && version.is_some_and(|live| live != rev)));
    let groups:Vec<_>=round.snapshot["lessons"].as_array().unwrap().iter().map(|lesson|json!({"lesson_id":lesson["id"],"title":lesson["title"],"summary":lesson["summary"].as_str().unwrap_or_default(),
        "blocks":lesson["content_blocks"].as_array().map(Vec::as_slice).unwrap_or_default()})).collect();
    let digest = crate::audio::assets::digest(root.to_string_lossy().as_bytes());
    Ok(
        json!({"workspace_key":&digest[..16],"content_hash":round.hash,"course":course,"study_session_id":study,"revision":round.revision,
        "position":state.position,"state_version":state.version,"completed":state.completed,"items":rows,"groups":groups}),
    )
}

fn reference(spec: &Value) -> Value {
    let target = spec["target"].as_str().unwrap_or_default();
    json!({"target":target,"tokens":english_check::tokens(target),"phonetic":spec["phonetic"].as_str().unwrap_or_default(),"gloss":spec["gloss"].as_str().unwrap_or_default(),
        "explanation":spec["explanation"].as_str().unwrap_or_default(),"sentence_parts":spec["sentence_parts"].as_array().map(Vec::as_slice).unwrap_or_default()})
}

pub fn answer(db: &Connection, study: &str, exercise: &str) -> Result<Value, StorageError> {
    let round = context(db, study, false)?;
    let spec = spec(item(&round, exercise)?)?;
    let row = latest(db, study, exercise)?.unwrap_or(Value::Null);
    let feedback = feedback(db, row["id"].as_str())?;
    if !matches!(
        row["status"].as_str(),
        Some("PASSED" | "RECHECKED" | "REVIEWED")
    ) && !feedback.assisted
        && feedback.checked["matched"] != true
    {
        return Err(StorageError::new("REFERENCE_HIDDEN"));
    }
    Ok(reference(spec))
}
