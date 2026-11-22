use std::collections::{HashMap, HashSet};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use time::Date;

use super::{date_text, exposed_time, get_plan};
use crate::{
    infrastructure::StorageError,
    learning::attempt_history::{frozen_exercise_ids, latest_statuses, passed},
};

pub(super) struct Member {
    id: String,
    plan: String,
    course: String,
    track: String,
    position: i64,
    management: String,
    reason: String,
    planned_start: Option<String>,
    planned_end: Option<String>,
}

pub(super) fn members(
    db: &Connection,
    plan: Option<&str>,
    track: Option<&str>,
) -> Result<Vec<Member>, StorageError> {
    let mut query = db.prepare(
        "SELECT id,plan_line_id,course_id,track,sequence_number,management_position,management_reason,planned_start,planned_end
         FROM plan_course_items WHERE (?1 IS NULL OR plan_line_id=?1) AND (?2 IS NULL OR track=?2)
         ORDER BY plan_line_id,sequence_number,id",
    )?;
    let rows = query
        .query_map(params![plan, track], |row| {
            Ok(Member {
                id: row.get(0)?,
                plan: row.get(1)?,
                course: row.get(2)?,
                track: row.get(3)?,
                position: row.get(4)?,
                management: row.get(5)?,
                reason: row.get(6)?,
                planned_start: row.get(7)?,
                planned_end: row.get(8)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}

pub fn plan_detail(db: &Connection, identifier: &str, date: Date) -> Result<Value, StorageError> {
    let mut plan = get_plan(db, identifier)?;
    let id = plan["id"].as_str().expect("plan ID");
    let members = members(db, Some(id), None)?;
    let total = members.iter().filter(|item| item.track == "MAIN").count();
    let day = date_text(date);
    let mut courses = Vec::with_capacity(total);
    for member in members.iter().filter(|item| item.track == "MAIN") {
        let schedule = schedule_for(db, &member.id, &day)?;
        courses.push(course_summary(db, member, schedule, total)?);
    }
    let pending = || {
        courses
            .iter()
            .filter(|course| course["learning_group"] == "PENDING")
    };
    let current = if plan["status"] == "ACTIVE" {
        pending()
            .find(|course| course["id"] == plan["focus_course_id"])
            .or_else(|| pending().next())
            .cloned()
    } else {
        None
    };
    let completed = courses
        .iter()
        .filter(|course| course["learning_group"] == "COMPLETED")
        .count();
    let normal = courses
        .iter()
        .filter(|course| course["learning_group"] != "OTHER")
        .count();
    plan["course_total"] = json!(total);
    plan["supplement_total"] = json!(members.len() - total);
    plan["completed_courses"] = json!(completed);
    plan["progress_percent"] = json!(percent(completed, normal));
    plan["today_course_count"] = json!(courses
        .iter()
        .filter(|course| !course["schedule"].is_null())
        .count());
    Ok(
        json!({"plan":plan,"target_date":day,"current_course":current,"courses":courses,"next_action":"按课程序号进入当前课程。"}),
    )
}

fn percent(numerator: usize, denominator: usize) -> u64 {
    if denominator == 0 {
        return 0;
    }
    (numerator as f64 / denominator as f64 * 100.0).round_ties_even() as u64
}

fn schedule_for(db: &Connection, member: &str, day: &str) -> Result<Option<Value>, StorageError> {
    Ok(db.query_row(
        "SELECT status,start_time,end_time FROM course_schedule_items WHERE plan_course_item_id=? AND scheduled_date=? AND status<>'CANCELLED'",
        params![member,day], |row| Ok(json!({"date":day,"status":row.get::<_,String>(0)?, "start_time":exposed_time(row.get(1)?), "end_time":exposed_time(row.get(2)?)})),
    ).optional()?)
}

struct FrozenStudy {
    id: String,
    revision: i64,
    read: bool,
    snapshot: Value,
}

fn latest_round(
    db: &Connection,
    course: &str,
    plan: &str,
) -> Result<(bool, Option<FrozenStudy>), StorageError> {
    let mut query = db.prepare("SELECT id,revision,reading_completed,abandoned_at,snapshot_json FROM course_study_sessions WHERE course_id=? ORDER BY revision DESC")?;
    let mut rows = query.query([course])?;
    let mut any = false;
    while let Some(row) = rows.next()? {
        any = true;
        if row.get::<_, Option<String>>(3)?.is_some() {
            continue;
        }
        let text: String = row.get(4)?;
        let snapshot: Value = serde_json::from_str(&text)
            .map_err(|error| StorageError::caused_by("DATABASE_ERROR", error))?;
        if snapshot["course"]["plan_line_id"] == plan {
            return Ok((
                true,
                Some(FrozenStudy {
                    id: row.get(0)?,
                    revision: row.get(1)?,
                    read: row.get(2)?,
                    snapshot,
                }),
            ));
        }
    }
    Ok((any, None))
}

fn exercise_groups(
    db: &Connection,
    course: &str,
) -> Result<HashMap<String, Vec<String>>, StorageError> {
    let mut query = db.prepare(
        "SELECT l.id,e.id FROM lessons l LEFT JOIN exercises e ON e.lesson_id=l.id AND e.included=1 WHERE l.course_id=? AND l.included=1",
    )?;
    let mut rows = query.query([course])?;
    let mut groups = HashMap::<String, Vec<String>>::new();
    while let Some(row) = rows.next()? {
        let group = groups.entry(row.get(0)?).or_default();
        if let Some(exercise) = row.get::<_, Option<String>>(1)? {
            group.push(exercise);
        }
    }
    Ok(groups)
}

fn course_summary(
    db: &Connection,
    member: &Member,
    schedule: Option<Value>,
    total: usize,
) -> Result<Value, StorageError> {
    let mut course = crate::courses::catalog::course(db, &member.course)?;
    let groups = exercise_groups(db, &member.course)?;
    let live_ids: Vec<_> = groups.values().flatten().cloned().collect();
    let (any_history, round) = latest_round(db, &member.course, &member.plan)?;
    let (exercise_total, knowledge, state) = match round {
        Some(round) => {
            let ids = frozen_exercise_ids(&round.snapshot);
            let active = latest_statuses(db, &ids, Some((&round.id, round.revision)))?;
            let frozen_groups: HashMap<_, _> = round.snapshot["lessons"]
                .as_array()
                .into_iter()
                .flatten()
                .enumerate()
                .map(|(index, lesson)| {
                    let ids = lesson["exercises"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(|exercise| exercise["id"].as_str().map(str::to_owned))
                        .collect();
                    (index.to_string(), ids)
                })
                .collect();
            let (knowledge, mut state) = outcome(&active, &frozen_groups, ids.len(), Some(&round));
            if course["learning_mode"] == "english" {
                if let Some(completed) = db
                    .query_row(
                        "SELECT completed FROM english_study_states WHERE study_session_id=?",
                        [&round.id],
                        |row| row.get::<_, bool>(0),
                    )
                    .optional()?
                {
                    state.submitted = completed;
                }
            }
            (ids.len(), knowledge, state)
        }
        None if !any_history && course["plan_line_id"] == member.plan => {
            let active = latest_statuses(db, &live_ids, None)?;
            let (knowledge, state) = outcome(&active, &groups, live_ids.len(), None);
            (live_ids.len(), knowledge, state)
        }
        None => (live_ids.len(), 0, Outcome::default()),
    };
    let learning_group = if member.management == "OTHER" {
        "OTHER"
    } else if state.submitted {
        "COMPLETED"
    } else {
        "PENDING"
    };
    let progress = if exercise_total == 0 && state.submitted {
        100
    } else {
        percent(state.passed, exercise_total)
    };
    let summary = json!({"id":member.course,"plan_course_item_id":member.id,"management_position":member.management,
        "management_reason":member.reason,"learning_group":learning_group,"track":member.track,"sequence":member.position,"total":total,
        "knowledge_total":groups.len(),"knowledge_completed":knowledge,"exercise_total":exercise_total,
        "exercise_completed":state.passed,"progress_percent":progress,"planned_start":member.planned_start,"planned_end":member.planned_end,
        "study_status":state.status,"study_session_id":state.session,"learning_submitted":state.submitted,
        "waiting_count":state.waiting,"feedback_count":state.feedback,"schedule":schedule});
    course
        .as_object_mut()
        .unwrap()
        .extend(summary.as_object().unwrap().clone());
    Ok(course)
}

struct Outcome {
    status: &'static str,
    submitted: bool,
    passed: usize,
    waiting: usize,
    feedback: usize,
    session: Option<String>,
}
impl Default for Outcome {
    fn default() -> Self {
        Self {
            status: "NOT_STARTED",
            submitted: false,
            passed: 0,
            waiting: 0,
            feedback: 0,
            session: None,
        }
    }
}

fn outcome(
    attempts: &HashMap<String, String>,
    groups: &HashMap<String, Vec<String>>,
    total: usize,
    round: Option<&FrozenStudy>,
) -> (usize, Outcome) {
    let states: HashSet<_> = attempts.values().map(String::as_str).collect();
    let is_passed = |id: &String| attempts.get(id).is_some_and(|status| passed(status));
    let knowledge = groups
        .values()
        .filter(|ids| !ids.is_empty() && ids.iter().all(is_passed))
        .count();
    let passed = attempts.values().filter(|status| passed(status)).count();
    let waiting = attempts
        .values()
        .filter(|status| *status == "WAITING_REVIEW")
        .count();
    let all_attempted = total > 0 && total == attempts.len();
    let submitted = all_attempted || total == 0 && round.is_some_and(|r| r.read);
    let status = match round {
        Some(r) if total == 0 => {
            if r.read {
                "READ_COMPLETED"
            } else {
                "IN_PROGRESS"
            }
        }
        Some(_) | None if states.contains("NEEDS_REVISION") => "NEEDS_REVISION",
        Some(_) | None if states.contains("RETEST_REQUIRED") => "RETEST_REQUIRED",
        Some(_) | None if total > 0 && passed == total => "PASSED",
        Some(_) if !all_attempted => "IN_PROGRESS",
        Some(_) if waiting != total => "PARTIAL_FEEDBACK",
        _ if all_attempted => "WAITING_REVIEW",
        _ => "NOT_STARTED",
    };
    (
        knowledge,
        Outcome {
            status,
            submitted,
            passed,
            waiting: if round.is_some() { waiting } else { 0 },
            feedback: if round.is_some() {
                attempts.len() - waiting
            } else {
                0
            },
            session: round.map(|r| r.id.clone()),
        },
    )
}

pub fn dashboard(
    db: &Connection,
    date: Date,
    plan: Option<&str>,
    kind: Option<&str>,
) -> Result<Value, StorageError> {
    let day = date_text(date);
    let plan = plan.filter(|id| !id.is_empty());
    let tasks = super::list_tasks(db, Some(date), plan, kind, true)?;
    let memberships = members(db, plan, None)?;
    let mut counts = HashMap::new();
    let mut main = Vec::new();
    let mut by_id = HashMap::new();
    for member in &memberships {
        by_id.insert(member.id.as_str(), member);
        if member.track == "MAIN"
            && member.management == "NORMAL"
            && db.query_row(
                "SELECT status='ACTIVE' FROM courses WHERE id=?",
                [&member.course],
                |row| row.get::<_, bool>(0),
            )?
        {
            main.push(member);
            *counts.entry((&member.plan, "MAIN")).or_insert(0) += 1;
        } else if member.track == "SUPPLEMENT" {
            *counts.entry((&member.plan, "SUPPLEMENT")).or_insert(0) += 1;
        }
    }
    let mut schedules = db.prepare(
        "SELECT s.plan_course_item_id,s.status,s.start_time,s.end_time
         FROM course_schedule_items s JOIN plan_course_items p ON p.id=s.plan_course_item_id
         WHERE s.scheduled_date=?1 AND s.status<>'CANCELLED' AND p.management_position='NORMAL'
           AND (?2 IS NULL OR p.plan_line_id=?2) ORDER BY s.position,s.start_time,s.id",
    )?;
    let mut schedules = schedules.query(params![day, plan])?;
    let mut courses = Vec::new();
    let mut seen = HashSet::new();
    let total = |m: &Member| {
        counts
            .get(&(&m.plan, m.track.as_str()))
            .copied()
            .unwrap_or(0)
    };
    while let Some(row) = schedules.next()? {
        let id: String = row.get(0)?;
        let member = by_id[id.as_str()];
        if seen.insert(&member.course) {
            let schedule = json!({"date":day,"status":row.get::<_,String>(1)?,
                "start_time":exposed_time(row.get(2)?),"end_time":exposed_time(row.get(3)?)});
            courses.push(course_summary(db, member, Some(schedule), total(member))?);
        }
    }
    for member in main {
        if seen.insert(&member.course) {
            courses.push(course_summary(db, member, None, total(member))?);
        }
    }
    let plans = super::list_plans(db, false)?;
    let current = plans
        .iter()
        .find_map(|p| {
            courses
                .iter()
                .find(|c| c["track"] == "MAIN" && c["id"] == p["focus_course_id"])
        })
        .or_else(|| {
            courses
                .iter()
                .find(|c| c["track"] == "MAIN" && c["learning_submitted"] == false)
        });
    let primary = tasks.first().map(|task| &task["title"]);
    Ok(
        json!({"date":day,"primary_task":primary,"current_course":current,"courses":courses,"tasks":tasks,
        "queue_counts":crate::reviews::queue_counts(db, plan)?}),
    )
}

pub(crate) fn course_status(db: &Connection, id: &str) -> Result<Value, StorageError> {
    let member_plan: Option<String> = db.query_row("SELECT plan_line_id FROM plan_course_items WHERE course_id=? ORDER BY sequence_number,id LIMIT 1",[id],|r|r.get(0)).optional()?;
    let course = crate::courses::catalog::course(db, id)?;
    let mut summary = if let Some(plan) = member_plan {
        let items = members(db, Some(&plan), None)?;
        let member = items
            .iter()
            .find(|m| m.course == id)
            .ok_or_else(|| StorageError::new("DATABASE_ERROR"))?;
        let total = items.iter().filter(|m| m.track == member.track).count();
        course_summary(db, member, None, total)?
    } else {
        let groups = exercise_groups(db, id)?;
        let ids: Vec<_> = groups.values().flatten().cloned().collect();
        let attempts = latest_statuses(db, &ids, None)?;
        let (done, outcome) = outcome(&attempts, &groups, ids.len(), None);
        json!({"plan_course_item_id":null,"management_position":"NORMAL","management_reason":"","learning_group":"PENDING",
            "track":"MAIN","sequence":null,"total":0,"knowledge_total":groups.len(),"knowledge_completed":done,"exercise_total":ids.len(),
            "exercise_completed":outcome.passed,"progress_percent":percent(outcome.passed,ids.len()),"planned_start":null,"planned_end":null,
            "study_status":outcome.status,"study_session_id":null,"learning_submitted":outcome.submitted,"waiting_count":0,"feedback_count":0,"schedule":null})
    };
    let row = db.query_row("SELECT id,revision,reading_completed,abandoned_at,snapshot_json FROM course_study_sessions WHERE course_id=? ORDER BY revision DESC LIMIT 1",[id],|r|Ok((r.get::<_,String>(0)?,r.get::<_,i64>(1)?,r.get::<_,bool>(2)?,r.get::<_,Option<String>>(3)?,r.get::<_,String>(4)?))).optional()?;
    let mut allowed = true;
    let mut frozen_revision = Value::Null;
    let mut english = false;
    if let Some((study, revision, read, abandoned, raw)) = row {
        let content: Value =
            serde_json::from_str(&raw).map_err(|e| StorageError::caused_by("DATABASE_ERROR", e))?;
        frozen_revision = content["course"]["content_revision"].clone();
        english = content["course"]["learning_mode"] == "english";
        if abandoned.is_none() {
            let ids = frozen_exercise_ids(&content);
            let statuses = latest_statuses(db, &ids, Some((&study, revision)))?;
            allowed = if ids.is_empty() {
                read
            } else {
                ids.iter()
                    .all(|id| statuses.get(id).is_some_and(|s| passed(s)))
            };
            if !allowed && english && !ids.is_empty() {
                let completed = db
                    .query_row(
                        "SELECT completed FROM english_study_states WHERE study_session_id=?",
                        [&study],
                        |row| row.get::<_, bool>(0),
                    )
                    .optional()?
                    .unwrap_or(false);
                allowed = completed
                    && ids.iter().all(|id| {
                        statuses
                            .get(id)
                            .is_some_and(|s| passed(s) || s == "WAITING_REVIEW")
                    });
            }
        }
    }
    summary["can_start_new_round"] = json!(allowed);
    summary["source_changed"] =
        json!(!frozen_revision.is_null() && frozen_revision != course["content_revision"]);
    summary["study_content_revision"] = frozen_revision;
    summary["new_round_blocker"] = json!(if allowed {
        ""
    } else if english {
        "请先完成并提交本轮训练；需修正或复测的记录也要先处理。"
    } else {
        "完成当前作答与反馈后，再开始新版学习。"
    });
    Ok(summary)
}
