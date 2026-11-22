mod assignment;
mod feedback;
mod retests;

pub use assignment::{context, summary};
pub use feedback::write;
pub use retests::publish;

use std::collections::HashSet;

use rusqlite::Connection;
use serde_json::{json, Value};

use crate::infrastructure::StorageError;
use crate::learning::attempt_history::{effective, Submission};

fn effective_attempts(db: &Connection) -> Result<Vec<Submission>, StorageError> {
    let mut query =
        db.prepare("SELECT id,exercise_id,status,parent_submission_id FROM submissions")?;
    let rows = query
        .query_map([], |row| {
            Ok(Submission {
                id: row.get(0)?,
                exercise: row.get(1)?,
                status: row.get(2)?,
                parent: row.get(3)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    effective(db, rows)
}

fn actionable(db: &Connection, plan: Option<&str>) -> Result<Vec<(String, String)>, StorageError> {
    let active = effective_attempts(db)?;
    let ids: HashSet<_> = active.iter().map(|row| row.id.as_str()).collect();
    let parents: HashSet<_> = active
        .iter()
        .filter(|row| row.status != "DRAFT")
        .filter_map(|row| row.parent.as_deref())
        .collect();
    let mut query = db.prepare(
        "SELECT s.id,s.status FROM submissions s JOIN exercises e ON e.id=s.exercise_id
         JOIN lessons l ON l.id=e.lesson_id JOIN courses c ON c.id=l.course_id
         LEFT JOIN course_study_sessions r ON r.id=s.study_session_id
         WHERE (?1 IS NULL OR c.plan_line_id=?1) AND r.abandoned_at IS NULL
         AND (s.study_session_id IS NOT NULL OR NOT EXISTS (
             SELECT 1 FROM course_study_sessions history WHERE history.course_id=c.id AND history.revision>=2
         )) AND s.status IN ('WAITING_REVIEW','NEEDS_REVISION','RETEST_REQUIRED') ORDER BY s.created_at,s.id",
    )?;
    let mut items = Vec::new();
    let mut rows = query.query([plan])?;
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        if ids.contains(id.as_str()) && !parents.contains(id.as_str()) {
            items.push((id, row.get(1)?));
        }
    }
    Ok(items)
}

pub(crate) fn queue_counts(db: &Connection, plan: Option<&str>) -> Result<Value, StorageError> {
    let mut counts = [0; 3];
    for (_, status) in actionable(db, plan)? {
        match status.as_str() {
            "WAITING_REVIEW" => counts[0] += 1,
            "NEEDS_REVISION" => counts[1] += 1,
            "RETEST_REQUIRED" => counts[2] += 1,
            _ => unreachable!(),
        }
    }
    Ok(json!({"waiting_review":counts[0], "needs_revision":counts[1], "waiting_retest":counts[2]}))
}

pub(crate) fn retest_task(
    db: &Connection,
    parent: Option<&str>,
    id: Option<&str>,
) -> Result<Option<Value>, StorageError> {
    use rusqlite::{params, OptionalExtension};
    if parent.is_none() && id.is_none() {
        return Ok(None);
    }
    Ok(db.query_row("SELECT id,parent_submission_id,study_session_id,title,prompt,requirements,objective,status FROM retest_tasks
        WHERE parent_submission_id=?1 OR id=?2 ORDER BY parent_submission_id IS ?1 DESC LIMIT 1",params![parent,id],|row|Ok(json!({
        "id":row.get::<_,String>(0)?,"parent_submission_id":row.get::<_,String>(1)?,"study_session_id":row.get::<_,Option<String>>(2)?,
        "title":row.get::<_,String>(3)?,"prompt":row.get::<_,String>(4)?,"requirements":row.get::<_,String>(5)?,"objective":row.get::<_,String>(6)?,"status":row.get::<_,String>(7)?}))).optional()?)
}

pub fn queue(db: &Connection, plan: Option<&str>) -> Result<Value, StorageError> {
    use rusqlite::OptionalExtension;
    let mut items = Vec::new();
    let mut batches: Vec<Value> = Vec::new();
    for (id, status) in actionable(db, plan)? {
        let detail = crate::learning::submissions::detail(db, &id, false)?;
        let (kind, label) = match status.as_str() {
            "WAITING_REVIEW" => ("WAITING_REVIEW", "等待批改"),
            "NEEDS_REVISION" => ("REVISION_REQUIRED", "需要修正"),
            _ => ("RETEST_REQUIRED", "等待复测"),
        };
        let (course,lesson,path,plan_id,plan_name) = db.query_row("SELECT c.id,l.id,l.markdown_path,c.plan_line_id,p.name FROM submissions s
            JOIN exercises e ON e.id=s.exercise_id JOIN lessons l ON l.id=e.lesson_id JOIN courses c ON c.id=l.course_id
            LEFT JOIN plan_lines p ON p.id=c.plan_line_id WHERE s.id=?",[&id],|row| Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?,
                row.get::<_,String>(2)?,row.get::<_,Option<String>>(3)?,row.get::<_,Option<String>>(4)?)))?;
        let item = json!({"id":id,"status":status,"study_session_id":detail["study_session_id"],"batch_id":detail["batch_id"],"study_context":detail["study_context"],
            "kind":kind,"label":label,"exercise_id":detail["exercise_id"],"exercise_title":detail["exercise"]["title"],"course_id":course,"course_title":detail["course"]["title"],
            "lesson_id":lesson,"lesson_title":detail["lesson"]["title"],"markdown_path":detail["lesson"]["markdown_path"],"plan_line_id":plan_id,"plan_line":plan_name,
            "parent_submission_id":detail["parent_submission_id"],"attempt_number":detail["attempt_number"],"attempt_kind":detail["attempt_kind"],"source":detail["source"],
            "answer_text":detail["answer_text"],"review_count":detail["reviews"].as_array().unwrap().len(),"snapshot_status":detail["snapshot_status"],
            "next_action":detail["next_action"].as_str().filter(|value|!value.is_empty()).unwrap_or("请外部 Agent 处理该作答。"),
            "context":{"submission_id":id,"course_id":course,"lesson_id":lesson,"markdown_path":path}});
        let batch = item["batch_id"].as_str().unwrap_or(&id);
        let index = match batches.iter().position(|row| row["batch_id"] == batch) {
            Some(index) => index,
            None => {
                let receipt: Option<String> = db
                    .query_row(
                        "SELECT id FROM course_write_receipts WHERE id=?",
                        [batch],
                        |row| row.get(0),
                    )
                    .optional()?;
                let (total, reviewed): (i64, i64) = if receipt.is_some() {
                    db.query_row("SELECT COUNT(*),COALESCE(SUM(status<>'WAITING_REVIEW'),0) FROM submissions WHERE batch_id=?",[batch],|row|Ok((row.get(0)?,row.get(1)?)))?
                } else {
                    (0, 0)
                };
                batches.push(json!({"batch_id":batch,"course_id":course,"course_title":item["course_title"],"study_session_id":item["study_session_id"],
                    "submission_ids":[],"total_count":total.max(1),"reviewed_count":reviewed}));
                batches.len() - 1
            }
        };
        batches[index]["submission_ids"]
            .as_array_mut()
            .unwrap()
            .push(json!(id));
        items.push(item);
    }
    let select = |status| {
        items
            .iter()
            .filter(|row| row["status"] == status)
            .collect::<Vec<_>>()
    };
    Ok(
        json!({"batches":batches,"waiting_review":select("WAITING_REVIEW"),"needs_revision":select("NEEDS_REVISION"),"waiting_retest":select("RETEST_REQUIRED"),"items":items}),
    )
}
