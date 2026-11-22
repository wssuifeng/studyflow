use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};
use time::{macros::format_description, Time};

use super::{date_text, event, parse_date, today};
use crate::{
    application::write_contract::{atomic_write, require_version, validate_key, StoredReceipt},
    infrastructure::{fingerprint::JsonFingerprint, StorageError},
};

pub struct PlanEdit<'a> {
    pub plan_line_id: &'a str,
    pub expected_version: i64,
    pub idempotency_key: &'a str,
    pub operation: &'a str,
    pub values: &'a Map<String, Value>,
}

type EditResult<T> = Result<T, StorageError>;
fn invalid() -> StorageError {
    StorageError::new("INVALID_ARGUMENT")
}
fn conflict() -> StorageError {
    StorageError::new("VERSION_CONFLICT")
}

pub fn edit_plan(connection: &mut Connection, edit: PlanEdit<'_>) -> EditResult<Value> {
    validate_key(edit.idempotency_key)?;
    let hash = JsonFingerprint::Ascii.hash(&json!({"plan_line_id":edit.plan_line_id,
        "expected_version":edit.expected_version,"operation":edit.operation,"values":edit.values}));
    atomic_write(connection, |db| {
        if let Some(receipt) = db
            .query_row(
                "SELECT payload_hash,result_json FROM plan_write_receipts WHERE idempotency_key=?",
                [edit.idempotency_key],
                |row| {
                    Ok(StoredReceipt {
                        operation: None,
                        payload_hash: row.get(0)?,
                        result_json: row.get(1)?,
                    })
                },
            )
            .optional()?
        {
            return receipt.replay(None, &hash);
        }
        let (version, name, priority, status, focus): (i64, String, i64, String, Option<String>) =
            db.query_row(
                "SELECT version,name,priority,status,focus_course_id FROM plan_lines WHERE id=?",
                [edit.plan_line_id],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                    ))
                },
            )
            .optional()?
            .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
        require_version(version, edit.expected_version)?;
        let items = plan_items(db, edit.plan_line_id)?;
        let id = edit.plan_line_id;
        let values = edit.values;
        match edit.operation {
            "UPDATE" => update(
                db,
                id,
                values,
                &items,
                PlanValues {
                    name,
                    priority,
                    status,
                    focus,
                },
            )?,
            "REORDER" => reorder(db, values, &items)?,
            "COURSE_POSITION" => move_course(db, id, values, &items)?,
            "SCHEDULE" => schedule(db, values, &items)?,
            "RESCHEDULE" | "CANCEL_SCHEDULE" => {
                edit_schedule(db, id, values, edit.operation == "CANCEL_SCHEDULE")?
            }
            _ => return Err(invalid()),
        }
        let next = version.checked_add(1).ok_or_else(conflict)?;
        if db.execute(
            "UPDATE plan_lines SET version=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?",
            params![next, id, version],
        )? != 1
        {
            return Err(conflict());
        }
        let result = json!({"ok":true,"plan_line_id":id,"version":next,"operation":edit.operation});
        db.execute("INSERT INTO plan_write_receipts(id,idempotency_key,payload_hash,result_json) VALUES(?,?,?,?)",
            params![uuid::Uuid::new_v4().to_string(), edit.idempotency_key, hash, result.to_string()])?;
        event(
            db,
            "USER_ENGINE",
            "plan",
            id,
            edit.operation,
            &format!("调整个人计划至版本 {next}，不改变学习证据"),
        )?;
        Ok(result)
    })
}

struct PlanValues {
    name: String,
    priority: i64,
    status: String,
    focus: Option<String>,
}
struct Item {
    id: String,
    course_id: String,
    track: String,
    position: i64,
    management: String,
}

