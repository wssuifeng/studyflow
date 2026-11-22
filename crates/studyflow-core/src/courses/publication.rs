use std::{fs::File, path::Path};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    documents,
    infrastructure::{events, StorageError},
    planning::{ensure_membership, Track},
};

use super::store::{self, CourseFields};

pub(crate) fn import_package(
    db: &Connection,
    root: &Path,
    package: &Value,
    summary: Value,
    track: Track,
) -> Result<Value, StorageError> {
    let package_id = package["package_id"].as_str().unwrap();
    let hash = summary["content_hash"].as_str().unwrap();
    if let Some((id, revision, mapping)) = db.query_row(
        "SELECT course_id,number,mapping_json FROM course_revisions
         WHERE json_extract(package_json,'$.package_id')=? AND content_hash=? ORDER BY number DESC LIMIT 1",
        params![package_id,hash],|row|Ok((row.get::<_,String>(0)?,row.get::<_,i64>(1)?,row.get::<_,String>(2)?)),
    ).optional()? {
        let mapping = store::load_json(&mapping)?;
        let ids: Vec<_> = package["lessons"].as_array().unwrap().iter().map(|lesson| &mapping["lessons"][lesson["id"].as_str().unwrap()]).collect();
        if ids.iter().any(|id| !id.is_string()) {
            return Err(StorageError::new("COURSE_SOURCE_CONFLICT"));
        }
        return Ok(join(summary, json!({"created":false,"course_id":id,"revision":revision,"lesson_ids":ids})));
    }
    let known = db.query_row("SELECT 1 FROM course_revisions WHERE json_extract(package_json,'$.package_id')=? LIMIT 1",[package_id], |_|Ok(())).optional()?.is_some();
    if known {
        return Err(StorageError::new("COURSE_PACKAGE_CONFLICT"));
    }
    let prefix = format!("content/course-packages/{package_id}/");
    let mut stmt = db.prepare("SELECT course_id,id,markdown_path FROM lessons WHERE substr(markdown_path,1,length(?1))=?1")?;
    let registered = stmt
        .query_map([&prefix], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
            ))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    if let Some((id, _, _)) = registered.first() {
        let mut ids = Vec::new();
        for lesson in package["lessons"].as_array().unwrap() {
            let relative = format!("{prefix}{hash}/{}.md", lesson["id"].as_str().unwrap());
            let stored = registered
                .iter()
                .find(|(course, _, path)| course == id && path == &relative)
                .ok_or_else(|| StorageError::new("COURSE_PACKAGE_CONFLICT"))?;
            ids.push(stored.1.as_str());
        }
        if ids.len() != registered.len() {
            return Err(StorageError::new("COURSE_PACKAGE_CONFLICT"));
        }
        return Ok(join(
            summary,
            json!({"created":false,"course_id":id,"lesson_ids":ids}),
        ));
    }
    drop(stmt);
    let plan = store::plan_named(db, package["plan_line"].as_str().unwrap())?;
    let fields = CourseFields::from_package(package);
    if store::matching_course(db, &plan, fields.title)?.is_some() {
        return Err(StorageError::new("COURSE_ALREADY_EXISTS"));
    }
    let id = store::insert_course(db, &plan, &fields)?;
    let item = ensure_membership(db, &plan, &id, track)?;
    let mut mapping = json!({"lessons":{},"exercises":{}});
    let (lesson_ids, paths) =
        store::write_package_lessons(db, root, &id, package, hash, 1, &mut mapping)?;
    db.execute("INSERT INTO course_revisions(id,course_id,number,package_json,mapping_json,content_hash,result_json)
        VALUES(?,?,1,?,?,?,'{}')",params![Uuid::new_v4().to_string(),id,package.to_string(),mapping.to_string(),hash])?;
    events::record(db, "AGENT_CLI", "course", &id, "IMPORT_PACKAGE", package_id)?;
    Ok(join(
        summary,
        json!({"created":true,"course_id":id,"plan_id":plan,"plan_course_item_id":item,"lesson_ids":lesson_ids,"paths":paths}),
    ))
}

fn join(mut base: Value, extras: Value) -> Value {
    base.as_object_mut()
        .unwrap()
        .extend(extras.as_object().unwrap().clone());
    base
}

pub(crate) struct MarkdownSource {
    relative: String,
    metadata: Value,
    exercises: Vec<Value>,
    content_type: String,
    document_type: String,
}

