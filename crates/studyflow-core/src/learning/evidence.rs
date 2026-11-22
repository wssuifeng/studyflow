use std::collections::HashSet;

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use super::{
    attempt_history::scoped_summaries,
    study_sessions::{outcome, require},
};
use crate::infrastructure::StorageError;

pub fn read(
    db: &Connection,
    plan: &str,
    course: Option<&str>,
    mode: Option<&str>,
    limit: usize,
    cursor: Option<&str>,
) -> Result<Value, StorageError> {
    if !(1..=100).contains(&limit)
        || mode.is_some_and(|value| !matches!(value, "general" | "english"))
    {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    if !db.query_row(
        "SELECT EXISTS(SELECT 1 FROM plan_lines WHERE id=?)",
        [plan],
        |row| row.get::<_, bool>(0),
    )? {
        return Err(StorageError::new("OBJECT_NOT_FOUND"));
    }
    let timestamp: Option<String> = cursor
        .filter(|id| !id.is_empty())
        .map(|id| {
            db.query_row(
                "SELECT created_at FROM course_study_sessions WHERE id=?",
                [id],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))
        })
        .transpose()?;
    let mut query = db.prepare("SELECT id,created_at,hint_tracking_enabled FROM course_study_sessions
        WHERE course_id IN (SELECT course_id FROM plan_course_items WHERE plan_line_id=?1) AND (?2 IS NULL OR course_id=?2)
        AND (?3 IS NULL OR created_at<?3 OR (created_at=?3 AND id<?4)) ORDER BY created_at DESC,id DESC LIMIT ?5")?;
    let rows = query
        .query_map(
            params![
                plan,
                course.filter(|id| !id.is_empty()),
                timestamp,
                cursor,
                (limit + 1) as i64
            ],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, bool>(2)?,
                ))
            },
        )?
        .collect::<Result<Vec<_>, _>>()?;
    let mut hint_query =
        db.prepare("SELECT exercise_id FROM course_reference_views WHERE study_session_id=?")?;
    let mut items = Vec::new();
    for (id, created, tracking) in rows.iter().take(limit) {
        let round = require(db, id, None, false)?;
        let frozen = &round.snapshot["course"];
        let learning_mode = frozen["learning_mode"].as_str().unwrap_or("general");
        if frozen["plan_line_id"] != plan || mode.is_some_and(|value| value != learning_mode) {
            continue;
        }
        let ids = round.ids();
        let attempts = scoped_summaries(db, &ids, Some(round.scope()), false)?;
        let hints = hint_query
            .query_map([id], |row| row.get::<_, String>(0))?
            .collect::<Result<HashSet<_>, _>>()?;
        let sample: Vec<_> = ids.iter().take(20).map(|id| {
            let result = attempts.get(id).and_then(|pair|pair.0.as_ref());
            json!({"exercise_id":id,"status":result.map_or("NOT_SUBMITTED",|row|row["status"].as_str().unwrap()),
                "attempt_kind":result.map(|row|&row["attempt_kind"]),"submission_id":result.map(|row|&row["id"]),"hint_used":tracking.then(||hints.contains(id))})
        }).collect();
        let mut item = outcome(&round, &ids, &attempts);
        item.as_object_mut().unwrap().extend(json!({"study_session_id":id,"course_id":round.course,"plan_line_id":plan,"learning_mode":learning_mode,
            "content_revision":frozen["content_revision"],"snapshot_hash":round.hash,"created_at":created.replacen(' ',"T",1),"abandoned":round.abandoned.is_some(),
            "hint_information":if *tracking {"recorded_since_1.8"} else {"legacy_unknown"},"hinted_exercise_count":hints.len(),"mastery":"not_inferred",
            "exercise_count":ids.len(),"exercise_sample":sample,"exercise_sample_truncated":ids.len()>20}).as_object().unwrap().clone());
        items.push(item);
    }
    let next = (rows.len() > limit).then(|| &rows[limit - 1].0);
    Ok(
        json!({"items":items,"scanned":limit.min(rows.len()),"next_cursor":next,"scope":{"plan_line_id":plan,"course_id":course,"learning_mode":mode},
        "note":"首次、修正、复测和提示是证据，不自动等同独立掌握；更多题面按ID读取。"}),
    )
}
