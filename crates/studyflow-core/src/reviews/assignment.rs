use std::collections::{HashMap, HashSet};

use rusqlite::{named_params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};

use super::effective_attempts;
use crate::{
    infrastructure::StorageError,
    learning::{study_sessions, submissions},
};

const ACTIVE: &[&str] = &["WAITING_REVIEW", "NEEDS_REVISION", "RETEST_REQUIRED"];
const PAST: &[&str] = &["PASSED", "REVIEWED", "RECHECKED"];

pub fn summary(db: &Connection, input: &Value) -> Result<Value, StorageError> {
    let role = input
        .get("role")
        .map_or(Some("all"), Value::as_str)
        .filter(|value| matches!(*value, "all" | "agent" | "learner"))
        .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?;
    let limit = input
        .get("limit")
        .map_or(Some(50), Value::as_u64)
        .filter(|count| (1..=100).contains(count))
        .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))? as usize;
    let status = input["status"].as_str().filter(|value| !value.is_empty());
    let cursor = input["cursor"].as_str().unwrap_or_default();
    let statuses = if input["history"] == true {
        PAST
    } else {
        ACTIVE
    };
    if status.is_some_and(|status| !ACTIVE.contains(&status) && !PAST.contains(&status))
        || cursor.chars().count() > 64
    {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let included: HashSet<String> = effective_attempts(db)?
        .into_iter()
        .map(|attempt| attempt.id)
        .collect();
    let mut query=db.prepare("SELECT s.id,s.status,s.version,c.id,c.title,c.plan_line_id,l.id,l.title,e.id,e.title,s.study_session_id,s.batch_id,s.attempt_number,s.attempt_kind,s.next_action,EXISTS(SELECT 1 FROM retest_tasks t WHERE t.parent_submission_id=s.id)
        FROM submissions s JOIN exercises e ON e.id=s.exercise_id JOIN lessons l ON l.id=e.lesson_id JOIN courses c ON c.id=l.course_id
        LEFT JOIN course_study_sessions r ON r.id=s.study_session_id
        WHERE (:plan IS NULL OR c.plan_line_id=:plan) AND (:course IS NULL OR c.id=:course) AND (:status IS NULL OR s.status=:status)
        AND NOT EXISTS(SELECT 1 FROM submissions child WHERE child.parent_submission_id=s.id AND child.status<>'DRAFT')
        AND (:history OR (r.abandoned_at IS NULL AND (s.study_session_id IS NOT NULL OR NOT EXISTS(SELECT 1 FROM course_study_sessions rounds WHERE rounds.course_id=c.id AND rounds.revision>=2))))
        ORDER BY s.id")?;
    let mut counts = Map::new();
    let plan = input["plan_line_id"]
        .as_str()
        .filter(|value| !value.is_empty());
    let course = input["course_id"]
        .as_str()
        .filter(|value| !value.is_empty());
    let mut items = Vec::new();
    let mut scanned = query.query(named_params!{":plan":plan,":course":course,":status":status,":history":input["history"]==true})?;
    let mut has_more = false;
    let mut frozen = HashMap::new();
    while let Some(row) = scanned.next()? {
        let id: String = row.get(0)?;
        let status: String = row.get(1)?;
        if !included.contains(&id) || !statuses.contains(&status.as_str()) {
            continue;
        }
        let task: bool = row.get(15)?;
        let (action, label) = match status.as_str() {
            "WAITING_REVIEW" => ("REVIEW", "等待Agent批改"),
            "NEEDS_REVISION" => ("REVISE", "需要修正"),
            "RETEST_REQUIRED" if task => ("RETEST", "开始复测"),
            "RETEST_REQUIRED" => ("PUBLISH_RETEST", "等待Agent出题"),
            _ => ("VIEW_HISTORY", "已通过历史"),
        };
        if role == "agent" && !matches!(action, "REVIEW" | "PUBLISH_RETEST")
            || role == "learner" && !matches!(action, "REVISE" | "RETEST")
        {
            continue;
        }
        let count = counts.entry(status.clone()).or_insert(json!(0));
        *count = json!(count.as_u64().unwrap() + 1);
        if id.as_str() <= cursor {
            continue;
        }
        if items.len() >= limit {
            has_more = true;
            continue;
        }
        let study: Option<String> = row.get(10)?;
        let exercise: String = row.get(8)?;
        let mut item = json!({"id":id,"status":status,"version":row.get::<_,i64>(2)?,"action":action,"kind":action,"label":label,
            "course_id":row.get::<_,String>(3)?,"course_title":row.get::<_,String>(4)?,"plan_line_id":row.get::<_,Option<String>>(5)?,
            "lesson_id":row.get::<_,String>(6)?,"lesson_title":row.get::<_,String>(7)?,"exercise_id":exercise,"exercise_title":row.get::<_,String>(9)?,
            "study_session_id":study,"batch_id":row.get::<_,Option<String>>(11)?,"attempt_number":row.get::<_,i64>(12)?,"attempt_kind":row.get::<_,String>(13)?,"next_action":row.get::<_,String>(14)?});
        if let Some(study) = study {
            let round = match frozen.entry(study.clone()) {
                std::collections::hash_map::Entry::Occupied(entry) => entry.into_mut(),
                std::collections::hash_map::Entry::Vacant(entry) => {
                    entry.insert(study_sessions::require(db, &study, None, false)?)
                }
            };
            for lesson in round.snapshot["lessons"].as_array().into_iter().flatten() {
                if let Some(question) = lesson["exercises"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .find(|question| question["id"] == exercise)
                {
                    item["course_title"] = round.snapshot["course"]["title"].clone();
                    item["lesson_title"] = lesson["title"].clone();
                    item["exercise_title"] = question["title"].clone();
                    break;
                }
            }
        }
        items.push(item);
    }
    let next = if has_more {
        items.last().map(|row| &row["id"])
    } else {
        None
    };
    Ok(json!({"items":items,"counts":counts,"next_cursor":next,"limit":limit,"role":role}))
}

pub fn context(db: &Connection, input: &Value) -> Result<Value, StorageError> {
    let ids = input["submission_ids"]
        .as_array()
        .filter(|ids| (1..=100).contains(&ids.len()) && ids.iter().all(Value::is_string))
        .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?;
    let mut contexts = Map::new();
    let mut items = Vec::new();
    let mut seen = HashSet::new();
    for id in ids
        .iter()
        .filter_map(Value::as_str)
        .filter(|id| seen.insert(*id))
    {
        let mut detail = submissions::detail(db, id, true)?;
        let mut frozen = detail
            .as_object_mut()
            .unwrap()
            .remove("study_context")
            .unwrap_or_default();
        let lesson = detail["lesson"]["id"].as_str().unwrap_or_default();
        let key = if let Some(study) = frozen["study_session_id"].as_str() {
            format!("{study}:{lesson}")
        } else {
            format!("legacy:{lesson}")
        };
        contexts.entry(key.clone()).or_insert_with(||{
            if let Some(fields)=frozen.as_object_mut() {fields.remove("exercise"); frozen} else {
                json!({"snapshot_status":"LEGACY_UNVERSIONED","lesson":detail["lesson"],"course":detail["course"]})
            }
        });
        if let Some(task) = detail["retest_task_id"].as_str() {
            let agent_reference: Option<String> = db
                .query_row(
                    "SELECT agent_reference FROM retest_tasks WHERE id=?",
                    [task],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(agent_reference) = agent_reference {
                detail["agent_reference"] = json!(agent_reference);
            }
        }
        detail["context_id"] = json!(key);
        items.push(detail);
    }
    Ok(json!({"items":items,"contexts":contexts}))
}
