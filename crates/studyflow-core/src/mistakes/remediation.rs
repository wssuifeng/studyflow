use std::{collections::HashSet, path::Path};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use crate::{
    infrastructure::StorageError,
    learning::{attempt_history, english, study_sessions},
};

fn invalid() -> StorageError {
    StorageError::new("INVALID_ARGUMENT")
}

pub(crate) fn freeze_sources(
    db: &Connection,
    plan: &str,
    sources: &[Value],
) -> Result<Vec<Value>, StorageError> {
    let mut seen = HashSet::new();
    let mut frozen = Vec::with_capacity(sources.len());
    for source in sources {
        if !source.as_object().is_some_and(|object| object.len() == 3) {
            return Err(invalid());
        }
        let aggregate = source["aggregate_id"]
            .as_str()
            .filter(|id| !id.is_empty() && id.chars().count() <= 100)
            .ok_or_else(invalid)?;
        if !seen.insert(aggregate) {
            return Err(invalid());
        }
        let version = source["expected_version"]
            .as_i64()
            .filter(|v| *v >= 1)
            .ok_or_else(invalid)?;
        let (scope,domain,course,current,rule,archived)=db.query_row("SELECT b.plan_line_id,b.domain,a.course_id,a.version,a.rule_hash,a.archived FROM english_error_aggregates a JOIN mistake_notebooks b ON b.id=a.notebook_id WHERE a.id=?",[aggregate],|row|Ok((row.get::<_,Option<String>>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?,row.get::<_,i64>(3)?,row.get::<_,String>(4)?,row.get::<_,bool>(5)?))).optional()?.ok_or_else(||StorageError::new("OBJECT_NOT_FOUND"))?;
        if scope.as_deref() != Some(plan) || domain != "english" {
            return Err(StorageError::new("SCOPE_MISMATCH"));
        }
        if archived {
            return Err(StorageError::new("SOURCE_ARCHIVED"));
        }
        if current != version {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        let evidence = source["evidence_ids"]
            .as_array()
            .filter(|ids| (1..=10).contains(&ids.len()))
            .ok_or_else(invalid)?;
        let mut ids = Vec::with_capacity(evidence.len());
        for id in evidence {
            let id = id.as_str().ok_or_else(invalid)?;
            if ids.contains(&id) {
                return Err(invalid());
            }
            let valid = db
                .query_row(
                    "SELECT valid_error FROM english_error_evidence WHERE id=? AND aggregate_id=?",
                    params![id, aggregate],
                    |row| row.get::<_, bool>(0),
                )
                .optional()?
                .ok_or_else(|| StorageError::new("SCOPE_MISMATCH"))?;
            if !valid {
                return Err(StorageError::new("SOURCE_NOT_VALID_ERROR"));
            }
            ids.push(id);
        }
        ids.sort_unstable();
        frozen.push(json!({"aggregate_id":aggregate,"source_version":version,"rule_hash":rule,"source_course_id":course,"evidence_ids":ids}));
    }
    Ok(frozen)
}

pub fn get(
    db: &Connection,
    root: &Path,
    course: &str,
    include_sources: bool,
) -> Result<Value, StorageError> {
    let (title,summary,plan,objectives,rationale)=db.query_row("SELECT c.title,c.summary,p.plan_line_id,p.objective_ids_json,p.rationale FROM english_remediation_courses p JOIN courses c ON c.id=p.course_id WHERE p.course_id=?",[course],|row|Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?,row.get::<_,String>(3)?,row.get::<_,String>(4)?))).optional()?.ok_or_else(||StorageError::new("OBJECT_NOT_FOUND"))?;
    let objectives: Value = serde_json::from_str(&objectives)
        .map_err(|err| StorageError::caused_by("DATABASE_ERROR", err))?;
    let mut result = json!({"course_id":course,"title":title,"summary":summary,"plan_line_id":plan,"track":"SUPPLEMENT","objective_ids":objectives,"rationale":rationale,"learning_status":"NOT_STARTED","study_session_id":null,"auto_resolves_original_errors":false,"transfer_status":"NOT_ATTEMPTED","transfer_total":0,"transfer_unassisted_passed":0});
    if let Some(study) = study_sessions::current(db, course)? {
        let view = english::get(db, root, &study.id)?;
        let mut assisted=db.prepare("SELECT DISTINCT s.exercise_id FROM submissions s JOIN english_submission_details d ON d.submission_id=s.id WHERE s.study_session_id=? AND s.retest_task_id IS NULL AND d.assisted=1")?;
        let assisted = assisted
            .query_map([&study.id], |row| row.get::<_, String>(0))?
            .collect::<Result<HashSet<_>, _>>()?;
        let mut total = 0;
        let mut passed = 0;
        let mut independent = 0;
        for item in view["items"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|item| item["progression"]["stage"] == "transfer")
        {
            total += 1;
            if item["matched"] == true
                || attempt_history::passed(item["status"].as_str().unwrap_or_default())
            {
                passed += 1;
                if item["assisted"] != true
                    && !assisted.contains(item["exercise_id"].as_str().unwrap_or_default())
                {
                    independent += 1;
                }
            }
        }
        result["study_session_id"] = json!(study.id);
        let completed = db
            .query_row(
                "SELECT completed FROM english_study_states WHERE study_session_id=?",
                [&study.id],
                |row| row.get::<_, bool>(0),
            )
            .optional()?
            .unwrap_or(false);
        result["learning_status"] = json!(if completed {
            "COMPLETED"
        } else {
            "IN_PROGRESS"
        });
        result["transfer_total"] = json!(total);
        result["transfer_unassisted_passed"] = json!(independent);
        result["transfer_status"] = json!(if total > 0 && total == independent {
            "UNASSISTED_PASS"
        } else if total > 0 && total == passed {
            "ASSISTED_PASS"
        } else {
            "PENDING"
        });
    }
    if include_sources {
        let mut query=db.prepare("SELECT s.aggregate_id,s.evidence_id,s.source_version,s.rule_hash,a.course_id,c.title,a.version,e.valid_error,a.archived FROM english_remediation_sources s JOIN english_error_aggregates a ON a.id=s.aggregate_id JOIN english_error_evidence e ON e.id=s.evidence_id JOIN courses c ON c.id=a.course_id WHERE s.course_id=? ORDER BY s.id")?;
        let sources=query.query_map([course],|row|Ok(json!({"aggregate_id":row.get::<_,String>(0)?,"evidence_id":row.get::<_,String>(1)?,"source_version":row.get::<_,i64>(2)?,"rule_hash":row.get::<_,String>(3)?,"source_course_id":row.get::<_,String>(4)?,"source_course_title":row.get::<_,String>(5)?,"current_version":row.get::<_,i64>(6)?,"evidence_still_valid":row.get::<_,bool>(7)?,"archived":row.get::<_,bool>(8)?})))?.collect::<Result<Vec<_>,_>>()?;
        result["sources"] = json!(sources);
    }
    Ok(result)
}

