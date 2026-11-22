use std::collections::{HashMap, HashSet};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::Value;

use crate::infrastructure::StorageError;

pub fn passed(status: &str) -> bool {
    matches!(status, "PASSED" | "REVIEWED" | "RECHECKED")
}

pub(crate) struct Submission {
    pub(crate) id: String,
    pub(crate) exercise: String,
    pub(crate) status: String,
    pub(crate) parent: Option<String>,
}

pub(crate) fn effective(
    db: &Connection,
    attempts: Vec<Submission>,
) -> Result<Vec<Submission>, StorageError> {
    let mut children: HashMap<&str, Vec<&str>> = HashMap::new();
    for row in &attempts {
        if let Some(parent) = row.parent.as_deref() {
            children.entry(parent).or_default().push(&row.id);
        }
    }
    let mut excluded = HashSet::new();
    let mut queue = Vec::new();
    for (&parent, edges) in children.iter().filter(|(_, edges)| edges.len() > 1) {
        let chosen: String = db
            .query_row(
                "SELECT child_id FROM submission_chain_links WHERE parent_id=?",
                [parent],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| StorageError::new("SUBMISSION_BRANCH_CONFLICT"))?;
        queue.extend(edges.iter().copied().filter(|child| *child != chosen));
    }
    while let Some(id) = queue.pop() {
        if excluded.insert(id.to_owned()) {
            if let Some(edges) = children.get(id) {
                queue.extend(edges.iter().copied());
            }
        }
    }
    Ok(attempts
        .into_iter()
        .filter(|row| !excluded.contains(&row.id))
        .collect())
}

pub fn latest_statuses(
    db: &Connection,
    exercises: &[String],
    scope: Option<(&str, i64)>,
) -> Result<HashMap<String, String>, StorageError> {
    if exercises.is_empty() {
        return Ok(HashMap::new());
    }
    let (session, legacy) = scope.map_or((None, false), |(id, revision)| (Some(id), revision == 1));
    let exercises = serde_json::to_string(exercises).expect("exercise IDs encode as JSON");
    let mut query = db.prepare(
        "SELECT id,exercise_id,status,parent_submission_id FROM submissions
         WHERE status<>'DRAFT' AND exercise_id IN (SELECT value FROM json_each(?))
         AND (?1 IS NOT NULL) AND (?2 IS NULL OR study_session_id=?2 OR (?3 AND study_session_id IS NULL))
         ORDER BY attempt_number,created_at,id",
    )?;
    let attempts = query
        .query_map(params![exercises, session, legacy], |row| {
            Ok(Submission {
                id: row.get(0)?,
                exercise: row.get(1)?,
                status: row.get(2)?,
                parent: row.get(3)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(effective(db, attempts)?
        .into_iter()
        .map(|row| (row.exercise, row.status))
        .collect())
}

pub(crate) fn frozen_exercise_ids(snapshot: &Value) -> Vec<String> {
    snapshot["lessons"]
        .as_array()
        .into_iter()
        .flatten()
        .flat_map(|lesson| lesson["exercises"].as_array().into_iter().flatten())
        .filter_map(|exercise| exercise["id"].as_str().map(str::to_owned))
        .collect()
}

pub(crate) const SUMMARY_COLUMNS: &str = "id,exercise_id,status,parent_submission_id,task_id,version,attempt_number,attempt_kind,next_action,study_session_id,batch_id,retest_task_id";

pub(crate) fn summary(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    Ok(
        serde_json::json!({"id":row.get::<_,String>(0)?,"exercise_id":row.get::<_,String>(1)?,"status":row.get::<_,String>(2)?,"parent_submission_id":row.get::<_,Option<String>>(3)?,
        "task_id":row.get::<_,Option<String>>(4)?,"version":row.get::<_,i64>(5)?,"attempt_number":row.get::<_,i64>(6)?,
        "attempt_kind":row.get::<_,String>(7)?,"next_action":row.get::<_,String>(8)?,"study_session_id":row.get::<_,Option<String>>(9)?,
        "batch_id":row.get::<_,Option<String>>(10)?,"retest_task_id":row.get::<_,Option<String>>(11)?}),
    )
}

pub(crate) type Latest = HashMap<String, (Option<Value>, Option<Value>)>;

pub(crate) fn latest_summaries(
    db: &Connection,
    exercises: &[String],
) -> Result<Latest, StorageError> {
    scoped_summaries(db, exercises, None, false)
}

pub(crate) fn scoped_summaries(
    db: &Connection,
    exercises: &[String],
    scope: Option<(&str, i64)>,
    include_draft_branches: bool,
) -> Result<Latest, StorageError> {
    let serialized = serde_json::to_string(exercises).expect("exercise IDs encode as JSON");
    let (session, legacy) = scope.map_or((None, false), |(id, revision)| (Some(id), revision == 1));
    let mut query = db.prepare(&format!("SELECT {SUMMARY_COLUMNS} FROM submissions WHERE exercise_id IN (SELECT value FROM json_each(?1))
        AND (?2 IS NULL OR study_session_id=?2 OR (?3 AND study_session_id IS NULL)) ORDER BY attempt_number,created_at,id"))?;
    let mut rows = query.query(params![serialized, session, legacy])?;
    let mut formal = Vec::new();
    let mut all = Vec::new();
    let mut summaries = HashMap::new();
    let mut result: Latest = HashMap::new();
    while let Some(row) = rows.next()? {
        let item = Submission {
            id: row.get(0)?,
            exercise: row.get(1)?,
            status: row.get(2)?,
            parent: row.get(3)?,
        };
        if item.status != "DRAFT" {
            formal.push(Submission {
                id: item.id.clone(),
                exercise: item.exercise.clone(),
                status: item.status.clone(),
                parent: item.parent.clone(),
            });
        }
        summaries.insert(item.id.clone(), summary(row)?);
        all.push(item);
    }
    if !include_draft_branches {
        for item in effective(db, formal)? {
            result.entry(item.exercise).or_default().0 = Some(summaries[&item.id].clone());
        }
    }
    for item in effective(db, all)? {
        let pair = result.entry(item.exercise).or_default();
        if item.status == "DRAFT" {
            pair.1 = summaries.remove(&item.id);
        } else if include_draft_branches {
            pair.0 = summaries.remove(&item.id);
        } else if scope.is_some() {
            pair.1 = None;
        }
    }
    Ok(result)
}
