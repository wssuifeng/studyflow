mod edits;
mod membership;
mod queries;
mod tasks;
pub use queries::{dashboard, plan_detail};
pub use tasks::{create_task, list_tasks, NewTask};

pub use edits::{edit_plan, PlanEdit};
pub use membership::{ensure_membership, Track};

use crate::infrastructure::events::record as event;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use time::{macros::format_description, Date, OffsetDateTime, UtcOffset};

use crate::{application::write_contract::atomic_write, infrastructure::StorageError};

pub fn today() -> Date {
    let now = OffsetDateTime::now_utc();
    now.to_offset(UtcOffset::local_offset_at(now).unwrap_or(UtcOffset::UTC))
        .date()
}

pub fn parse_date(input: &str) -> Result<Date, StorageError> {
    Date::parse(input, format_description!("[year]-[month]-[day]"))
        .map_err(|error| StorageError::caused_by("INVALID_ARGUMENT", error))
}

pub fn date_text(date: Date) -> String {
    date.format(format_description!("[year]-[month]-[day]"))
        .expect("valid date")
}

pub fn list_plans(db: &Connection, include_inactive: bool) -> Result<Vec<Value>, StorageError> {
    let mut query = db.prepare(
        "SELECT id,name,priority,status,version,focus_course_id FROM plan_lines
         WHERE ? OR status='ACTIVE' ORDER BY priority,name",
    )?;
    let output = query
        .query_map([include_inactive], plan_row)?
        .collect::<Result<_, _>>()?;
    Ok(output)
}

pub fn get_plan(db: &Connection, identifier: &str) -> Result<Value, StorageError> {
    db.query_row(
        "SELECT id,name,priority,status,version,focus_course_id FROM plan_lines
         WHERE id=?1 OR name=?1 ORDER BY id=?1 DESC LIMIT 1",
        [identifier],
        plan_row,
    )
    .optional()?
    .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))
}

fn plan_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    Ok(
        json!({"id": row.get::<_, String>(0)?, "name": row.get::<_, String>(1)?, "priority": row.get::<_, i64>(2)?,
        "status": row.get::<_, String>(3)?, "version": row.get::<_, i64>(4)?, "focus_course_id": row.get::<_, Option<String>>(5)?}),
    )
}

pub fn change_token(db: &Connection) -> Result<Value, StorageError> {
    let (count, latest): (i64, Option<String>) = db.query_row(
        "SELECT COUNT(id), MAX(created_at) FROM event_logs",
        [],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    let latest = latest.unwrap_or_default();
    let normalized = latest.strip_suffix(".000000").unwrap_or(&latest);
    Ok(json!({"revision": format!("{count}:{normalized}"), "event_count": count}))
}

pub fn create_plan(db: &mut Connection, name: &str, priority: i64) -> Result<Value, StorageError> {
    let name = name.trim();
    if name.is_empty() || priority < 1 {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    atomic_write(db, |db| {
        if db
            .query_row("SELECT 1 FROM plan_lines WHERE name=?", [name], |_| Ok(()))
            .optional()?
            .is_some()
        {
            return Err(StorageError::new("PLAN_LINE_EXISTS"));
        }
        let id = uuid::Uuid::new_v4().to_string();
        db.execute(
            "INSERT INTO plan_lines(id,name,priority,status,version) VALUES(?,?,?,'ACTIVE',1)",
            params![id, name, priority],
        )?;
        event(db, "AGENT_CLI", "plan_line", &id, "CREATE", name)?;
        get_plan(db, &id)
    })
}

pub fn schedules(db: &Connection, id: &str) -> Result<Value, StorageError> {
    if db
        .query_row("SELECT 1 FROM plan_lines WHERE id=?", [id], |_| Ok(()))
        .optional()?
        .is_none()
    {
        return Err(StorageError::new("OBJECT_NOT_FOUND"));
    }
    let mut query = db.prepare(
        "SELECT s.id,p.course_id,s.scheduled_date,s.status,s.start_time,s.end_time
         FROM course_schedule_items s JOIN plan_course_items p ON p.id=s.plan_course_item_id
         WHERE p.plan_line_id=? ORDER BY s.scheduled_date,s.id",
    )?;
    let items = query.query_map([id], |row| Ok(json!({
        "id": row.get::<_,String>(0)?, "course_id": row.get::<_,String>(1)?, "date": row.get::<_,String>(2)?,
        "status": row.get::<_,String>(3)?, "start_time": exposed_time(row.get(4)?), "end_time": exposed_time(row.get(5)?),
    })))?.collect::<Result<Vec<_>,_>>()?;
    Ok(json!({"items": items}))
}

pub(super) fn exposed_time(value: Option<String>) -> Option<String> {
    value.map(|value| value.strip_suffix(".000000").unwrap_or(&value).to_owned())
}
pub(crate) use queries::course_status;

pub(crate) fn add_membership(
    db: &Connection,
    id: &str,
    course: &mut Value,
) -> Result<(), StorageError> {
    use rusqlite::{params, OptionalExtension};
    let membership = db.query_row("SELECT sequence_number,track,(SELECT COUNT(*) FROM plan_course_items m WHERE m.plan_line_id=i.plan_line_id AND m.track=i.track)
        FROM plan_course_items i WHERE course_id=? AND plan_line_id=? ORDER BY sequence_number LIMIT 1",params![id,course["plan_line_id"].as_str()],
        |row|Ok((row.get::<_,i64>(0)?,row.get::<_,String>(1)?,row.get::<_,i64>(2)?))).optional()?;
    let default = course["track"].as_str().unwrap_or("MAIN").to_owned();
    let (sequence, track, total) =
        membership.map_or((None, default, 0), |(n, t, c)| (Some(n), t, c));
    course["sequence"] = json!(sequence);
    course["track"] = json!(track);
    course["total"] = json!(total);
    Ok(())
}