pub fn list(db: &Connection, root: &Path, input: &Value) -> Result<Value, StorageError> {
    let plan = input["plan_line_id"]
        .as_str()
        .filter(|id| !id.is_empty())
        .ok_or_else(invalid)?;
    if !db.query_row(
        "SELECT EXISTS(SELECT 1 FROM plan_lines WHERE id=?)",
        [plan],
        |row| row.get::<_, bool>(0),
    )? {
        return Err(StorageError::new("OBJECT_NOT_FOUND"));
    }
    let source = input["source_course_id"]
        .as_str()
        .filter(|id| !id.is_empty());
    let aggregate = input["aggregate_id"].as_str().filter(|id| !id.is_empty());
    let limit = input
        .get("limit")
        .map_or(Some(30), Value::as_i64)
        .filter(|limit| (1..=100).contains(limit))
        .ok_or_else(invalid)?;
    let offset = input
        .get("offset")
        .map_or(Some(0), Value::as_i64)
        .filter(|offset| (0..=100_000).contains(offset))
        .ok_or_else(invalid)?;
    let scope="FROM english_remediation_courses p WHERE p.plan_line_id=?1 AND ((?2 IS NULL AND ?3 IS NULL) OR EXISTS(SELECT 1 FROM english_remediation_sources s JOIN english_error_aggregates a ON a.id=s.aggregate_id WHERE s.course_id=p.course_id AND (?2 IS NULL OR a.course_id=?2) AND (?3 IS NULL OR a.id=?3)))";
    let total: i64 = db.query_row(
        &format!("SELECT COUNT(*) {scope}"),
        params![plan, source, aggregate],
        |row| row.get(0),
    )?;
    let mut query = db.prepare(&format!(
        "SELECT p.course_id {scope} ORDER BY p.created_at,p.course_id LIMIT ?4 OFFSET ?5"
    ))?;
    let courses = query
        .query_map(params![plan, source, aggregate, limit, offset], |row| {
            row.get::<_, String>(0)
        })?
        .collect::<Result<Vec<_>, _>>()?;
    let items = courses
        .iter()
        .map(|course| get(db, root, course, false))
        .collect::<Result<Vec<_>, _>>()?;
    let next = offset + items.len() as i64;
    Ok(
        json!({"plan_line_id":plan,"items":items,"total":total,"next_offset":(next<total).then_some(next)}),
    )
}
