use std::path::Path;

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    courses::catalog,
    documents,
    infrastructure::{events, fingerprint::JsonFingerprint, StorageError},
};

pub fn capture(
    db: &Connection,
    root: &Path,
    course_id: &str,
    plan: Option<&str>,
) -> Result<(Value, String), StorageError> {
    let mut course = catalog::course(db, course_id)?;
    if let Some(plan) = plan {
        let name: String = db.query_row("SELECT p.name FROM plan_lines p JOIN plan_course_items i ON i.plan_line_id=p.id WHERE p.id=? AND i.course_id=?",
            params![plan,course_id],|row|row.get(0)).optional()?.ok_or_else(||StorageError::new("SCOPE_MISMATCH"))?;
        course["plan_line_id"] = json!(plan);
        course["plan_line"] = json!(name);
    }
    let mut lessons = catalog::rows(db, course_id)?;
    if lessons.is_empty() {
        return Err(StorageError::new("EMPTY_COURSE"));
    }
    for lesson in &mut lessons {
        let source = catalog::read_markdown(root, lesson["markdown_path"].as_str().unwrap())
            .map_err(|e| {
                if e.code == "DOCUMENT_NOT_FOUND" {
                    StorageError::new("DOCUMENT_UNREADABLE")
                } else {
                    e
                }
            })?;
        let (meta, body) = if source.starts_with("---\n") {
            documents::parse_front_matter(&source)?
        } else {
            (Value::Null, source.as_str())
        };
        let (html, blocks) =
            catalog::lesson_content(&source, lesson["exercises"].as_array().unwrap())?;
        let specs = meta["structured_lesson"]["exercises"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or(&[]);
        let exercises = lesson["exercises"].as_array_mut().unwrap();
        if course["learning_mode"] == "english" && exercises.len() != specs.len() {
            return Err(StorageError::new("INVALID_COURSE_PACKAGE"));
        }
        let mut has_groups = false;
        for (index, exercise) in exercises.iter_mut().enumerate() {
            exercise.as_object_mut().unwrap().remove("semantic_id");
            if let Some(spec) = specs.get(index) {
                for key in ["review_reference", "essay", "reading", "listening"] {
                    if let Some(value) = spec.get(key) {
                        exercise[key] = value.clone();
                    }
                }
                if let Some(english) = spec
                    .get("english")
                    .filter(|_| course["learning_mode"] == "english")
                {
                    exercise["english"] = english.clone();
                    exercise["english"]["checker_version"] = json!("english-exact/1");
                }
            }
            has_groups |= matches!(
                exercise["type"].as_str(),
                Some("READING_GROUP" | "LISTENING_GROUP")
            );
        }
        lesson.as_object_mut().unwrap().remove("semantic_id");
        lesson["document_status"] = json!("PRESENT");
        lesson["rendered_html"] = json!(html);
        lesson["markdown"] = json!(if has_groups { body } else { &source });
        if !blocks.is_empty() {
            lesson["content_blocks"] = json!(blocks);
        }
    }
    let snapshot = json!({"course":course,"lessons":lessons});
    let hash = JsonFingerprint::Utf8.hash(&snapshot);
    Ok((snapshot, hash))
}

pub(crate) fn preserve_legacy_round(
    db: &Connection,
    root: &Path,
    course: &str,
    key: &str,
) -> Result<(), StorageError> {
    let needed: bool = db.query_row("SELECT NOT EXISTS(SELECT 1 FROM course_study_sessions WHERE course_id=?1)
        AND (EXISTS(SELECT 1 FROM submissions s JOIN exercises e ON e.id=s.exercise_id JOIN lessons l ON l.id=e.lesson_id WHERE l.course_id=?1 AND s.study_session_id IS NULL)
            OR EXISTS(SELECT 1 FROM learning_progress WHERE course_id=?1))",[course],|row|row.get(0))?;
    if !needed {
        return Ok(());
    }
    let (snapshot, hash) = capture(db, root, course, None)?;
    let id = Uuid::new_v4().to_string();
    let legacy_key = format!(
        "legacy-boundary-{}",
        JsonFingerprint::Ascii.hash(&json!({"course":course,"key":key}))
    );
    db.execute("INSERT INTO course_study_sessions(id,course_id,revision,idempotency_key,new_version,snapshot_json,content_hash,progress_json,version,reading_completed)
        VALUES(?,?,1,?,0,?,?,'{}',1,0)",params![id,course,legacy_key,snapshot.to_string(),hash])?;
    events::record(
        db,
        "AGENT_CLI",
        "course_study",
        &id,
        "LEGACY_BOUNDARY",
        "课程覆盖前保留旧材料边界；不是新增学习或作答证据",
    )?;
    Ok(())
}

pub(crate) fn seal_current(
    db: &Connection,
    course: &str,
    reason: &str,
) -> Result<Vec<String>, StorageError> {
    let mut query = db.prepare("SELECT id FROM course_study_sessions WHERE course_id=? AND abandoned_at IS NULL ORDER BY revision,id")?;
    let rows = query
        .query_map([course], |row| row.get::<_, String>(0))?
        .collect::<Result<Vec<_>, _>>()?;
    db.execute("UPDATE course_study_sessions SET abandoned_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP,version=version+1 WHERE course_id=? AND abandoned_at IS NULL",[course])?;
    for id in &rows {
        events::record(db, "AGENT_CLI", "course_study", id, "ABANDON", reason)?;
    }
    db.execute("DELETE FROM learning_progress WHERE course_id=?", [course])?;
    Ok(rows)
}

pub fn readback(
    db: &Connection,
    root: &Path,
    course_id: &str,
    plan: Option<&str>,
) -> Result<Value, StorageError> {
    let active = db.query_row("SELECT id,revision,content_hash,snapshot_json,abandoned_at FROM course_study_sessions WHERE course_id=? ORDER BY revision DESC LIMIT 1",
        [course_id],|row|Ok((row.get::<_,String>(0)?,row.get::<_,i64>(1)?,row.get::<_,String>(2)?,row.get::<_,String>(3)?,row.get::<_,Option<String>>(4)?))).optional()?;
    let (capture, hash) = capture(db, root, course_id, plan)?;
    let mut active_round = Value::Null;
    let readback = match active {
        Some((id, revision, previous_hash, raw, None)) => {
            active_round = json!({"study_session_id":id,"revision":revision,"content_hash":previous_hash,"abandoned":false});
            let old: Value = serde_json::from_str(&raw)
                .map_err(|e| StorageError::caused_by("DATABASE_ERROR", e))?;
            if previous_hash == hash || logical_capture(&old) == logical_capture(&capture) {
                "current"
            } else {
                "stale"
            }
        }
        _ => "no_active_round",
    };
    let next = match readback {
        "current" => "活动学习轮读到的就是最新材料，无需重开课程。",
        "stale" => "学习材料已更新而学习轮未重置；经用户授权运行course reset-learning的dry-run/confirm，再读取最新材料。",
        _ => "课程当前没有活动学习轮；下次打开课程即从最新材料开始。",
    };
    Ok(
        json!({"course_id":course_id,"learning_mode":capture["course"]["learning_mode"],"latest_revision":capture["course"]["content_revision"],
        "active_round":active_round,"current_capture_hash":hash,"readback":readback,"next_action":next}),
    )
}

// Renderer-generated HTML is derived and can differ between the old and new
// engines. Compare the authoring source and frozen exercise data as well as the hash.
pub(crate) fn logical_capture(source: &Value) -> Value {
    let mut value = source.clone();
    for lesson in value["lessons"].as_array_mut().into_iter().flatten() {
        let fields = lesson.as_object_mut().unwrap();
        fields.remove("rendered_html");
        if let Some(blocks) = fields.get_mut("content_blocks") {
            strip_rendered_html(blocks);
        }
    }
    value
}

fn strip_rendered_html(value: &mut Value) {
    match value {
        Value::Object(fields) => {
            fields.retain(|key, _| !key.ends_with("_html"));
            fields.values_mut().for_each(strip_rendered_html);
        }
        Value::Array(items) => items.iter_mut().for_each(strip_rendered_html),
        _ => {}
    }
}

pub fn source(
    db: &Connection,
    root: &Path,
    study: &str,
    lesson: &str,
    block: Option<&str>,
    section: Option<&str>,
) -> Result<Value, StorageError> {
    let (raw, hash): (String, String) = db
        .query_row(
            "SELECT snapshot_json,content_hash FROM course_study_sessions WHERE id=?",
            [study],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    let mut content: Value =
        serde_json::from_str(&raw).map_err(|e| StorageError::caused_by("DATABASE_ERROR", e))?;
    let lesson = content["lessons"]
        .as_array_mut()
        .into_iter()
        .flatten()
        .find(|item| item["id"] == lesson)
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    hide_answers(lesson);
    let block = block
        .filter(|id| !id.is_empty())
        .map(|id| {
            lesson["content_blocks"]
                .as_array()
                .into_iter()
                .flatten()
                .find(|item| item["id"] == id)
                .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))
        })
        .transpose()?;
    let section = section
        .filter(|id| !id.is_empty())
        .map(|id| {
            block
                .and_then(|b| find_section(&b["sections"], id))
                .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))
        })
        .transpose()?;
    let key = crate::audio::assets::digest(root.to_string_lossy().as_bytes());
    let mut result = json!({"workspace_key":&key[..16],"readonly":true,"study_session_id":study,"content_hash":hash,"lesson":lesson,"block":block,"section":section});
    result["course"] = content["course"].clone();
    Ok(result)
}

