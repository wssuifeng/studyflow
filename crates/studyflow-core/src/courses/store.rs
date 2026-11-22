use std::{fs, path::Path};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    documents,
    infrastructure::{file_paths, StorageError},
};

use super::presentation::fallback_markdown;

pub(super) fn load_json(text: &str) -> Result<Value, StorageError> {
    serde_json::from_str(text).map_err(|error| StorageError::caused_by("DATABASE_ERROR", error))
}

pub(super) fn value_text(value: &Value, field: &str) -> String {
    match value.get(field) {
        None => String::new(),
        Some(Value::String(s)) => s.trim().to_owned(),
        Some(Value::Null) => "None".into(),
        Some(value) => value.to_string(),
    }
}

pub(super) struct CourseFields<'a> {
    pub title: &'a str,
    pub summary: &'a str,
    pub subject: &'a str,
    pub difficulty: &'a str,
    pub mode: &'a str,
    pub content_type: &'a str,
    pub source_type: &'a str,
}

impl<'a> CourseFields<'a> {
    pub fn from_package(package: &'a Value) -> Self {
        let source = &package["course"];
        Self {
            title: source["title"].as_str().unwrap(),
            summary: source["summary"].as_str().unwrap_or_default(),
            subject: source["subject"].as_str().unwrap_or_default(),
            difficulty: source["difficulty"].as_str().unwrap_or_default(),
            mode: source["learning_mode"].as_str().unwrap_or("general"),
            content_type: "LESSON",
            source_type: "AGENT_CLI",
        }
    }
}

pub(super) fn plan_named(db: &Connection, name: &str) -> Result<String, StorageError> {
    db.query_row("SELECT id FROM plan_lines WHERE name=?", [name], |row| {
        row.get(0)
    })
    .optional()?
    .ok_or_else(|| StorageError::new("PLAN_LINE_NOT_FOUND"))
}

pub(super) fn matching_course(
    db: &Connection,
    plan: &str,
    title: &str,
) -> Result<Option<String>, StorageError> {
    Ok(db
        .query_row(
            "SELECT id FROM courses WHERE plan_line_id=? AND title=?",
            params![plan, title],
            |row| row.get(0),
        )
        .optional()?)
}

