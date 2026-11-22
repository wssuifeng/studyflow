use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use time::Date;

use crate::{application::write_contract::atomic_write, infrastructure::StorageError};

use super::{date_text, event};

const KINDS: &[&str] = &[
    "DOCUMENT", "EXAM", "OTHER", "PRACTICE", "PROJECT", "READING", "REVIEW",
];

pub(crate) fn task_kind(value: &str) -> Result<String, StorageError> {
    let normalized = value.to_uppercase();
    if KINDS.contains(&normalized.as_str()) {
        Ok(normalized)
    } else {
        Err(StorageError::new("INVALID_TASK_KIND"))
    }
}

pub struct NewTask<'a> {
    pub title: &'a str,
    pub date: Date,
    pub kind: &'a str,
    pub description: &'a str,
    pub plan: Option<&'a str>,
    pub priority: i64,
}

pub fn create_task(db: &mut Connection, task: NewTask<'_>) -> Result<Value, StorageError> {
    let title = task.title.trim();
    let kind = task_kind(task.kind.trim())?;
    if title.is_empty() || task.priority < 1 {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let day = date_text(task.date);
    let plan = task.plan.filter(|id| !id.is_empty());
    atomic_write(db, |db| {
        if let Some(plan) = plan {
            let exists = db
                .query_row("SELECT 1 FROM plan_lines WHERE id=?", [plan], |_| Ok(()))
                .optional()?;
            if exists.is_none() {
                return Err(StorageError::new("PLAN_LINE_NOT_FOUND"));
            }
        }
        let id = uuid::Uuid::new_v4().to_string();
        db.execute(
            "INSERT INTO tasks(id,title,description,scheduled_date,task_kind,plan_line_id,priority,status,reason,next_action) VALUES(?,?,?,?,?,?,?,'TODO','','')",
            params![id, title, task.description.trim(), day, kind, plan, task.priority],
        )?;
        event(db, "AGENT_CLI", "task", &id, "CREATE", title)?;
        Ok(json!({"id":id,"title":title,"date":day,"kind":kind,"plan_line_id":plan}))
    })
}

pub fn list_tasks(
    db: &Connection,
    date: Option<Date>,
    plan: Option<&str>,
    kind: Option<&str>,
    dashboard: bool,
) -> Result<Vec<Value>, StorageError> {
    let day = date.map(date_text);
    let plan = plan.filter(|value| !value.is_empty());
    let kind = kind
        .filter(|value| !value.is_empty())
        .map(task_kind)
        .transpose()?;
    let mut query = db.prepare(
        "SELECT t.id,t.title,t.scheduled_date,t.status,t.task_kind,p.name FROM tasks t
         LEFT JOIN plan_lines p ON p.id=t.plan_line_id
         WHERE (?1 IS NULL OR t.scheduled_date=?1) AND (?2 IS NULL OR t.plan_line_id=?2)
         AND (?3 IS NULL OR t.task_kind=?3)
         ORDER BY t.scheduled_date,t.priority,CASE WHEN ?4 THEN t.id ELSE t.title END,t.id",
    )?;
    let rows = query.query_map(params![day, plan, kind, dashboard], |row| Ok(json!({
        "id":row.get::<_,String>(0)?,"title":row.get::<_,String>(1)?,"date":row.get::<_,String>(2)?,
        "status":row.get::<_,String>(3)?,"kind":row.get::<_,String>(4)?,"plan_line":row.get::<_,Option<String>>(5)?,
    })))?.collect::<Result<_,_>>()?;
    Ok(rows)
}