pub(crate) fn hide_answers(lesson: &mut Value) {
    for exercise in lesson["exercises"].as_array_mut().into_iter().flatten() {
        if let Some(fields) = exercise.as_object_mut() {
            for field in ["review_reference", "reading", "listening"] {
                fields.remove(field);
            }
            if let Some(spec) = fields.get_mut("english") {
                let target = spec["target"].as_str().unwrap_or_default();
                *spec = json!({"token_count":super::english_check::tokens(target).len(),"evaluation_mode":spec["evaluation_mode"].as_str().unwrap_or("local_exact")});
            }
        }
    }
    // The YAML includes author-side reference and answer fields. Keep it only
    // in the frozen snapshot and explicit author reads.
    if let Some(body) = lesson["markdown"]
        .as_str()
        .and_then(|text| documents::parse_front_matter(text).ok())
        .filter(|(metadata, _)| metadata.get("structured_lesson").is_some())
        .map(|(_, body)| body.to_owned())
    {
        lesson["markdown"] = json!(body);
    }
}

fn find_section<'a>(children: &'a Value, id: &str) -> Option<&'a Value> {
    children.as_array()?.iter().find_map(|section| {
        if section["id"] == id {
            Some(section)
        } else {
            find_section(&section["children"], id)
        }
    })
}