impl MarkdownSource {
    pub(crate) fn read(root: &Path, source: &Path) -> Result<Self, StorageError> {
        let (path, relative) = documents::markdown_import_path(root, source)?;
        let text = documents::read_text(File::open(path)?)?;
        let (metadata, _) = documents::parse_front_matter(&text)?;
        let metadata = documents::validate_import_metadata(&metadata)?;
        let content_type = checked_type(
            &metadata,
            "content_type",
            "LESSON",
            &[
                "LESSON",
                "REFERENCE",
                "EXAM_PREP",
                "PROJECT_GUIDE",
                "REVIEW",
                "OTHER",
            ],
            "INVALID_CONTENT_TYPE",
        )?;
        let document_type = checked_type(
            &metadata,
            "document_type",
            "LESSON",
            &[
                "LESSON",
                "REVIEW",
                "PROJECT",
                "PLAN",
                "SNAPSHOT",
                "REFERENCE",
                "ANSWER",
                "FEEDBACK",
                "OTHER",
                "MARKDOWN",
            ],
            "INVALID_DOCUMENT_TYPE",
        )?;
        let mut exercises = Vec::new();
        for item in metadata["exercises"].as_array().unwrap() {
            let required = |key| {
                item[key]
                    .as_str()
                    .map(str::trim)
                    .filter(|v| !v.is_empty())
                    .ok_or_else(|| StorageError::new("INVALID_EXERCISE_METADATA"))
            };
            let kind = checked_type(
                item,
                "type",
                "SHORT_ANSWER",
                &[
                    "SHORT_ANSWER",
                    "CODE",
                    "ESSAY",
                    "EXAM_QUESTION",
                    "CHECKLIST",
                    "SELF_EXPLANATION",
                    "PROJECT_ANALYSIS",
                    "OTHER",
                ],
                "INVALID_EXERCISE_TYPE",
            )?;
            exercises.push(json!({"title":required("title")?,"prompt":required("prompt")?,"type":kind,"requirements":store::value_text(item,"requirements")}));
        }
        Ok(Self {
            relative,
            metadata,
            exercises,
            content_type,
            document_type,
        })
    }
}

fn checked_type(
    value: &Value,
    key: &str,
    default: &str,
    allowed: &[&str],
    error: &'static str,
) -> Result<String, StorageError> {
    let value = if value.get(key).is_none() {
        default.to_owned()
    } else {
        store::value_text(value, key).to_uppercase()
    };
    if allowed.contains(&value.as_str()) {
        Ok(value)
    } else {
        Err(StorageError::new(error))
    }
}

pub(crate) fn import_markdown(
    db: &Connection,
    root: &Path,
    source: &MarkdownSource,
) -> Result<Value, StorageError> {
    let relative = &source.relative;
    if let Some((id,lesson,plan)) = db.query_row("SELECT c.id,l.id,c.plan_line_id FROM lessons l JOIN courses c ON c.id=l.course_id WHERE l.markdown_path=?",
        [relative],|row|Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?,row.get::<_,Option<String>>(2)?))).optional()? {
        if let Some(plan) = plan { ensure_membership(db,&plan,&id,Track::Main)?; }
        return Ok(json!({"created":false,"course_id":id,"lesson_id":lesson,"path":relative}));
    }
    let meta = &source.metadata;
    let plan = store::plan_named(db, meta["plan_line"].as_str().unwrap())?;
    let fields = CourseFields {
        title: meta["course"].as_str().unwrap(),
        summary: &store::value_text(meta, "summary"),
        subject: &store::value_text(meta, "subject"),
        difficulty: &store::value_text(meta, "difficulty").to_uppercase(),
        mode: "general",
        content_type: &source.content_type,
        source_type: &if meta.get("source_type").is_some() {
            store::value_text(meta, "source_type").to_uppercase()
        } else {
            "AGENT_CLI".to_owned()
        },
    };
    let id = match store::matching_course(db, &plan, fields.title)? {
        Some(id) => id,
        None => store::insert_course(db, &plan, &fields)?,
    };
    let item = ensure_membership(db, &plan, &id, Track::Main)?;
    let position = db.query_row(
        "SELECT COALESCE(MAX(position),0)+1 FROM lessons WHERE course_id=?",
        [&id],
        |r| r.get(0),
    )?;
    let lesson = Uuid::new_v4().to_string();
    store::insert_lesson(
        db,
        &lesson,
        &id,
        "",
        meta["lesson"].as_str().unwrap(),
        position,
        relative,
        fields.summary,
    )?;
    for (position, exercise) in source.exercises.iter().enumerate() {
        store::insert_exercise(db, &Uuid::new_v4().to_string(), &lesson, exercise, position)?;
    }
    if documents::register(root, db, relative, Some(&source.document_type))?.status != "PRESENT" {
        return Err(StorageError::new("DOCUMENT_UNREADABLE"));
    }
    events::record(db, "AGENT_CLI", "course", &id, "IMPORT_MARKDOWN", relative)?;
    Ok(
        json!({"created":true,"course_id":id,"lesson_id":lesson,"plan_course_item_id":item,"path":relative,"course_title":fields.title}),
    )
}
