use std::{fs, path::Path};

use rusqlite::Connection;
use serde_json::{json, Value};

use crate::{
    application::write_contract::atomic_write,
    infrastructure::{
        events,
        file_paths::{self, portable_relative},
        leases::Lease,
        sqlite, StorageError,
    },
    workspace::{archive, Workspace},
};

const SCOPE: &str = "WITH selected_courses AS (SELECT id,title,created_at FROM courses WHERE ?1 IS NULL OR id IN (SELECT value FROM json_each(?1))),
    selected_lessons AS (SELECT id,markdown_path FROM lessons WHERE course_id IN (SELECT id FROM selected_courses)),
    selected_exercises AS (SELECT id FROM exercises WHERE lesson_id IN (SELECT id FROM selected_lessons)),
    selected_studies AS (SELECT id FROM course_study_sessions WHERE course_id IN (SELECT id FROM selected_courses)),
    selected_answers AS (SELECT id FROM submissions WHERE exercise_id IN (SELECT id FROM selected_exercises)),
    selected_retests AS (SELECT id FROM retest_tasks WHERE parent_submission_id IN (SELECT id FROM selected_answers) OR study_session_id IN (SELECT id FROM selected_studies)),
    selected_items AS (SELECT id FROM plan_course_items WHERE course_id IN (SELECT id FROM selected_courses)),
    selected_schedule AS (SELECT id FROM course_schedule_items WHERE plan_course_item_id IN (SELECT id FROM selected_items)),
    selected_tasks AS (SELECT id FROM tasks WHERE course_schedule_item_id IN (SELECT id FROM selected_schedule)),
    selected_errors AS (SELECT id FROM english_error_aggregates WHERE course_id IN (SELECT id FROM selected_courses)),
    selected_general AS (SELECT id FROM general_mistake_entries WHERE course_id IN (SELECT id FROM selected_courses))";

const EXTENSIONS: &[(&str, &str)] = &[
    (
        "course_reference_views",
        "study_session_id IN (SELECT id FROM selected_studies)",
    ),
    (
        "english_remediation_sources",
        "course_id IN (SELECT id FROM selected_courses)",
    ),
    (
        "english_remediation_courses",
        "course_id IN (SELECT id FROM selected_courses)",
    ),
    (
        "english_review_items",
        "aggregate_id IN (SELECT id FROM selected_errors)",
    ),
    (
        "english_error_evidence",
        "aggregate_id IN (SELECT id FROM selected_errors)",
    ),
    (
        "english_error_aggregates",
        "id IN (SELECT id FROM selected_errors)",
    ),
    (
        "general_mistake_occurrences",
        "entry_id IN (SELECT id FROM selected_general)",
    ),
    (
        "general_mistake_entries",
        "id IN (SELECT id FROM selected_general)",
    ),
    (
        "english_submission_details",
        "submission_id IN (SELECT id FROM selected_answers)",
    ),
    (
        "english_check_attempts",
        "study_session_id IN (SELECT id FROM selected_studies)",
    ),
    (
        "english_study_states",
        "study_session_id IN (SELECT id FROM selected_studies)",
    ),
    (
        "english_items",
        "exercise_id IN (SELECT id FROM selected_exercises)",
    ),
];

const SETS: &[(&str, &str, &str)] = &[
    ("selected_courses", "course_ids", "courses"),
    ("selected_lessons", "lesson_ids", "lessons"),
    ("selected_exercises", "exercise_ids", "exercises"),
    ("selected_studies", "study_session_ids", "study_sessions"),
    ("selected_answers", "submission_ids", "submissions"),
    ("selected_retests", "retest_task_ids", "retest_tasks"),
    (
        "selected_items",
        "plan_course_item_ids",
        "plan_course_items",
    ),
    ("selected_schedule", "schedule_item_ids", "schedule_items"),
    ("selected_tasks", "linked_task_ids", "linked_tasks"),
];

fn strings(
    db: &Connection,
    ids: &Option<String>,
    select: &str,
) -> Result<Vec<String>, StorageError> {
    let mut query = db.prepare(&format!("{SCOPE} {select}"))?;
    let values = query
        .query_map([ids], |row| row.get(0))?
        .collect::<Result<_, _>>()?;
    Ok(values)
}

