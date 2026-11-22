use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use super::{
    attempt_history::{summary, SUMMARY_COLUMNS},
    study_sessions,
};
use crate::{documents, infrastructure::StorageError, reviews};

pub(crate) fn summary_by_id(db: &Connection, id: &str) -> Result<Option<Value>, StorageError> {
    Ok(db
        .query_row(
            &format!("SELECT {SUMMARY_COLUMNS} FROM submissions WHERE id=?"),
            [id],
            summary,
        )
        .optional()?)
}

pub fn detail(db: &Connection, id: &str, check_current: bool) -> Result<Value, StorageError> {
    let row = db.query_row("SELECT exercise_id,answer_text,source,created_at,updated_at FROM submissions WHERE id=?",[id],
        |row|Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?,row.get::<_,Option<String>>(3)?,row.get::<_,Option<String>>(4)?)))
        .optional()?.ok_or_else(||StorageError::new("OBJECT_NOT_FOUND"))?;
    let (exercise, answer, source, created, updated) = row;
    let mut result = summary_by_id(db, id)?.ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    let (live_exercise, live_lesson, live_course) = db.query_row("SELECT e.id,e.title,e.prompt,e.requirements,l.id,l.title,l.position,l.markdown_path,c.id,c.title,c.plan_line_id
        FROM exercises e JOIN lessons l ON e.lesson_id=l.id JOIN courses c ON l.course_id=c.id WHERE e.id=?",[&exercise],|row|Ok((
        json!({"id":row.get::<_,String>(0)?,"title":row.get::<_,String>(1)?,"prompt":row.get::<_,String>(2)?,"requirements":row.get::<_,String>(3)?}),
        json!({"id":row.get::<_,String>(4)?,"title":row.get::<_,String>(5)?,"position":row.get::<_,i64>(6)?,"markdown_path":row.get::<_,String>(7)?}),
        json!({"id":row.get::<_,String>(8)?,"title":row.get::<_,String>(9)?,"plan_line_id":row.get::<_,Option<String>>(10)?}))))?;
    let session = result["study_session_id"].as_str();
    let context = session
        .map(|session| study_sessions::frozen_context(db, session, &exercise))
        .transpose()?
        .flatten();
    let current = if check_current {
        study_sessions::current(db, live_course["id"].as_str().unwrap())?.is_none_or(|round| {
            session == Some(round.id.as_str()) || session.is_none() && round.revision == 1
        })
    } else {
        true
    };
    let parent = result["parent_submission_id"]
        .as_str()
        .map(|parent| summary_by_id(db, parent))
        .transpose()?
        .flatten();
    let retest = reviews::retest_task(db, None, result["retest_task_id"].as_str())?;
    let mut query = db.prepare(&format!("SELECT {SUMMARY_COLUMNS} FROM submissions WHERE parent_submission_id=? ORDER BY attempt_number,id"))?;
    let children = query
        .query_map([id], summary)?
        .collect::<Result<Vec<_>, _>>()?;
    let (exercise, lesson, course) =
        context
            .as_ref()
            .map_or((live_exercise, live_lesson, live_course), |c| {
                (
                    c["exercise"].clone(),
                    c["lesson"].clone(),
                    c["course"].clone(),
                )
            });
    let state = if context.is_some() {
        "FROZEN"
    } else {
        "LEGACY_UNVERSIONED"
    };
    result.as_object_mut().unwrap().extend(json!({"is_current_study":current,"study_context":context,"snapshot_status":state,
        "answer_text":answer,"source":source,"retest_task":retest,"created_at":timestamp(created),"updated_at":timestamp(updated),"parent":parent,"children":children,
        "exercise":exercise,"lesson":lesson,"course":course,"reviews":reviews_for(db,id)?}).as_object().unwrap().clone());
    Ok(result)
}

fn timestamp(value: Option<String>) -> Option<String> {
    value.map(|text| {
        let text = text.replacen('T', " ", 1);
        match text.split_once('.') {
            Some((seconds, fraction)) if fraction.chars().all(|ch| ch == '0') => seconds.to_owned(),
            Some((seconds, fraction))
                if fraction.bytes().all(|byte| byte.is_ascii_digit()) && fraction.len() < 6 =>
            {
                format!("{seconds}.{fraction:0<6}")
            }
            _ => text,
        }
    })
}

fn reviews_for(db: &Connection, submission: &str) -> Result<Vec<Value>, StorageError> {
    let mut query = db.prepare("SELECT id,reference_hash,reference_revision,reference_reason,summary,detail_markdown,issues_json,issue_count,decision,next_action,created_at FROM review_feedback WHERE submission_id=? ORDER BY created_at,id")?;
    let mut rows = query.query([submission])?;
    let mut reviews = Vec::new();
    while let Some(row) = rows.next()? {
        let markdown: String = row.get(5)?;
        let issues: Value = serde_json::from_str(
            &row.get::<_, Option<String>>(6)?
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| "[]".into()),
        )
        .map_err(|err| StorageError::caused_by("DATABASE_ERROR", err))?;
        reviews.push(json!({"id":row.get::<_,String>(0)?,"reference_hash":row.get::<_,Option<String>>(1)?,"reference_revision":row.get::<_,Option<i64>>(2)?,"reference_reason":row.get::<_,String>(3)?,
            "summary":row.get::<_,String>(4)?,"detail_markdown":markdown,"rendered_html":documents::render(&markdown,false)?,"issues":issues,
            "issue_count":row.get::<_,i64>(7)?,"decision":row.get::<_,String>(8)?,"next_action":row.get::<_,String>(9)?,"created_at":timestamp(row.get(10)?)}));
    }
    Ok(reviews)
}

pub(crate) fn claim_parent(
    db: &Connection,
    parent: &Value,
    child: &str,
    source: &str,
) -> Result<(), StorageError> {
    let id = parent["id"].as_str().unwrap();
    // The caller has already inserted the new child in this transaction.
    let occupied = db.query_row("SELECT EXISTS(SELECT 1 FROM submissions WHERE parent_submission_id=?1 AND id<>?2) OR EXISTS(SELECT 1 FROM submission_chain_links WHERE parent_id=?1)",params![id,child],|row| row.get::<_,bool>(0))?;
    if occupied || db.execute("UPDATE submissions SET version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?",params![id,parent["version"].as_i64()])?!=1 {
        return Err(StorageError::new("VERSION_CONFLICT"));
    }
    db.execute(
        "INSERT INTO submission_chain_links(parent_id,child_id,source,reason) VALUES(?,?,?,'')",
        params![id, child, source],
    )?;
    Ok(())
}
