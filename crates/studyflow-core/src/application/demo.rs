use std::fs;

use rusqlite::{params, OptionalExtension};
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    application::write_contract::atomic_write,
    infrastructure::{events, file_paths, StorageError},
    planning::{date_text, ensure_membership, today, Track},
    workspace::Workspace,
};

const PLAN: &str = "Java就业";
const COURSE: &str = "Java对象模型：从引用到运行过程";
const STAGE: &str = "StudyFlow产品第一条闭环";
const PATH: &str = "content/lessons/java-reference.md";

#[derive(Deserialize)]
struct Lesson {
    title: String,
    summary: String,
    exercise_title: String,
    prompt: String,
    requirements: String,
}

pub fn initialize(workspace: &Workspace) -> Result<Value, StorageError> {
    workspace.upgrade()?;
    let mut active = workspace.open()?;
    let lessons: Vec<Lesson> = serde_json::from_str(include_str!("demo/lessons.json"))
        .map_err(|error| StorageError::caused_by("INVALID_DEMO_CONTENT", error))?;
    let date = date_text(today());
    let id = || Uuid::new_v4().to_string();
    atomic_write(&mut active.connection, |db| {
        let existing = db.query_row(
            "SELECT p.id,c.id FROM plan_lines p JOIN courses c ON c.plan_line_id=p.id
             WHERE p.name=? AND c.title=? AND EXISTS(SELECT 1 FROM lessons WHERE course_id=c.id AND markdown_path=?)
             ORDER BY c.created_at,c.id LIMIT 1",
            params![PLAN, COURSE, PATH],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        ).optional()?;
        let created = existing.is_none();
        let (plan, course) = if let Some(existing) = existing {
            existing
        } else {
            let plan = db
                .query_row("SELECT id FROM plan_lines WHERE name=?", [PLAN], |row| {
                    row.get::<_, String>(0)
                })
                .optional()?;
            if plan.is_some() {
                return Err(StorageError::new("DEMO_PLAN_CONFLICT"));
            }
            (id(), id())
        };
        let root = &workspace.settings().workspace;
        let document = file_paths::workspace_path(root, PATH.as_ref())?;
        if file_paths::relative_in_workspace(&document, root)? != std::path::Path::new(PATH) {
            return Err(StorageError::new("INVALID_WORKSPACE_PATH"));
        }
        fs::create_dir_all(document.parent().expect("embedded demo path"))?;
        file_paths::write_if_absent(&document, include_bytes!("demo/java-reference.md"))?;
        let mut exercise_id = None;
        let mut task_id = None;
        if created {
            db.execute(
                "INSERT INTO plan_lines(id,name,priority,status,version,created_at,updated_at) VALUES(?,?,1,'ACTIVE',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                params![plan, PLAN],
            )?;
            db.execute(
                "INSERT INTO courses(id,plan_line_id,title,summary,content_type,difficulty,source_type,version,status,learning_mode,created_at,updated_at) VALUES(?,?,?,?,'LESSON','','AGENT_CLI',1,'ACTIVE','general',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                params![
                    course,
                    plan,
                    COURSE,
                    "用多个知识点和可运行的小练习理解对象、引用和异常边界。"
                ],
            )?;
            for (index, lesson) in lessons.iter().enumerate() {
                let lesson_id = id();
                let exercise = id();
                db.execute("INSERT INTO lessons(id,course_id,title,position,markdown_path,summary,created_at,updated_at) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                    params![lesson_id, course, lesson.title, index as i64 + 1, PATH, lesson.summary])?;
                db.execute("INSERT INTO exercises(id,lesson_id,title,prompt,requirements,position,exercise_type,created_at,updated_at) VALUES(?,?,?,?,?,1,'SHORT_ANSWER',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                    params![exercise, lesson_id, lesson.exercise_title, lesson.prompt, lesson.requirements])?;
                exercise_id.get_or_insert(exercise);
            }
        }
        let item = ensure_membership(db, &plan, &course, Track::Main)?;
        db.execute("INSERT INTO course_schedule_items(id,plan_course_item_id,scheduled_date,position,start_time,end_time,status,created_at,updated_at)
                    VALUES(?,?,?,1,'09:00:00','10:30:00','PLANNED',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) ON CONFLICT(plan_course_item_id,scheduled_date) DO NOTHING", params![id(), item, date])?;
        if created {
            let stage = id();
            let task = id();
            let schedule: String = db.query_row("SELECT id FROM course_schedule_items WHERE plan_course_item_id=? AND scheduled_date=?", params![item,date], |row| row.get(0))?;
            db.execute("INSERT INTO stages(id,plan_line_id,name,window_start,window_end,status,created_at,updated_at) VALUES(?,?,?,?,?,'ACTIVE',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", params![stage,plan,STAGE,date,date])?;
            db.execute("INSERT INTO tasks(id,stage_id,title,description,scheduled_date,task_kind,course_schedule_item_id,status,reason,next_action,priority,created_at,updated_at) VALUES(?,?,?,?,?,'PRACTICE',?,'TODO','','',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                params![task,stage,"完成 StudyFlow 第一节课程与练习","阅读课程，完成练习并提交答案，随后由外部 Agent 通过 CLI 批改。",date,schedule])?;
            db.execute("INSERT INTO time_blocks(id,task_id,block_date,start_time,end_time,actual_minutes,created_at,updated_at) VALUES(?,?,?,'09:00:00','10:30:00',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", params![id(),task,date])?;
            events::record(
                db,
                "SYSTEM_JOB",
                "course",
                &course,
                "SEED_DEMO",
                "创建多知识点演示课闭环",
            )?;
            task_id = Some(task);
        }
        let mut result = json!({"created":created,"plan_line_id":plan,"course_id":course});
        if created {
            result["task_id"] = json!(task_id);
            result["exercise_id"] = json!(exercise_id);
        }
        Ok(result)
    })
}
