use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    application::write_contract::{atomic_write, validate_key},
    courses::references::{self, ReferenceRequest},
    infrastructure::{events, fingerprint::JsonFingerprint::Utf8, StorageError},
    mistakes,
    workspace::Workspace,
};

const ISSUE_FIELDS: [&str; 5] = ["quote", "location", "reason", "guidance", "next_action"];

fn invalid() -> StorageError {
    StorageError::new("INVALID_ARGUMENT")
}

fn field<'a>(input: &'a Value, key: &str) -> Result<&'a str, StorageError> {
    input
        .get(key)
        .map_or(Some(""), Value::as_str)
        .ok_or_else(invalid)
}

fn decision(input: &Value) -> Result<(&'static str, &'static str, &'static str), StorageError> {
    let explicit = input["decision"].as_str().unwrap_or_default().trim();
    let revise = input["needs_revision"].as_bool().unwrap_or(false);
    let value = match explicit.to_uppercase().as_str() {
        "" if revise => (
            "REVISION_REQUIRED",
            "NEEDS_REVISION",
            "按批改反馈提交修正版。",
        ),
        "" => ("PASSED", "REVIEWED", "保留通过证据，进入下一个知识点。"),
        "PASSED" | "REVIEWED" => ("PASSED", "PASSED", "保留通过证据，进入下一个知识点。"),
        "REVISION_REQUIRED" | "NEEDS_REVISION" => (
            "REVISION_REQUIRED",
            "NEEDS_REVISION",
            "按批改反馈提交修正版。",
        ),
        "RETEST_REQUIRED" | "RETEST" => (
            "RETEST_REQUIRED",
            "RETEST_REQUIRED",
            "复习错误点后提交复测版。",
        ),
        _ => return Err(StorageError::new("INVALID_REVIEW_DECISION")),
    };
    Ok(value)
}

fn issues_json(issues: &[Value]) -> Result<String, StorageError> {
    let mut encoded = Vec::with_capacity(issues.len());
    for issue in issues {
        let fields = issue
            .as_object()
            .filter(|fields| fields.len() == ISSUE_FIELDS.len())
            .ok_or_else(invalid)?;
        let mut properties = Vec::with_capacity(ISSUE_FIELDS.len());
        for field in ISSUE_FIELDS {
            let item = fields
                .get(field)
                .filter(|item| {
                    item.as_str().is_some_and(|text| {
                        !text.trim().is_empty() && text.chars().count() <= 10_000
                    })
                })
                .ok_or_else(invalid)?;
            properties.push(format!("\"{field}\": {}", Utf8.serialize(item)));
        }
        encoded.push(format!("{{{}}}", properties.join(", ")));
    }
    Ok(format!("[{}]", encoded.join(", ")))
}

struct Feedback<'a> {
    submission: &'a str,
    summary: &'a str,
    detail: &'a str,
    key: Option<&'a str>,
    actor: &'a str,
    decision: &'static str,
    status: &'static str,
    next: &'a str,
    issues: Option<&'a [Value]>,
    issues_json: String,
    issue_count: i64,
    reference: Option<&'a str>,
    revision: Option<i64>,
    reason: &'a str,
}

impl<'a> Feedback<'a> {
    fn new(input: &'a Value) -> Result<Self, StorageError> {
        let submission = field(input, "submission_id")?.trim();
        let summary = field(input, "summary")?.trim();
        if submission.is_empty() || summary.is_empty() {
            return Err(invalid());
        }
        let detail = field(input, "detail_markdown")?.trim();
        let key = input["idempotency_key"].as_str();
        if let Some(key) = key.filter(|key| !key.is_empty()) {
            validate_key(key)?;
        }
        let actor = input
            .get("source")
            .map_or(Some("AGENT_CLI"), Value::as_str)
            .ok_or_else(invalid)?;
        let (decision, status, default_next) = decision(input)?;
        let next = field(input, "next_action")?.trim();
        let next = if next.is_empty() { default_next } else { next };
        let issues = match &input["issues"] {
            Value::Null => None,
            Value::Array(items) if items.len() <= 50 => Some(items.as_slice()),
            _ => return Err(invalid()),
        };
        let issue_count = match issues {
            Some(items) => items.len() as i64,
            None => input
                .get("issue_count")
                .map_or(Some(0), Value::as_i64)
                .filter(|count| *count >= 0)
                .ok_or_else(invalid)?,
        };
        let issues_json = issues_json(issues.unwrap_or_default())?;
        let reference = input["reference_hash"].as_str();
        let revision = input["reference_revision"].as_i64();
        let reason = field(input, "reference_reason")?;
        if reason.chars().count() > 3_000 || (revision.is_some() && reference.is_none()) {
            return Err(invalid());
        }
        Ok(Self {
            submission,
            summary,
            detail,
            key,
            actor,
            decision,
            status,
            next,
            issues,
            issues_json,
            issue_count,
            reference,
            revision,
            reason,
        })
    }

