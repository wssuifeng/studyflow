use rusqlite::{params, Connection, OptionalExtension};
use serde_json::Value;
use uuid::Uuid;

use crate::{infrastructure::StorageError, learning::study_sessions::Round};

pub(super) fn record_check(
    db: &Connection,
    round: &Round,
    item: &Value,
    attempt: &str,
    rule: &str,
    matched: bool,
) -> Result<(), StorageError> {
    let plan: Option<String> = db.query_row(
        "SELECT plan_line_id FROM english_study_states WHERE study_session_id=?",
        [&round.id],
        |row| row.get(0),
    )?;
    let notebook = crate::mistakes::notebook(db, plan.as_deref(), "english", !matched)?;
    let Some(notebook) = notebook else {
        return Ok(());
    };
    let exercise = item["id"].as_str().unwrap();
    if !matched {
        let ids = item["english"]["objective_ids"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_default();
        db.execute("INSERT INTO english_error_aggregates(id,notebook_id,course_id,exercise_key,rule_hash,objective_ids_json,failed_attempts,failed_rounds,version,archived)
            VALUES(?,?,?,?,?,?,0,0,1,0) ON CONFLICT(notebook_id,course_id,exercise_key,rule_hash) DO NOTHING",params![Uuid::new_v4().to_string(),notebook,round.course,exercise,rule,serde_json::to_string(ids).unwrap()])?;
    }
    let id:Option<String>=db.query_row("SELECT id FROM english_error_aggregates WHERE notebook_id=? AND course_id=? AND exercise_key=? AND rule_hash=?",
        params![notebook,round.course,exercise,rule],|row|row.get(0)).optional()?;
    let Some(id) = id else {
        return Ok(());
    };
    if matched {
        db.execute("UPDATE english_error_aggregates SET latest_attempt_id=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",params![attempt,id])?;
        return Ok(());
    }
    let prior = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM english_error_evidence WHERE aggregate_id=? AND round_key=?)",
        params![id, round.id],
        |row| row.get::<_, bool>(0),
    )?;
    db.execute("INSERT INTO english_error_evidence(id,aggregate_id,attempt_id,round_key,valid_error) VALUES(?,?,?,?,1)",params![Uuid::new_v4().to_string(),id,attempt,round.id])?;
    let reopen=db.execute("UPDATE english_review_items SET status='PENDING',reason='NEW_FAILURE',updated_at=CURRENT_TIMESTAMP WHERE aggregate_id=?",[&id])?;
    db.execute("UPDATE english_error_aggregates SET latest_attempt_id=?,version=version+1+?,failed_attempts=failed_attempts+1,failed_rounds=failed_rounds+?,archived=0,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        params![attempt,reopen as i64,i64::from(!prior),id])?;
    Ok(())
}
