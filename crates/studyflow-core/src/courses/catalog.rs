use std::{fs::File, path::Path};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use super::presentation::{render_blocks, PresentationError};
use crate::{
    documents,
    infrastructure::{file_paths, StorageError},
};

const COURSE_COLUMNS: &str = "c.id,c.title,c.summary,c.subject,c.content_type,c.difficulty,c.source_type,p.name,c.plan_line_id,c.status,c.learning_mode,c.version";

fn course_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    Ok(
        json!({"id":row.get::<_,String>(0)?,"title":row.get::<_,String>(1)?,"summary":row.get::<_,String>(2)?,
        "subject":row.get::<_,String>(3)?,"content_type":row.get::<_,String>(4)?,"difficulty":row.get::<_,String>(5)?,
        "source_type":row.get::<_,String>(6)?,"plan_line":row.get::<_,Option<String>>(7)?,"plan_line_id":row.get::<_,Option<String>>(8)?,
        "status":row.get::<_,String>(9)?,"learning_mode":row.get::<_,String>(10)?,"content_revision":row.get::<_,i64>(11)?}),
    )
}

pub fn course(db: &Connection, id: &str) -> Result<Value, StorageError> {
    db.query_row(&format!("SELECT {COURSE_COLUMNS} FROM courses c LEFT JOIN plan_lines p ON p.id=c.plan_line_id WHERE c.id=?"),[id],course_row)
        .optional()?.ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))
}