fn plan_items(db: &Connection, plan: &str) -> EditResult<Vec<Item>> {
    let mut query = db.prepare("SELECT id,course_id,track,sequence_number,management_position FROM plan_course_items WHERE plan_line_id=? ORDER BY sequence_number")?;
    let items = query
        .query_map([plan], |row| {
            Ok(Item {
                id: row.get(0)?,
                course_id: row.get(1)?,
                track: row.get(2)?,
                position: row.get(3)?,
                management: row.get(4)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(items)
}

fn fields(values: &Map<String, Value>, allowed: &[&str]) -> EditResult<()> {
    if values.keys().all(|key| allowed.contains(&key.as_str())) {
        Ok(())
    } else {
        Err(invalid())
    }
}

fn text<'a>(values: &'a Map<String, Value>, key: &str) -> EditResult<&'a str> {
    values.get(key).and_then(Value::as_str).ok_or_else(invalid)
}

fn update(
    db: &Connection,
    id: &str,
    values: &Map<String, Value>,
    items: &[Item],
    mut plan: PlanValues,
) -> EditResult<()> {
    fields(values, &["name", "priority", "status", "focus_course_id"])?;
    if let Some(name) = values.get("name") {
        plan.name = name
            .as_str()
            .map(str::trim)
            .filter(|name| (1..=120).contains(&name.chars().count()))
            .ok_or_else(invalid)?
            .into();
    }
    if let Some(priority) = values.get("priority") {
        plan.priority = priority
            .as_i64()
            .filter(|value| (1..=100).contains(value))
            .ok_or_else(invalid)?;
    }
    if let Some(status) = values.get("status") {
        plan.status = match status.as_str() {
            Some(value @ ("ACTIVE" | "PAUSED" | "ARCHIVED")) => value.into(),
            _ => return Err(invalid()),
        };
    }
    if let Some(focus) = values.get("focus_course_id") {
        plan.focus = match focus {
            Value::Null => None,
            Value::String(course)
                if items
                    .iter()
                    .any(|i| i.course_id == *course && i.track == "MAIN") =>
            {
                Some(course.clone())
            }
            _ => return Err(invalid()),
        };
    }
    let duplicate = db
        .query_row(
            "SELECT 1 FROM plan_lines WHERE name=? AND id<>?",
            params![plan.name, id],
            |_| Ok(()),
        )
        .optional()?
        .is_some();
    if duplicate {
        return Err(StorageError::new("PLAN_LINE_EXISTS"));
    }
    db.execute(
        "UPDATE plan_lines SET name=?,priority=?,status=?,focus_course_id=? WHERE id=?",
        params![plan.name, plan.priority, plan.status, plan.focus, id],
    )?;
    Ok(())
}

fn reorder(db: &Connection, values: &Map<String, Value>, items: &[Item]) -> EditResult<()> {
    fields(values, &["course_ids"])?;
    let order = values
        .get("course_ids")
        .and_then(Value::as_array)
        .ok_or_else(invalid)?;
    let main: std::collections::HashMap<_, _> = items
        .iter()
        .filter(|item| item.track == "MAIN")
        .map(|item| (item.course_id.as_str(), item))
        .collect();
    if order.len() != main.len() {
        return Err(invalid());
    }
    let mut visited = std::collections::HashSet::new();
    let mut ordered = Vec::new();
    for course in order {
        let id = course.as_str().ok_or_else(invalid)?;
        let item = main
            .get(id)
            .filter(|_| visited.insert(id))
            .ok_or_else(invalid)?;
        ordered.push(*item);
    }
    for (index, item) in ordered.iter().enumerate() {
        db.execute(
            "UPDATE plan_course_items SET sequence_number=? WHERE id=?",
            params![-(index as i64 + 1), item.id],
        )?;
    }
    for (index, item) in ordered.iter().enumerate() {
        let position = index as i64 + 1;
        db.execute("UPDATE plan_course_items SET sequence_number=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",params![position,item.id])?;
        db.execute("UPDATE course_schedule_items SET position=?,updated_at=CURRENT_TIMESTAMP WHERE plan_course_item_id=? AND status<>'CANCELLED'",params![position,item.id])?;
    }
    Ok(())
}

fn move_course(
    db: &Connection,
    plan: &str,
    values: &Map<String, Value>,
    items: &[Item],
) -> EditResult<()> {
    fields(values, &["course_id", "position", "reason"])?;
    let course = values
        .get("course_id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let item = items
        .iter()
        .find(|item| item.course_id == course)
        .ok_or_else(|| StorageError::new("SCOPE_MISMATCH"))?;
    let position = text(values, "position")?;
    let reason = match values.get("reason") {
        Some(value) => value.as_str().ok_or_else(invalid)?,
        None => "",
    };
    if !matches!(position, "NORMAL" | "OTHER")
        || reason.chars().count() > 1000
        || position == "OTHER" && reason.trim().is_empty()
    {
        return Err(invalid());
    }
    let reason = if position == "OTHER" {
        reason.trim()
    } else {
        ""
    };
    db.execute("UPDATE plan_course_items SET management_position=?,management_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",params![position,reason,item.id])?;
    if position == "OTHER" {
        db.execute(
            "UPDATE plan_lines SET focus_course_id=NULL WHERE id=? AND focus_course_id=?",
            params![plan, course],
        )?;
        db.execute("UPDATE course_schedule_items SET status='CANCELLED',updated_at=CURRENT_TIMESTAMP WHERE plan_course_item_id=? AND status='PLANNED' AND scheduled_date>=?",params![item.id,date_text(today())])?;
    }
    Ok(())
}

fn read_time(value: Option<&Value>) -> EditResult<Option<Time>> {
    let text = match value {
        None | Some(Value::Null) => return Ok(None),
        Some(value) => value.as_str().ok_or_else(invalid)?,
    };
    if text.is_empty() {
        return Ok(None);
    }
    let time = Time::parse(
        text,
        format_description!("[hour]:[minute]:[second].[subsecond]"),
    )
    .or_else(|_| Time::parse(text, format_description!("[hour]:[minute]:[second]")))
    .or_else(|_| Time::parse(text, format_description!("[hour]:[minute]")))
    .map_err(|error| StorageError::caused_by("INVALID_ARGUMENT", error))?;
    Ok(Some(time))
}

fn schedule(db: &Connection, values: &Map<String, Value>, items: &[Item]) -> EditResult<()> {
    fields(values, &["course_id", "date", "start_time", "end_time"])?;
    let course = text(values, "course_id")?;
    let item = items
        .iter()
        .find(|item| item.course_id == course)
        .ok_or_else(invalid)?;
    if item.management == "OTHER" {
        return Err(StorageError::new("COURSE_ON_HOLD"));
    }
    let day = date_text(parse_date(text(values, "date")?)?);
    let start = read_time(values.get("start_time"))?;
    let end = read_time(values.get("end_time"))?;
    if start.zip(end).is_some_and(|(start, end)| end <= start) {
        return Err(invalid());
    }
    let as_text = |value: Time| {
        value
            .format(format_description!(
                "[hour]:[minute]:[second].[subsecond digits:6]"
            ))
            .expect("valid time")
    };
    db.execute(
        "INSERT INTO course_schedule_items(id,plan_course_item_id,scheduled_date,position,start_time,end_time,status)
         VALUES(?,?,?,?,?,?,'PLANNED') ON CONFLICT(plan_course_item_id,scheduled_date) DO UPDATE SET
         start_time=excluded.start_time,end_time=excluded.end_time,status='PLANNED',updated_at=CURRENT_TIMESTAMP",
        params![uuid::Uuid::new_v4().to_string(),item.id,day,item.position,start.map(as_text),end.map(as_text)],
    )?;
    Ok(())
}

fn edit_schedule(
    db: &Connection,
    plan: &str,
    values: &Map<String, Value>,
    cancel: bool,
) -> EditResult<()> {
    let id = text(values, "schedule_id")?;
    let (item, management): (String,String) = db.query_row(
        "SELECT p.id,p.management_position FROM course_schedule_items s JOIN plan_course_items p ON p.id=s.plan_course_item_id WHERE s.id=? AND p.plan_line_id=?",
        params![id,plan], |row| Ok((row.get(0)?,row.get(1)?)),
    ).optional()?.ok_or_else(invalid)?;
    if cancel {
        db.execute("UPDATE course_schedule_items SET status='CANCELLED',updated_at=CURRENT_TIMESTAMP WHERE id=?",[id])?;
        return Ok(());
    }
    if management == "OTHER" {
        return Err(StorageError::new("COURSE_ON_HOLD"));
    }
    let day = date_text(parse_date(text(values, "date")?)?);
    if db.query_row("SELECT 1 FROM course_schedule_items WHERE plan_course_item_id=? AND scheduled_date=? AND id<>?",params![item,day,id], |_| Ok(())).optional()?.is_some() {
        return Err(conflict());
    }
    db.execute("UPDATE course_schedule_items SET scheduled_date=?,status='PLANNED',updated_at=CURRENT_TIMESTAMP WHERE id=?",params![day,id])?;
    Ok(())
}