pub(super) fn insert_course(
    db: &Connection,
    plan: &str,
    fields: &CourseFields<'_>,
) -> Result<String, StorageError> {
    let id = Uuid::new_v4().to_string();
    db.execute("INSERT INTO courses(id,plan_line_id,title,summary,subject,difficulty,learning_mode,content_type,source_type,version,status)
         VALUES(?,?,?,?,?,?,?,?,?,1,'ACTIVE')",params![id,plan,fields.title,fields.summary,fields.subject,fields.difficulty,fields.mode,fields.content_type,fields.source_type])?;
    Ok(id)
}

pub(super) fn insert_lesson(
    db: &Connection,
    id: &str,
    course: &str,
    semantic_id: &str,
    title: &str,
    position: i64,
    relative: &str,
    summary: &str,
) -> Result<(), StorageError> {
    db.execute("INSERT INTO lessons(id,course_id,semantic_id,title,position,markdown_path,summary,included) VALUES(?,?,?,?,?,?,?,1)
        ON CONFLICT(id) DO UPDATE SET title=excluded.title, position=excluded.position, markdown_path=excluded.markdown_path,
        semantic_id=excluded.semantic_id,included=1,updated_at=CURRENT_TIMESTAMP",
        params![id,course,semantic_id,title,position,relative,summary])?;
    Ok(())
}

pub(super) fn insert_exercise(
    db: &Connection,
    id: &str,
    lesson: &str,
    exercise: &Value,
    position: usize,
) -> Result<(), StorageError> {
    db.execute("INSERT INTO exercises(id,lesson_id,semantic_id,title,prompt,requirements,exercise_type,position,included) VALUES(?,?,?,?,?,?,?,?,1)
        ON CONFLICT(id) DO UPDATE SET title=excluded.title,prompt=excluded.prompt,requirements=excluded.requirements,
        exercise_type=excluded.exercise_type,position=excluded.position,semantic_id=excluded.semantic_id,included=1,updated_at=CURRENT_TIMESTAMP",
        params![id,lesson,exercise["id"].as_str().unwrap_or_default(),exercise["title"].as_str().unwrap(),
            exercise["prompt"].as_str().unwrap(),exercise["requirements"].as_str().unwrap_or_default(),
            exercise["type"].as_str().unwrap_or("SHORT_ANSWER"),position as i64+1])?;
    if let Some(spec) = exercise.get("english") {
        db.execute(
            "INSERT INTO english_items(exercise_id,spec_json) VALUES(?,?)
            ON CONFLICT(exercise_id) DO UPDATE SET spec_json=excluded.spec_json",
            params![id, spec.to_string()],
        )?;
    }
    Ok(())
}

pub(super) fn publish_lesson(
    root: &Path,
    relative: &str,
    metadata: &Value,
    lesson: &Value,
) -> Result<(), StorageError> {
    let body = fallback_markdown(lesson);
    // JSON objects are valid YAML mappings. Old front matter is accepted by value
    // when retrying the same immutable source written by the previous runtime.
    let encoded = serde_json::to_string_pretty(metadata).expect("metadata is JSON");
    let source = format!("---\n{encoded}\n---\n{body}");
    let path = file_paths::workspace_path(root, Path::new(relative))?;
    fs::create_dir_all(path.parent().expect("lesson folder"))?;
    if !path.exists() && file_paths::write_if_absent(&path, source.as_bytes())? {
        return Ok(());
    }
    let current = documents::read_text(fs::File::open(path)?)?;
    if current == source
        || documents::parse_front_matter(&current)
            .is_ok_and(|(existing, text)| existing == *metadata && text == body)
    {
        Ok(())
    } else {
        Err(StorageError::new("COURSE_PACKAGE_FILE_CONFLICT"))
    }
}

pub(super) fn lesson_meta(package: &Value, lesson: &Value) -> Value {
    json!({"content_schema":package["schema"],"learning_mode":CourseFields::from_package(package).mode,
        "structured_lesson":lesson,"exercises":lesson.get("exercises").cloned().unwrap_or_else(||json!([]))})
}

pub(super) fn write_package_lessons(
    db: &Connection,
    root: &Path,
    course: &str,
    package: &Value,
    hash: &str,
    revision: i64,
    mapping: &mut Value,
) -> Result<(Vec<String>, Vec<String>), StorageError> {
    let source = CourseFields::from_package(package);
    let id = package["package_id"].as_str().unwrap();
    let folder = if revision == 1 {
        format!("content/course-packages/{id}/{hash}")
    } else {
        format!("content/course-revisions/{course}/{revision}-{hash}")
    };
    let mut lesson_ids = Vec::new();
    let mut paths = Vec::new();
    for (index, lesson) in package["lessons"].as_array().unwrap().iter().enumerate() {
        let semantic = lesson["id"].as_str().unwrap();
        let title = lesson["title"].as_str().unwrap();
        let relative = format!("{folder}/{semantic}.md");
        let mut meta = lesson_meta(package, lesson);
        if revision == 1 {
            meta.as_object_mut().unwrap().extend(
                json!({"course":source.title,"lesson":title,"plan_line":package["plan_line"],
                "summary":source.summary,"package_id":id,"package_hash":hash})
                .as_object()
                .unwrap()
                .clone(),
            );
        }
        publish_lesson(root, &relative, &meta, lesson)?;
        let lesson_id = mapped_id(&mapping["lessons"][semantic]);
        insert_lesson(
            db,
            &lesson_id,
            course,
            semantic,
            title,
            index as i64 + 1,
            &relative,
            "",
        )?;
        mapping["lessons"][semantic] = json!(lesson_id);
        for (position, exercise) in lesson["exercises"]
            .as_array()
            .into_iter()
            .flatten()
            .enumerate()
        {
            let key = format!("{semantic}:{}", exercise["id"].as_str().unwrap());
            let exercise_id = mapped_id(&mapping["exercises"][&key]);
            insert_exercise(db, &exercise_id, &lesson_id, exercise, position)?;
            mapping["exercises"][key] = json!(exercise_id);
        }
        if documents::register(root, db, &relative, Some("LESSON"))?.status != "PRESENT" {
            return Err(StorageError::new("DOCUMENT_UNREADABLE"));
        }
        lesson_ids.push(lesson_id);
        paths.push(relative);
    }
    Ok((lesson_ids, paths))
}

fn mapped_id(value: &Value) -> String {
    value
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| Uuid::new_v4().to_string())
}
