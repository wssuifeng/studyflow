use serde_json::{json, Map, Value};

use crate::infrastructure::fingerprint::JsonFingerprint::{Ascii, Utf8};

/// The domain validates answer fields before this function constructs the
/// persisted hash. Historically nullable fields contribute even when omitted.
pub fn course_answers(
    course_id: &str,
    study_id: Option<&str>,
    source: &str,
    operation: &str,
    answers: &[Value],
) -> String {
    let mut rows: Vec<_> = answers.iter().collect();
    rows.sort_by_key(|row| row["exercise_id"].as_str());
    let rows: Vec<Value> = rows
        .into_iter()
        .map(|row| {
            let mut fields: Map<String, Value> = [
                "exercise_id",
                "answer_text",
                "submission_id",
                "expected_version",
                "parent_submission_id",
                "task_id",
            ]
            .into_iter()
            .map(|field| (field.to_owned(), row[field].clone()))
            .collect();
            if !row["retest_task_id"].is_null() {
                fields.insert("retest_task_id".into(), row["retest_task_id"].clone());
            }
            Value::Object(fields)
        })
        .collect();
    let mut payload = json!({
        "course_id": course_id, "source": source, "operation": operation, "answers": rows,
    });
    if let Some(study_id) = study_id {
        payload["study_session_id"] = json!(study_id);
    }
    Ascii.hash(&payload)
}

pub fn open_study(
    course_id: &str,
    plan_id: Option<&str>,
    new_version: bool,
    review_round: bool,
) -> String {
    let mut payload = json!({"course_id": course_id, "new_version": new_version});
    if let Some(plan_id) = plan_id {
        payload["plan_line_id"] = json!(plan_id);
    }
    if review_round {
        payload["review_round"] = Value::Bool(true);
    }
    Ascii.hash(&payload)
}

pub fn english_save(
    study: &str,
    exercise: &str,
    text: &str,
    version: i64,
    skipped: bool,
) -> String {
    Ascii.hash(&json!({
        "study_session_id": study, "exercise_id": exercise, "answer_text": text,
        "expected_version": version, "skipped": skipped,
    }))
}

pub fn study_note(study: &str, lesson: &str, text: &str, version: i64) -> String {
    Utf8.hash(&json!([study, lesson, text, version]))
}