fn inventory(db: &Connection, ids: &Option<String>) -> Result<Value, StorageError> {
    let mut result = json!({"deleted":false,"counts":{}});
    for (table, field, count) in SETS {
        let order = if *table == "selected_courses" {
            "created_at,id"
        } else {
            "id"
        };
        let values = strings(db, ids, &format!("SELECT id FROM {table} ORDER BY {order}"))?;
        result["counts"][count] = json!(values.len());
        result[field] = json!(values);
    }
    result["course_titles"] = json!(strings(
        db,
        ids,
        "SELECT title FROM selected_courses ORDER BY created_at,id"
    )?);
    let paths = strings(db,ids,"SELECT DISTINCT markdown_path FROM selected_lessons WHERE markdown_path<>'' ORDER BY markdown_path")?;
    let protected = strings(db,ids,"SELECT DISTINCT p.markdown_path FROM selected_lessons p WHERE p.markdown_path<>'' AND (
        EXISTS(SELECT 1 FROM lessons l WHERE l.markdown_path=p.markdown_path AND l.course_id NOT IN (SELECT id FROM selected_courses)) OR
        EXISTS(SELECT 1 FROM course_study_sessions s, json_each(s.snapshot_json,'$.lessons') l
            WHERE s.course_id NOT IN (SELECT id FROM selected_courses) AND json_extract(l.value,'$.markdown_path')=p.markdown_path)) ORDER BY p.markdown_path")?;
    let deletable: Vec<_> = paths
        .iter()
        .filter(|path| protected.binary_search(path).is_err())
        .collect();
    result["document_paths"] = json!(paths);
    result["deletable_document_paths"] = json!(deletable);
    result["protected_document_paths"] = json!(protected);
    result["counts"]["documents"] = json!(deletable.len());
    result["counts"]["protected_documents"] = json!(protected.len());
    // These three counters were historically estimated by ownership roots.
    result["counts"]["review_feedback"] = result["counts"]["submissions"].clone();
    result["counts"]["course_revisions"] = result["counts"]["courses"].clone();
    result["counts"]["learning_progress"] = result["counts"]["courses"].clone();
    for (table, predicate) in EXTENSIONS {
        let count: i64 = db.query_row(
            &format!("{SCOPE} SELECT COUNT(*) FROM {table} WHERE {predicate}"),
            [ids],
            |r| r.get(0),
        )?;
        result["counts"][table] = json!(count);
    }
    Ok(result)
}

pub fn preview(workspace: &Workspace, ids: Option<&[String]>) -> Result<Value, StorageError> {
    let ids = ids.map(|ids| json!(ids).to_string());
    workspace.read_consistent(|db| inventory(db, &ids))
}