pub fn list(db: &Connection, plan: Option<&str>) -> Result<Vec<Value>, StorageError> {
    let mut stmt = db.prepare(&format!("SELECT {COURSE_COLUMNS} FROM courses c LEFT JOIN plan_lines p ON p.id=c.plan_line_id
        LEFT JOIN plan_course_items m ON m.course_id=c.id AND m.plan_line_id=?1
        WHERE c.status='ACTIVE' AND (?1 IS NULL OR m.id IS NOT NULL) ORDER BY m.sequence_number,c.title,c.id"))?;
    let rows = stmt
        .query_map([plan.filter(|id| !id.is_empty())], course_row)?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows.into_iter().map(|c| json!({"id":c["id"],"title":c["title"],"summary":c["summary"],"subject":c["subject"],
        "content_type":c["content_type"],"difficulty":c["difficulty"],"source_type":c["source_type"],"plan_line":c["plan_line"]})).collect())
}

pub(crate) fn rows(db: &Connection, id: &str) -> Result<Vec<Value>, StorageError> {
    let mut query = db.prepare("SELECT id,title,position,markdown_path,summary,semantic_id FROM lessons WHERE course_id=? AND included=1 ORDER BY position,id")?;
    let mut lessons = query.query_map([id], |row|Ok(json!({"id":row.get::<_,String>(0)?,"title":row.get::<_,String>(1)?,
        "position":row.get::<_,i64>(2)?,"markdown_path":row.get::<_,String>(3)?,"summary":row.get::<_,String>(4)?,"semantic_id":row.get::<_,String>(5)?})))?.collect::<Result<Vec<_>,_>>()?;
    let mut exercises = db.prepare("SELECT id,title,prompt,requirements,exercise_type,position,semantic_id FROM exercises WHERE lesson_id=? AND included=1 ORDER BY position,id")?;
    for lesson in &mut lessons {
        let order = exercises.query_map([lesson["id"].as_str().unwrap()],|row|Ok(json!({"id":row.get::<_,String>(0)?,"title":row.get::<_,String>(1)?,
            "prompt":row.get::<_,String>(2)?,"requirements":row.get::<_,String>(3)?,"type":row.get::<_,String>(4)?,"position":row.get::<_,i64>(5)?,"semantic_id":row.get::<_,String>(6)?})))?.collect::<Result<Vec<_>,_>>()?;
        lesson["exercises"] = json!(order);
    }
    Ok(lessons)
}

pub(crate) fn read_markdown(root: &Path, relative: &str) -> Result<String, StorageError> {
    let path = file_paths::workspace_path(root, Path::new(relative))?;
    documents::read_text(File::open(path).map_err(|error| {
        StorageError::caused_by(
            if error.kind() == std::io::ErrorKind::NotFound {
                "DOCUMENT_NOT_FOUND"
            } else {
                "DOCUMENT_UNREADABLE"
            },
            error,
        )
    })?)
}

pub(crate) fn lesson_content(
    source: &str,
    exercises: &[Value],
) -> Result<(String, Vec<Value>), StorageError> {
    let ids: Vec<_> = exercises
        .iter()
        .map(|exercise| exercise["id"].as_str().unwrap().to_owned())
        .collect();
    let blocks = render_blocks(source, &ids).map_err(|error| match error {
        PresentationError::Storage(error) => error,
        PresentationError::Package(error) => {
            StorageError::caused_by("INVALID_COURSE_PACKAGE", error)
        }
    })?;
    Ok((documents::render(source, true)?, blocks))
}

pub fn detail(db: &Connection, root: &Path, id: &str) -> Result<Value, StorageError> {
    let mut info = course(db, id)?;
    let mut lessons = rows(db, id)?;
    let statuses = crate::planning::course_status(db, id)?;
    info.as_object_mut()
        .unwrap()
        .extend(statuses.as_object().unwrap().clone());
    let mut latest_progress = None;
    let mut percent = 0;
    let mut found_legacy = false;
    let ids: Vec<_> = lessons
        .iter()
        .flat_map(|l| l["exercises"].as_array().unwrap())
        .map(|exercise| exercise["id"].as_str().unwrap().to_owned())
        .collect();
    let submissions = crate::learning::attempt_history::latest_summaries(db, &ids)?;
    for lesson in &mut lessons {
        let lesson_id = lesson["id"].as_str().unwrap();
        let progress = db.query_row("SELECT progress_percent,status,last_position,COALESCE(updated_at,created_at,'') FROM learning_progress WHERE course_id=? AND lesson_id=?",
            params![id,lesson_id], |row| Ok((row.get::<_,i64>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?,row.get::<_,String>(3)?))).optional()?;
        let mut state = json!({"progress_percent":0,"status":"NOT_STARTED","last_position":""});
        if let Some((value, status, position, updated)) = progress {
            percent += value;
            if latest_progress
                .as_ref()
                .is_none_or(|(current, _)| updated > *current)
            {
                latest_progress = Some((updated, lesson_id.to_owned()));
            }
            state = json!({"progress_percent":value,"status":status,"last_position":position});
        }
        let relative = lesson["markdown_path"].as_str().unwrap();
        let exercises = lesson["exercises"].as_array().unwrap();
        let (status, html, blocks) = match read_markdown(root, relative) {
            Ok(source) => {
                let (html, blocks) = lesson_content(&source, exercises)?;
                found_legacy |= exercises.iter().any(|e| {
                    matches!(
                        e["type"].as_str(),
                        Some("READING_GROUP" | "LISTENING_GROUP" | "ESSAY")
                    )
                }) && documents::parse_front_matter(&source)
                    .is_ok_and(|(m, _)| m["content_schema"] == "studyflow.course-package/7");
                ("PRESENT", html, blocks)
            }
            Err(error) if error.code == "DOCUMENT_NOT_FOUND" => {
                ("MISSING", String::new(), Vec::new())
            }
            Err(error) if error.code == "DOCUMENT_UNREADABLE" => {
                ("UNREADABLE", String::new(), Vec::new())
            }
            Err(error) => return Err(error),
        };
        lesson.as_object_mut().unwrap().remove("semantic_id");
        for exercise in lesson["exercises"].as_array_mut().unwrap() {
            let (latest, draft) = submissions
                .get(exercise["id"].as_str().unwrap())
                .cloned()
                .unwrap_or_default();
            exercise.as_object_mut().unwrap().remove("semantic_id");
            exercise["latest_submission"] = json!(latest);
            exercise["draft"] = json!(draft);
        }
        lesson["document_status"] = json!(status);
        lesson["rendered_html"] = json!(html);
        lesson["content_blocks"] = json!(blocks);
        lesson["progress"] = state;
    }
    if found_legacy {
        info["legacy_practice"] = json!(true);
    }
    let reading_percent = if lessons.is_empty() {
        0
    } else {
        (percent as f64 / lessons.len() as f64).round_ties_even() as i64
    };
    let resume = latest_progress.map(|(_, id)| id);
    Ok(
        json!({"course":info,"lessons":lessons,"reading_percent":reading_percent,"resume_lesson_id":resume,
        "next_action":"按顺序阅读知识点并完成练习；阅读进度与练习通过状态分别记录。"}),
    )
}