    fn receipt(&self, id: &str) -> Value {
        json!({"review_id":id,"submission_id":self.submission,"decision":self.decision,"next_action":self.next,"needs_revision":self.decision!="PASSED"})
    }

    fn replay(&self, db: &Connection) -> Result<Option<Value>, StorageError> {
        let Some(key) = self.key.filter(|key| !key.is_empty()) else {
            return Ok(None);
        };
        let saved=db.query_row("SELECT id,submission_id,summary,detail_markdown,issue_count,decision,next_action,issues_json,reference_hash,reference_revision,reference_reason FROM review_feedback WHERE idempotency_key=?",[key],|row|Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?,row.get::<_,String>(3)?,row.get::<_,i64>(4)?,row.get::<_,String>(5)?,row.get::<_,String>(6)?,row.get::<_,String>(7)?,row.get::<_,Option<String>>(8)?,row.get::<_,Option<i64>>(9)?,row.get::<_,String>(10)?))).optional()?;
        let Some((
            id,
            submission,
            summary,
            detail,
            count,
            decision,
            next,
            issues,
            hash,
            revision,
            reason,
        )) = saved
        else {
            return Ok(None);
        };
        let issues_match = self.issues.is_none_or(|expected| {
            serde_json::from_str::<Value>(&issues)
                .ok()
                .is_some_and(|stored| stored.as_array().is_some_and(|stored| stored == expected))
        });
        if submission != self.submission
            || summary != self.summary
            || detail != self.detail
            || count != self.issue_count
            || decision != self.decision
            || next != self.next
            || !issues_match
            || hash.as_deref() != self.reference
            || self
                .revision
                .is_some_and(|expected| Some(expected) != revision)
            || reason != self.reason
        {
            return Err(StorageError::new("IDEMPOTENCY_KEY_CONFLICT"));
        }
        Ok(Some(self.receipt(&id)))
    }

    fn reference_revision(&self, db: &Connection) -> Result<Option<i64>, StorageError> {
        let Some(hash) = self.reference else {
            return Ok(None);
        };
        let basis = references::resolve(
            db,
            ReferenceRequest {
                submission_id: Some(self.submission),
                reference_revision: self.revision,
                ..Default::default()
            },
        )?;
        if basis["available"] != true || basis["reference_hash"] != hash {
            return Err(StorageError::new("REFERENCE_MISMATCH"));
        }
        if basis["is_correction"] == true && self.reason.trim().is_empty() {
            return Err(invalid());
        }
        Ok(basis["content_revision"].as_i64())
    }
}

pub fn write(workspace: &Workspace, input: &Value) -> Result<Value, StorageError> {
    let feedback = Feedback::new(input)?;
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        if let Some(saved) = feedback.replay(db)? {
            return Ok(saved);
        }
        let (status,version,answer,study,exercise,task) = db.query_row("SELECT status,version,answer_text,study_session_id,exercise_id,retest_task_id FROM submissions WHERE id=?",[feedback.submission],|row|Ok((row.get::<_,String>(0)?,row.get::<_,i64>(1)?,row.get::<_,String>(2)?,row.get::<_,Option<String>>(3)?,row.get::<_,String>(4)?,row.get::<_,Option<String>>(5)?))).optional()?.ok_or_else(||StorageError::new("OBJECT_NOT_FOUND"))?;
        if status != "WAITING_REVIEW" {
            return Err(StorageError::new("INVALID_REVIEW_SOURCE"));
        }
        let revision = feedback.reference_revision(db)?;
        if let Some(issues) = feedback.issues {
            if issues
                .iter()
                .any(|item| !answer.contains(item["quote"].as_str().unwrap_or_default()))
            {
                return Err(StorageError::new("REVIEW_QUOTE_MISMATCH"));
            }
            if feedback.decision == "PASSED" && !issues.is_empty() {
                return Err(invalid());
            }
        }
        let changed=db.execute("UPDATE submissions SET status=?,next_action=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=? AND status='WAITING_REVIEW'",params![feedback.status,feedback.next,feedback.submission,version])?;
        if changed != 1 {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        let id = Uuid::new_v4().to_string();
        db.execute("INSERT INTO review_feedback(id,submission_id,summary,detail_markdown,issue_count,needs_revision,source,idempotency_key,decision,next_action,issues_json,reference_hash,reference_revision,reference_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",params![id,feedback.submission,feedback.summary,feedback.detail,feedback.issue_count,feedback.decision!="PASSED",feedback.actor,feedback.key,feedback.decision,feedback.next,feedback.issues_json,feedback.reference,revision,feedback.reason])?;
        if let Some(task) = task {
            db.execute(
                "UPDATE retest_tasks SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                params![feedback.status, task],
            )?;
        }
        mistakes::record_review(
            db,
            study.as_deref(),
            &exercise,
            feedback.submission,
            &answer,
            &id,
            feedback.decision,
        )?;
        events::record(
            db,
            feedback.actor,
            "submission",
            feedback.submission,
            "REVIEW",
            &format!("{}: {}", feedback.decision, feedback.summary),
        )?;
        Ok(feedback.receipt(&id))
    })
}
