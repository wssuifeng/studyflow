use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use super::notebook;
use crate::{
    infrastructure::{fingerprint::JsonFingerprint::Utf8, StorageError},
    learning::{english_check, study_sessions},
};

pub(crate) fn record_review(
    db: &Connection,
    study: Option<&str>,
    exercise: &str,
    id: &str,
    answer: &str,
    feedback: &str,
    decision: &str,
) -> Result<(), StorageError> {
    let Some(study) = study else {
        return Ok(());
    };
    let Some(frozen) = study_sessions::frozen_context(db, study, exercise)? else {
        return Ok(());
    };
    let course = frozen["course"]["id"]
        .as_str()
        .ok_or_else(|| StorageError::new("DATABASE_ERROR"))?;
    let question = &frozen["exercise"];
    let failed = decision != "PASSED";
    let english = question.get("english").filter(|entry| entry.is_object());
    let Some(book) = notebook(
        db,
        frozen["course"]["plan_line_id"].as_str(),
        if english.is_some() {
            "english"
        } else {
            "general"
        },
        failed,
    )?
    else {
        return Ok(());
    };
    if let Some(spec) = english {
        let rule = english_check::rule_hash(spec, question["prompt"].as_str().unwrap_or_default());
        let aggregate: Option<String> = db.query_row("SELECT id FROM english_error_aggregates WHERE notebook_id=? AND course_id=? AND exercise_key=? AND rule_hash=?",params![book,course,exercise,rule],|row|row.get(0)).optional()?;
        if !failed {
            db.execute("UPDATE english_error_evidence SET valid_error=0,updated_at=CURRENT_TIMESTAMP WHERE attempt_id IN (SELECT id FROM english_check_attempts WHERE submission_id=? AND answer_text=? AND rule_hash=?)",params![id,answer,rule])?;
            if let Some(aggregate) = aggregate {
                db.execute("UPDATE english_review_items SET status='AGENT_ACCEPTED',updated_at=CURRENT_TIMESTAMP WHERE aggregate_id=?",[&aggregate])?;
                db.execute("UPDATE english_error_aggregates SET version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",[&aggregate])?;
            }
            return Ok(());
        }
        let aggregate = match aggregate {
            Some(aggregate) => aggregate,
            None => {
                let aggregate = Uuid::new_v4().to_string();
                let objectives = spec
                    .get("objective_ids")
                    .cloned()
                    .unwrap_or_else(|| json!([]));
                db.execute("INSERT INTO english_error_aggregates(id,notebook_id,course_id,exercise_key,rule_hash,objective_ids_json) VALUES(?,?,?,?,?,?)",params![aggregate,book,course,exercise,rule,objectives.to_string()])?;
                aggregate
            }
        };
        let last: Option<String> = db.query_row("SELECT a.result_json FROM english_submission_details d JOIN english_check_attempts a ON a.id=d.last_attempt_id WHERE d.submission_id=?",[id],|row|row.get(0)).optional()?;
        let last: Option<Value> = last
            .map(|raw| serde_json::from_str(&raw))
            .transpose()
            .map_err(|err| StorageError::caused_by("DATABASE_ERROR", err))?;
        if last.is_none_or(|last| last["matched"] != false) {
            let prior: bool = db.query_row("SELECT EXISTS(SELECT 1 FROM english_error_evidence WHERE aggregate_id=? AND round_key=?)",params![aggregate,study],|row|row.get(0))?;
            db.execute("INSERT INTO english_error_evidence(id,aggregate_id,feedback_id,round_key,valid_error) VALUES(?,?,?,?,1)",params![Uuid::new_v4().to_string(),aggregate,feedback,study])?;
            db.execute("UPDATE english_error_aggregates SET failed_attempts=failed_attempts+1,failed_rounds=failed_rounds+? WHERE id=?",params![i64::from(!prior),aggregate])?;
        }
        select_english_review(db, &aggregate, "AGENT_REVISION")?;
        return Ok(());
    }
    let rule = Utf8.hash(&json!({"prompt":question["prompt"],"requirements":question["requirements"],"type":question["type"]}));
    let entry: Option<String> = db.query_row("SELECT id FROM general_mistake_entries WHERE notebook_id=? AND course_id=? AND exercise_key=? AND rule_hash=?",params![book,course,exercise,rule],|row|row.get(0)).optional()?;
    let entry = match entry {
        Some(entry) => {
            db.execute("UPDATE general_mistake_entries SET latest_feedback_id=?,status=?,version=version+1,archived=CASE WHEN ? THEN 0 ELSE archived END,updated_at=CURRENT_TIMESTAMP WHERE id=?",params![feedback,decision,failed,entry])?;
            entry
        }
        None if failed => {
            let entry = Uuid::new_v4().to_string();
            db.execute("INSERT INTO general_mistake_entries(id,notebook_id,course_id,exercise_key,rule_hash,latest_feedback_id,status) VALUES(?,?,?,?,?,?,?)",params![entry,book,course,exercise,rule,feedback,decision])?;
            entry
        }
        None => return Ok(()),
    };
    if failed {
        db.execute(
            "INSERT INTO general_mistake_occurrences(id,entry_id,feedback_id) VALUES(?,?,?)",
            params![Uuid::new_v4().to_string(), entry, feedback],
        )?;
    }
    Ok(())
}

pub(super) fn select_english_review(
    db: &Connection,
    aggregate: &str,
    reason: &str,
) -> Result<(), StorageError> {
    db.execute("INSERT INTO english_review_items(id,aggregate_id,reason,status) VALUES(?,?,?,'PENDING') ON CONFLICT(aggregate_id) DO UPDATE SET reason=excluded.reason,status='PENDING',updated_at=CURRENT_TIMESTAMP",params![Uuid::new_v4().to_string(),aggregate,reason])?;
    db.execute("UPDATE english_error_aggregates SET archived=0,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",[aggregate])?;
    Ok(())
}
