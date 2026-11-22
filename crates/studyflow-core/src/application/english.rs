use rusqlite::{params, OptionalExtension};
use serde_json::{json, Map, Value};
use uuid::Uuid;

use super::write_contract::{atomic_write, StoredReceipt};
use crate::{
    infrastructure::{events, fingerprint::JsonFingerprint, StorageError},
    learning::english,
    workspace::Workspace,
};

pub enum Command<'a> {
    Save {
        exercise: &'a str,
        answer: &'a str,
        expected: i64,
        skipped: bool,
    },
    Check {
        exercise: &'a str,
        expected: i64,
    },
    Reveal {
        exercise: &'a str,
    },
    Review {
        exercise: &'a str,
        expected: i64,
    },
    Move {
        position: i64,
        expected: i64,
    },
    Submit {
        versions: &'a Map<String, Value>,
    },
    RetestSave {
        task: &'a str,
        answer: &'a str,
        expected: i64,
    },
    RetestCheck {
        task: &'a str,
        answer: &'a str,
        expected: i64,
    },
}

impl Command<'_> {
    fn descriptor(&self) -> (&'static str, Value) {
        match self {
            Self::Save {
                exercise,
                answer,
                expected,
                skipped,
            } => (
                "EN_SAVE",
                json!({"exercise_id":exercise,"answer_text":answer,"expected_version":expected,"skipped":skipped}),
            ),
            Self::Check { exercise, expected } => (
                "EN_CHECK",
                json!({"exercise_id":exercise,"expected_version":expected}),
            ),
            Self::Reveal { exercise } => ("EN_REVEAL", json!({"exercise_id":exercise})),
            Self::Review { exercise, expected } => (
                "EN_REVIEW",
                json!({"exercise_id":exercise,"expected_version":expected}),
            ),
            Self::Move { position, expected } => (
                "EN_MOVE",
                json!({"position":position,"expected_version":expected}),
            ),
            Self::Submit { versions } => ("EN_SUBMIT", json!({"expected_versions":versions})),
            Self::RetestSave {
                task,
                answer,
                expected,
            } => (
                "EN_RETEST_SAVE",
                json!({"task_id":task,"answer_text":answer,"expected_version":expected}),
            ),
            Self::RetestCheck {
                task,
                answer,
                expected,
            } => (
                "EN_RETEST",
                json!({"task_id":task,"answer_text":answer,"expected_version":expected}),
            ),
        }
    }
}

pub fn write(
    workspace: &Workspace,
    study: Option<&str>,
    key: &str,
    command: Command<'_>,
) -> Result<Value, StorageError> {
    if !(1..=160).contains(&key.chars().count()) {
        return Err(StorageError::new("INVALID_ARGUMENT"));
    }
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        let task = match command {
            Command::RetestSave { task, .. } | Command::RetestCheck { task, .. } => Some(task),
            _ => None,
        };
        let retest_study = task
            .map(|task| english::retest::study(db, task))
            .transpose()?;
        let study = retest_study
            .as_deref()
            .or(study)
            .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?;
        let (operation, mut payload) = command.descriptor();
        payload["study_session_id"] = json!(study);
        let hash = JsonFingerprint::Ascii.hash(&payload);
        let receipt=db.query_row("SELECT operation,payload_hash,result_json FROM course_write_receipts WHERE idempotency_key=?",[key],
            |row|Ok(StoredReceipt{operation:row.get(0)?,payload_hash:row.get(1)?,result_json:row.get(2)?})).optional()?;
        if let Some(receipt) = receipt {
            return receipt.replay(Some(operation), &hash);
        }
        let round = english::context(db, study, task.is_none())?;
        let result = match command {
            Command::Save {
                exercise,
                answer,
                expected,
                skipped,
            } => english::save(db, &round, exercise, answer, expected, skipped),
            Command::Check { exercise, expected } => english::check(db, &round, exercise, expected),
            Command::Reveal { exercise } => english::reveal(db, &round, exercise),
            Command::Review { exercise, expected } => {
                english::request_review(db, &round, exercise, expected)
            }
            Command::Move { position, expected } => {
                english::navigate(db, &round, position, expected)
            }
            Command::Submit { versions } => english::submit(db, &round, Some(versions)),
            Command::RetestSave {
                task,
                answer,
                expected,
            } => english::retest::save(db, task, answer, expected),
            Command::RetestCheck {
                task,
                answer,
                expected,
            } => english::retest::check(db, task, answer, expected),
        }?;
        db.execute("INSERT INTO course_write_receipts(id,course_id,study_session_id,idempotency_key,operation,payload_hash,result_json) VALUES(?,?,?,?,?,?,?)",
            params![Uuid::new_v4().to_string(),round.course,study,key,operation,hash,result.to_string()])?;
        events::record(
            db,
            "USER_ENGINE",
            "english_study",
            study,
            operation,
            "英语训练状态更新；无答卷正文。",
        )?;
        Ok(result)
    })
}