fn remove_rows(db: &Connection, ids: &Option<String>, info: &Value) -> Result<(), StorageError> {
    let dependent = db.query_row(&format!("{SCOPE} SELECT EXISTS(SELECT 1 FROM english_remediation_sources
        WHERE aggregate_id IN (SELECT id FROM selected_errors) AND course_id NOT IN (SELECT id FROM selected_courses))"), [ids], |r|r.get::<_,bool>(0))?;
    if dependent {
        return Err(StorageError::new("COURSE_HAS_REMEDIATION_DEPENDENCIES"));
    }
    // Freeze ID sets before any relational delete changes their membership.
    for (table, field, _) in SETS {
        db.execute_batch(&format!(
            "CREATE TEMP TABLE {table}(id TEXT PRIMARY KEY) WITHOUT ROWID"
        ))?;
        db.execute(
            &format!("INSERT INTO {table} SELECT value FROM json_each(?)"),
            [info[field].to_string()],
        )?;
    }
    db.execute_batch("CREATE TEMP TABLE selected_errors AS SELECT id FROM english_error_aggregates WHERE course_id IN (SELECT id FROM selected_courses);
        CREATE TEMP TABLE selected_general AS SELECT id FROM general_mistake_entries WHERE course_id IN (SELECT id FROM selected_courses);")?;
    for (table, predicate) in EXTENSIONS {
        db.execute(&format!("DELETE FROM {table} WHERE {predicate}"), [])?;
    }
    db.execute_batch(r#"
UPDATE submissions SET parent_submission_id=NULL,retest_task_id=NULL WHERE id IN (SELECT id FROM selected_answers);
DELETE FROM review_feedback WHERE submission_id IN (SELECT id FROM selected_answers);
DELETE FROM submission_chain_links WHERE parent_id IN (SELECT id FROM selected_answers) OR child_id IN (SELECT id FROM selected_answers);
DELETE FROM submission_write_receipts WHERE submission_id IN (SELECT id FROM selected_answers);
DELETE FROM study_notes WHERE study_session_id IN (SELECT id FROM selected_studies);
DELETE FROM study_note_receipts WHERE study_session_id IN (SELECT id FROM selected_studies);
DELETE FROM retest_tasks WHERE id IN (SELECT id FROM selected_retests);
DELETE FROM submissions WHERE id IN (SELECT id FROM selected_answers);
DELETE FROM course_write_receipts WHERE course_id IN (SELECT id FROM selected_courses) OR study_session_id IN (SELECT id FROM selected_studies);
DELETE FROM course_study_sessions WHERE id IN (SELECT id FROM selected_studies);
DELETE FROM learning_progress WHERE course_id IN (SELECT id FROM selected_courses);
DELETE FROM course_revisions WHERE course_id IN (SELECT id FROM selected_courses);
UPDATE submissions SET task_id=NULL WHERE task_id IN (SELECT id FROM selected_tasks);
DELETE FROM time_blocks WHERE task_id IN (SELECT id FROM selected_tasks);
DELETE FROM tasks WHERE id IN (SELECT id FROM selected_tasks);
DELETE FROM course_schedule_items WHERE id IN (SELECT id FROM selected_schedule);
DELETE FROM plan_course_items WHERE id IN (SELECT id FROM selected_items);
UPDATE plan_lines SET focus_course_id=NULL WHERE focus_course_id IN (SELECT id FROM selected_courses);
DELETE FROM exercises WHERE id IN (SELECT id FROM selected_exercises);
DELETE FROM lessons WHERE id IN (SELECT id FROM selected_lessons);
DELETE FROM courses WHERE id IN (SELECT id FROM selected_courses);
"#)?;
    db.execute(
        "DELETE FROM documents WHERE relative_path IN (SELECT value FROM json_each(?))",
        [info["deletable_document_paths"].to_string()],
    )?;
    events::record(
        db,
        "AGENT_CLI",
        "workspace",
        "courses",
        "PURGE_COURSES",
        &format!("清理 {} 门课程及其课程专属数据", info["counts"]["courses"]),
    )?;
    Ok(())
}

pub fn purge(
    workspace: &Workspace,
    ids: Option<&[String]>,
    backup: &Path,
) -> Result<Value, StorageError> {
    let checked = archive::validate(backup)?;
    let settings = workspace.settings();
    let _lease = Lease::exclusive(&settings.workspace)?;
    let mut db = sqlite::write_existing(&settings.database)?;
    let ids = ids.map(|ids| json!(ids).to_string());
    let mut result = atomic_write(&mut db, |db| {
        let info = inventory(db, &ids)?;
        if info["counts"]["courses"] != 0 {
            remove_rows(db, &ids, &info)?;
        }
        Ok(info)
    })?;
    let mut removed = Vec::new();
    let mut warnings = Vec::new();
    for relative in result["deletable_document_paths"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(Value::as_str)
    {
        let original = settings.workspace.join(relative);
        let candidate = portable_relative(relative)
            .and_then(|_| file_paths::workspace_path(&settings.workspace, Path::new(relative)));
        if !candidate.as_ref().is_ok_and(|path| path == &original) {
            warnings.push(format!("课程文档路径未通过校验：{relative}"));
            continue;
        }
        match fs::symlink_metadata(&original) {
            Ok(meta) if meta.is_file() && !file_paths::is_link(&meta) => {
                match fs::remove_file(&original) {
                    Ok(()) => removed.push(relative.to_owned()),
                    Err(error) => warnings.push(format!("课程文档未能删除：{relative}（{error}）")),
                }
            }
            Ok(_) => warnings.push(format!("课程文档不是普通文件：{relative}")),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => warnings.push(format!("课程文档未能检查：{relative}（{error}）")),
        }
    }
    result["deleted"] = json!(result["counts"]["courses"] != 0);
    result["files_removed"] = json!(removed);
    result["warnings"] = json!(warnings);
    result["backup"] = json!(checked);
    Ok(result)
}
