use std::{
    collections::{BTreeSet, HashMap},
    path::Path,
};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    application::write_contract::{require_version, validate_key, StoredReceipt},
    documents,
    infrastructure::{events, fingerprint::JsonFingerprint, StorageError},
    learning::material,
};

use super::{
    catalog, english, packages,
    store::{self, CourseFields},
};

const NOOP: &str = "COURSE_UPDATE_NOOP";

struct Existing {
    course: Value,
    content: Value,
    mapping: Value,
}

fn existing(db: &Connection, root: &Path, course: Value) -> Result<Existing, StorageError> {
    let id = course["id"].as_str().unwrap();
    let rows = catalog::rows(db, id)?;
    let stored: Option<String> = db.query_row("SELECT mapping_json FROM course_revisions WHERE course_id=? ORDER BY number DESC LIMIT 1",[id],|r|r.get(0)).optional()?;
    let mut mapping = stored
        .as_deref()
        .map(store::load_json)
        .transpose()?
        .unwrap_or(json!({"lessons":{},"exercises":{}}));
    let mut schema = if course["learning_mode"] == "english" {
        2
    } else {
        1
    };
    let mut lessons = Vec::new();
    for row in &rows {
        let markdown = catalog::read_markdown(root, row["markdown_path"].as_str().unwrap())?;
        let (meta, body) = documents::parse_front_matter(&markdown)?;
        schema = schema.max(packages::schema_revision(&meta["content_schema"]).unwrap_or(1));
        let db_exercises = row["exercises"].as_array().unwrap();
        let lesson = if let Some(source) = meta
            .get("structured_lesson")
            .filter(|source| source.is_object())
        {
            source.clone()
        } else {
            let exercise_list: Vec<_> = db_exercises.iter().map(|ex|json!({"id":semantic(ex),"title":ex["title"],"prompt":ex["prompt"],"requirements":ex["requirements"]})).collect();
            json!({"id":semantic(row),"title":row["title"],"blocks":[{"id":"legacy","type":"concept","title":row["title"],"body":body}],"exercises":exercise_list})
        };
        if lesson["blocks"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|b| b["type"] == "details")
        {
            schema = schema.max(3);
        }
        let lesson_id = lesson["id"]
            .as_str()
            .ok_or_else(|| StorageError::new("COURSE_SOURCE_CONFLICT"))?;
        mapping["lessons"][lesson_id] = row["id"].clone();
        let specifications = lesson["exercises"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or(&[]);
        if specifications.len() != db_exercises.len() {
            return Err(StorageError::new("COURSE_SOURCE_CONFLICT"));
        }
        for (spec, registered) in specifications.iter().zip(db_exercises) {
            let spec_id = spec["id"]
                .as_str()
                .ok_or_else(|| StorageError::new("COURSE_SOURCE_CONFLICT"))?;
            let semantic = registered["semantic_id"].as_str().unwrap_or_default();
            if !semantic.is_empty() && semantic != spec_id {
                return Err(StorageError::new("COURSE_SOURCE_CONFLICT"));
            }
            mapping["exercises"][format!("{lesson_id}:{spec_id}")] = registered["id"].clone();
        }
        lessons.push(lesson);
    }
    let mut metadata = json!({"title":course["title"],"summary":course["summary"],"subject":course["subject"],"difficulty":course["difficulty"]});
    if course["learning_mode"] == "english" {
        metadata["learning_mode"] = json!("english");
    }
    let content = json!({"schema":format!("studyflow.course-package/{schema}"),"package_id":format!("existing-{id}"),
        "plan_line":course["plan_line"].as_str().unwrap_or_default(),"course":metadata,"lessons":lessons});
    Ok(Existing {
        course,
        content,
        mapping,
    })
}

fn semantic(value: &Value) -> String {
    value["semantic_id"]
        .as_str()
        .filter(|id| !id.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| format!("legacy-{}", value["id"].as_str().unwrap()))
}

fn keys(content: &Value) -> (Vec<&str>, BTreeSet<String>) {
    let mut lessons = Vec::new();
    let mut exercises = BTreeSet::new();
    for lesson in content["lessons"].as_array().into_iter().flatten() {
        let lid = lesson["id"].as_str().expect("validated lesson id");
        lessons.push(lid);
        for item in lesson["exercises"].as_array().into_iter().flatten() {
            exercises.insert(format!(
                "{lid}:{}",
                item["id"].as_str().expect("validated exercise id")
            ));
        }
    }
    (lessons, exercises)
}

fn objectives(content: &Value) -> BTreeSet<String> {
    content["lessons"]
        .as_array()
        .into_iter()
        .flatten()
        .flat_map(|l| l["exercises"].as_array().into_iter().flatten())
        .flat_map(|e| {
            e["english"]["objective_ids"]
                .as_array()
                .into_iter()
                .flatten()
        })
        .filter_map(|o| o.as_str().map(str::to_owned))
        .collect()
}

fn check(
    db: &Connection,
    state: &Existing,
    next: &Value,
    content_hash: &str,
    expected: i64,
) -> Result<Value, StorageError> {
    let old = &state.content;
    let id = state.course["id"].as_str().unwrap();
    if state.course["plan_line"].is_null() || next["plan_line"] != state.course["plan_line"] {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    if old["schema"] == "studyflow.course-package/4" && state.course["learning_mode"] == "english" {
        if next["schema"] != old["schema"] {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        let remediation = db
            .query_row(
                "SELECT 1 FROM english_remediation_courses WHERE course_id=?",
                [id],
                |_| Ok(()),
            )
            .optional()?
            .is_some();
        english::validate_chains(next, remediation)
            .map_err(|e| StorageError::caused_by("INVALID_COURSE_PACKAGE", e))?;
        if remediation && !objectives(old).is_subset(&objectives(next)) {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
    }
    if CourseFields::from_package(next).mode != state.course["learning_mode"] {
        return Err(StorageError::new("COURSE_MODE_CHANGE_UNSUPPORTED"));
    }
    let (old_order, old_ex) = keys(old);
    let (new_order, new_ex) = keys(next);
    let old_lessons: BTreeSet<_> = old_order.iter().copied().collect();
    let new_lessons: BTreeSet<_> = new_order.iter().copied().collect();
    let by_id: HashMap<_, _> = old["lessons"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|l| Some((l["id"].as_str()?, l)))
        .collect();
    let changed: Vec<_> = next["lessons"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|l| {
            let id = l["id"].as_str()?;
            by_id.get(id).is_some_and(|old| *old != l).then_some(id)
        })
        .collect();
    let rounds: i64 = db.query_row(
        "SELECT COUNT(*) FROM course_study_sessions WHERE course_id=?",
        [id],
        |r| r.get(0),
    )?;
    let materially_changed = ["title", "summary", "subject", "difficulty"]
        .iter()
        .any(|key| {
            old["course"][key].as_str().unwrap_or_default()
                != next["course"][key].as_str().unwrap_or_default()
        })
        || old["lessons"] != next["lessons"];
    let new_revision = expected
        .checked_add(i64::from(materially_changed))
        .ok_or_else(|| StorageError::new("VERSION_CONFLICT"))?;
    let preview = JsonFingerprint::Ascii.hash(&json!({"old":old,"new":next,"mapping":state.mapping,"course_id":id,"expected_revision":expected}));
    Ok(
        json!({"course_id":id,"expected_revision":expected,"new_revision":new_revision,"content_hash":content_hash,
        "added_lessons":new_lessons.difference(&old_lessons).collect::<Vec<_>>(),"removed_lessons":old_lessons.difference(&new_lessons).collect::<Vec<_>>(),
        "added_exercises":new_ex.difference(&old_ex).collect::<Vec<_>>(),"removed_exercises":old_ex.difference(&new_ex).collect::<Vec<_>>(),
        "changed_lessons":changed,"order_changed":old_order!=new_order,"affected_study_rounds":rounds,"historical_entities_retained":true,
        "material_changed":materially_changed,"reset_current_learning":materially_changed,"preview_hash":preview}),
    )
}

pub(crate) struct Change<'a> {
    pub id: &'a str,
    pub package: &'a Value,
    pub content_hash: &'a str,
    pub expected: i64,
}

impl Change<'_> {
    fn read(&self, db: &Connection, root: &Path) -> Result<Existing, StorageError> {
        let course = catalog::course(db, self.id)?;
        require_version(course["content_revision"].as_i64().unwrap(), self.expected)?;
        existing(db, root, course)
    }

    pub(crate) fn preview(&self, db: &Connection, root: &Path) -> Result<Value, StorageError> {
        check(
            db,
            &self.read(db, root)?,
            self.package,
            self.content_hash,
            self.expected,
        )
    }

    pub(crate) fn apply(
        &self,
        db: &Connection,
        root: &Path,
        token: &str,
        key: &str,
    ) -> Result<Value, StorageError> {
        validate_key(key)?;
        let id = self.id;
        let request_hash = JsonFingerprint::Ascii.hash(&json!({"course_id":id,"data":self.package,"expected_revision":self.expected,"preview_hash":token}));
        if let Some(receipt) = db.query_row("SELECT operation,payload_hash,result_json FROM course_write_receipts WHERE idempotency_key=?",
            [key], |r|Ok(StoredReceipt {operation:r.get(0)?,payload_hash:r.get(1)?,result_json:r.get(2)?})).optional()? {
            return receipt.replay(Some(NOOP),&request_hash);
        }
        if let Some(receipt) = db
            .query_row(
                "SELECT request_hash,result_json FROM course_revisions WHERE idempotency_key=?",
                [key],
                |r| {
                    Ok(StoredReceipt {
                        operation: None,
                        payload_hash: r.get(0)?,
                        result_json: r.get(1)?,
                    })
                },
            )
            .optional()?
        {
            return receipt.replay(None, &request_hash);
        }
        let mut current = self.read(db, root)?;
        let checked = check(db, &current, self.package, self.content_hash, self.expected)?;
        if checked["preview_hash"] != token {
            return Err(StorageError::new("PREVIEW_CHANGED"));
        }
        if checked["material_changed"] == false {
            let receipt = json!({"ok":true,"course_id":id,"revision":self.expected,"content_hash":self.content_hash,
                "unchanged":true,"historical_rounds_unchanged":true,"learning_state_reset":false,"reset_study_sessions":[]});
            db.execute("INSERT INTO course_write_receipts(id,course_id,idempotency_key,operation,payload_hash,result_json) VALUES(?,?,?,?,?,?)",
                params![Uuid::new_v4().to_string(),id,key,NOOP,request_hash,receipt.to_string()])?;
            return Ok(receipt);
        }
        material::preserve_legacy_round(db, root, id, key)?;
        let next = checked["new_revision"].as_i64().unwrap();
        let fields = CourseFields::from_package(self.package);
        let changed = db.execute("UPDATE courses SET version=?,title=?,summary=?,subject=?,difficulty=?,learning_mode=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=?",
            params![next,fields.title,fields.summary,fields.subject,fields.difficulty,fields.mode,id,self.expected])?;
        if changed != 1 {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        db.execute("INSERT INTO course_revisions(id,course_id,number,package_json,mapping_json,content_hash,result_json)
            VALUES(?,?,?,?,?,?,'{}') ON CONFLICT(course_id,number) DO NOTHING",params![Uuid::new_v4().to_string(),id,self.expected,
            current.content.to_string(),current.mapping.to_string(),JsonFingerprint::Ascii.hash(&current.content)])?;
        db.execute("UPDATE lessons SET included=0 WHERE course_id=?", [id])?;
        db.execute("UPDATE exercises SET included=0 WHERE lesson_id IN (SELECT id FROM lessons WHERE course_id=?)",[id])?;
        store::write_package_lessons(
            db,
            root,
            id,
            self.package,
            self.content_hash,
            next,
            &mut current.mapping,
        )?;
        let sealed = material::seal_current(
            db,
            id,
            &format!("课程修订{next}发布，按用户决定重置学习状态"),
        )?;
        let reset = !sealed.is_empty();
        let receipt = json!({"ok":true,"course_id":id,"revision":next,"content_hash":self.content_hash,"historical_rounds_unchanged":!reset,"learning_state_reset":reset,"reset_study_sessions":sealed});
        db.execute("INSERT INTO course_revisions(id,course_id,number,package_json,mapping_json,content_hash,idempotency_key,request_hash,result_json) VALUES(?,?,?,?,?,?,?,?,?)",
            params![Uuid::new_v4().to_string(),id,next,self.package.to_string(),current.mapping.to_string(),self.content_hash,key,request_hash,receipt.to_string()])?;
        let state = if reset { "已重置" } else { "不变" };
        events::record(
            db,
            "AGENT_CLI",
            "course",
            id,
            "PUBLISH_REVISION",
            &format!("发布课程修订{next}，学习状态{state}"),
        )?;
        Ok(receipt)
    }
}
