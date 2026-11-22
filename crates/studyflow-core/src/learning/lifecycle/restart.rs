use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use super::{
    atomic_write, events, exists, insert_round, latest, record_receipt, replay_course,
    require_unused_round_key, require_version, reset, validate_key, Ascii, Round, StorageError,
    Workspace,
};
use crate::learning::study_sessions;

fn training_version(db: &Connection, id: &str) -> Result<(i64, bool), StorageError> {
    Ok(db
        .query_row(
            "SELECT version,completed FROM english_study_states WHERE study_session_id=?",
            [id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?
        .unwrap_or_default())
}

fn blockers(db: &Connection, round: &Round) -> Result<Vec<Value>, StorageError> {
    let mode = round.snapshot["course"]["learning_mode"]
        .as_str()
        .unwrap_or("general");
    let english = mode == "english";
    let tracked = db.query_row(
        "SELECT hint_tracking_enabled FROM course_study_sessions WHERE id=?",
        [&round.id],
        |r| r.get::<_, bool>(0),
    )?;
    let ids = json!(round.ids()).to_string();
    let (version, complete) = training_version(db, &round.id)?;
    let checks = [
        (!matches!(mode,"general"|"english"), "LEARNING_MODE_UNSUPPORTED", "未知学习模式不能安全放弃。"),
        (round.reading_completed, "READING_COMPLETED", "本轮已完成阅读，请使用完成后的新轮次入口。"),
        (english && !tracked, "HINT_HISTORY_UNKNOWN", "旧轮次的提示记录不完整，不能确认是空轮次。"),
        (exists(db, "SELECT EXISTS(SELECT 1 FROM course_reference_views WHERE study_session_id=?)", [&round.id])?, "REFERENCE_VIEW_PRESENT", "本轮已查看过答案解析，不能按空轮次放弃。"),
        (exists(db, "SELECT EXISTS(SELECT 1 FROM submissions WHERE study_session_id=? OR (study_session_id IS NULL AND exercise_id IN (SELECT value FROM json_each(?))))", params![round.id,ids])?, "ANSWER_HISTORY_PRESENT", "已有题目草稿或作答记录，不能放弃本轮。"),
        (exists(db, "SELECT EXISTS(SELECT 1 FROM course_write_receipts WHERE study_session_id=? AND operation NOT IN ('STUDY_OPEN','STUDY_RESTART') AND (NOT ? OR operation<>'EN_MOVE'))", params![round.id,english])?, "ANSWER_WRITE_PRESENT", "已有作答写入回执，请继续本轮并确认写入结果。"),
        ((version > 0 && (!english || complete)) || exists(db, "SELECT EXISTS(SELECT 1 FROM english_check_attempts WHERE study_session_id=?)", [&round.id])?, "TRAINING_HISTORY_PRESENT", "本轮已有检查或完成证据，不能放弃。"),
    ];
    Ok(checks
        .into_iter()
        .filter(|(present, _, _)| *present)
        .map(|(_, code, message)| json!({"code":code,"message":message}))
        .collect())
}

pub fn restart_preview(
    workspace: &Workspace,
    id: &str,
    reset_current: bool,
) -> Result<Value, StorageError> {
    let root = &workspace.settings().workspace;
    workspace.read_consistent(|db| {
        let round = study_sessions::require(db,id,None,true)?;
        let mut data = json!({"study_session_id":id,"course_id":round.course,"revision":round.revision,
            "expected_version":round.version,"frozen_content_hash":round.hash,"history_retained":true,"notes_retained":true,"reading_position_transferred":false});
        if reset_current {
            let info = super::inventory(db,root,&round.course)?.preview;
            data["expected_content_hash"] = info["content_hash"].clone();
            data["expected_state_hash"] = info["state_hash"].clone();
            data["reset_current_state"] = json!(true);
            data["can_restart"] = json!(true);
            data["blocked_reasons"] = json!([]);
        } else {
            let mut reasons = blockers(db,&round)?;
            match latest(db,root,&round) {
                Ok((_,hash)) => data["expected_content_hash"] = json!(hash),
                Err(error) if error.code != "DATABASE_ERROR" => {
                    data["expected_content_hash"] = Value::Null;
                    reasons.push(json!({"code":"SOURCE_UNAVAILABLE","message":"最新版材料暂不可读；原轮次仍保留。"}));
                }
                Err(error) => return Err(error),
            }
            data["expected_training_version"] = json!(training_version(db,id)?.0);
            data["can_restart"] = json!(reasons.is_empty());
            data["blocked_reasons"] = json!(reasons);
        }
        Ok(data)
    })
}

pub fn restart(workspace: &Workspace, id: &str, input: &Value) -> Result<Value, StorageError> {
    let invalid = || StorageError::new("INVALID_ARGUMENT");
    let root = &workspace.settings().workspace;
    if input["reset_current_state"] == true {
        let course = workspace
            .read_consistent(|db| Ok(study_sessions::require(db, id, None, false)?.course))?;
        let mut command = input.clone();
        command["confirm"] = json!(true);
        let result = reset(workspace, &course, &command)?;
        let id = result["study_session_id"].as_str().ok_or_else(invalid)?;
        return workspace.read_consistent(|db| study_sessions::detail(db, root, id));
    }
    let version = input["expected_version"]
        .as_i64()
        .filter(|num| *num >= 1)
        .ok_or_else(invalid)?;
    let content_hash = input["expected_content_hash"]
        .as_str()
        .filter(|hash| hash.chars().count() == 64)
        .ok_or_else(invalid)?;
    let key = input["idempotency_key"].as_str().ok_or_else(invalid)?;
    validate_key(key)?;
    let training = &input["expected_training_version"];
    let mut payload = json!({"study_session_id":id,"expected_version":version,"expected_content_hash":content_hash});
    if !training.is_null() {
        payload["expected_training_version"] = training.clone();
    }
    let request_hash = Ascii.hash(&payload);
    let mut active = workspace.open()?;
    let next = atomic_write(&mut active.connection, |db| {
        if let Some(receipt) = replay_course(db, key, "STUDY_RESTART", &request_hash)? {
            return receipt["study_session_id"]
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| StorageError::new("IDEMPOTENCY_UNVERIFIABLE"));
        }
        require_unused_round_key(db, key)?;
        let old = study_sessions::require(db, id, None, true)?;
        if !blockers(db, &old)?.is_empty() {
            return Err(StorageError::new("STUDY_RESTART_BLOCKED"));
        }
        if old.snapshot["course"]["learning_mode"] == "english"
            && training.as_i64() != Some(training_version(db, id)?.0)
        {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        require_version(old.version, version)?;
        let (snapshot, hash) = latest(db, root, &old)?;
        if hash != content_hash {
            return Err(StorageError::new("COURSE_CONTENT_CONFLICT"));
        }
        let changed = db.execute("UPDATE course_study_sessions SET abandoned_at=CURRENT_TIMESTAMP,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND version=? AND abandoned_at IS NULL", params![id, version])?;
        if changed != 1 {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
        let next = insert_round(db, &old.course, old.revision + 1, key, snapshot, &hash)?;
        record_receipt(
            db,
            &old.course,
            &next,
            key,
            "STUDY_RESTART",
            &request_hash,
            &json!({"study_session_id":next,"previous_study_session_id":id}),
        )?;
        events::record(
            db,
            "USER_ENGINE",
            "course_study",
            id,
            "ABANDON",
            "明确保留历史并重新开始",
        )?;
        events::record(
            db,
            "USER_ENGINE",
            "course_study",
            &next,
            "OPEN",
            "用最新材料创建固定学习轮次",
        )?;
        Ok(next)
    })?;
    let db = active.connection.unchecked_transaction()?;
    study_sessions::detail(&db, root, &next)
}
