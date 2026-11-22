use std::path::Path;
use std::sync::{Arc, Barrier};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use studyflow_core::application::write_contract::{
    atomic_write, require_version, validate_key, StoredReceipt,
};
use studyflow_core::infrastructure::{fingerprint::JsonFingerprint, StorageError};

fn source() -> Connection {
    let db = Connection::open_in_memory().unwrap();
    db.execute_batch(
        "CREATE TABLE versions (id INTEGER PRIMARY KEY, version INTEGER NOT NULL, body TEXT);
         INSERT INTO versions(id,version) VALUES(1,0);
         CREATE TABLE receipts (key TEXT PRIMARY KEY, operation TEXT, payload_hash TEXT, result_json TEXT);",
    )
    .unwrap();
    db
}

fn lookup(db: &Connection, key: &str) -> Result<Option<StoredReceipt>, StorageError> {
    Ok(db
        .query_row(
            "SELECT operation,payload_hash,result_json FROM receipts WHERE key=?",
            [key],
            |row| {
                Ok(StoredReceipt {
                    operation: row.get(0)?,
                    payload_hash: row.get(1)?,
                    result_json: row.get(2)?,
                })
            },
        )
        .optional()?)
}

fn save(
    db: &mut Connection,
    key: &str,
    body: &str,
    expected: i64,
    before_commit: impl FnOnce() -> Result<(), StorageError>,
) -> Result<Value, StorageError> {
    validate_key(key)?;
    let hash = JsonFingerprint::Ascii.hash(&json!([body, expected]));
    atomic_write(db, |tx| {
        if let Some(receipt) = lookup(tx, key)? {
            return receipt.replay(Some("SAVE"), &hash);
        }
        let changed = tx.execute(
            "UPDATE versions SET body=?,version=version+1 WHERE id=1 AND version=?",
            params![body, expected],
        )?;
        require_version(changed as i64, 1)?;
        let result = json!({"version": expected + 1, "body": body});
        tx.execute(
            "INSERT INTO receipts VALUES (?,'SAVE',?,?)",
            params![key, hash, result.to_string()],
        )?;
        before_commit()?;
        Ok(result)
    })
}

fn state(conn: &Connection) -> (i64, i64) {
    conn.query_row(
        "SELECT version, (SELECT count(*) FROM receipts) FROM versions WHERE id=1",
        [],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )
    .unwrap()
}

#[test]
fn lost_response_is_replayable_only_after_a_committed_write() {
    let mut conn = source();
    let error = save(&mut conn, "one", "初稿 🔖", 0, || {
        Err(StorageError::new("INJECTED_BEFORE_COMMIT"))
    })
    .unwrap_err();
    assert_eq!(error.code, "INJECTED_BEFORE_COMMIT");
    assert_eq!(state(&conn), (0, 0));
    assert!(lookup(&conn, "one").unwrap().is_none());

    // The transport fails after the completed request and discards its result.
    let write_and_deliver = |conn: &mut Connection| {
        save(conn, "one", "初稿 🔖", 0, || Ok(()))?;
        Err::<(), _>(StorageError::new("INJECTED_TRANSPORT_CLOSED"))
    };
    assert_eq!(
        write_and_deliver(&mut conn).unwrap_err().code,
        "INJECTED_TRANSPORT_CLOSED"
    );
    assert_eq!(state(&conn), (1, 1));
    let original = save(&mut conn, "one", "初稿 🔖", 0, || {
        panic!("replay wrote again")
    })
    .unwrap();
    assert_eq!(original, json!({"version":1,"body":"初稿 🔖"}));
    assert_eq!(
        save(&mut conn, "one", "更改", 0, || Ok(()))
            .unwrap_err()
            .code,
        "IDEMPOTENCY_KEY_CONFLICT"
    );
    assert_eq!(
        save(&mut conn, "two", " stale", 0, || Ok(()))
            .unwrap_err()
            .code,
        "VERSION_CONFLICT"
    );
    assert_eq!(state(&conn), (1, 1));
}

#[test]
fn concurrent_requests_share_one_committed_receipt() {
    // Use a real SQLite file for busy_timeout rather than SQLite's shared-cache
    // table locks, which report SQLITE_LOCKED without waiting.
    let path = std::env::temp_dir().join(format!("studyflow-write-{}.db", std::process::id()));
    assert!(!path.exists());
    let mut destination = Connection::open(&path).unwrap();
    {
        let source = source();
        let backup = rusqlite::backup::Backup::new(&source, &mut destination).unwrap();
        assert!(matches!(
            backup.step(-1).unwrap(),
            rusqlite::backup::StepResult::Done
        ));
    }
    let gate = Arc::new(Barrier::new(2));
    let responses = std::thread::scope(|scope| {
        let jobs = (0..2)
            .map(|_| {
                let gate = gate.clone();
                let path = &path;
                scope.spawn(move || {
                    let mut connection = Connection::open(path).unwrap();
                    connection
                        .busy_timeout(std::time::Duration::from_secs(3))
                        .unwrap();
                    gate.wait();
                    save(&mut connection, "parallel", "same", 0, || Ok(())).unwrap()
                })
            })
            .collect::<Vec<_>>();
        jobs.into_iter()
            .map(|job| job.join().unwrap())
            .collect::<Vec<_>>()
    });
    assert_eq!(responses[0], responses[1]);
    assert_eq!(state(&destination), (1, 1));
    drop(destination);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn malformed_or_legacy_key_is_never_reused_for_a_new_write() {
    for key in ["", " \u{1f}\t", &"题".repeat(161)] {
        assert_eq!(validate_key(key).unwrap_err().code, "INVALID_ARGUMENT");
    }
    assert!(validate_key(&"题".repeat(160)).is_ok());
    let legacy = StoredReceipt {
        operation: Some("SAVE".into()),
        payload_hash: None,
        result_json: None,
    };
    assert_eq!(
        legacy.replay(Some("SAVE"), "hash").unwrap_err().code,
        "IDEMPOTENCY_UNVERIFIABLE"
    );
    let corrupt = StoredReceipt {
        operation: None,
        payload_hash: Some("hash".into()),
        result_json: Some("[".into()),
    };
    assert_eq!(
        corrupt.replay(None, "hash").unwrap_err().code,
        "IDEMPOTENCY_UNVERIFIABLE"
    );
}

#[test]
fn python_json_byte_layout_preserves_spaces_unicode_null_and_floats() {
    let payload = json!({"z":null,"unicode":"课😀\u{7f}\n","values":[0.0,-0.0,0.0001,0.00001,1e15,1e16,1e100,5e-324,true]});
    let ascii = r#"{"unicode": "\u8bfe\ud83d\ude00\u007f\n", "values": [0.0, -0.0, 0.0001, 1e-05, 1000000000000000.0, 1e+16, 1e+100, 5e-324, true], "z": null}"#;
    assert_eq!(JsonFingerprint::Ascii.serialize(&payload), ascii);
    let utf8 = ascii.replace(r#"\u8bfe\ud83d\ude00\u007f"#, "课😀\u{7f}");
    assert_eq!(JsonFingerprint::Utf8.serialize(&payload), utf8);
    assert_eq!(
        JsonFingerprint::CompactUtf8.serialize(&payload),
        utf8.replace(": ", ":").replace(", ", ",")
    );
    assert_ne!(
        JsonFingerprint::Ascii.hash(&json!([" x"])),
        JsonFingerprint::Ascii.hash(&json!(["x"]))
    );
    assert_ne!(
        JsonFingerprint::Ascii.hash(&json!([null])),
        JsonFingerprint::Ascii.hash(&json!([]))
    );
}

#[test]
fn whole_course_fingerprints_follow_historical_sorting_and_optional_fields() {
    use studyflow_core::learning::request_fingerprints::course_answers;
    let a = json!({"exercise_id": "a", "answer_text": " A ", "retest_task_id": null});
    let b = json!({"exercise_id": "b", "answer_text": "写作 😀", "task_id": null});
    let hash = |rows: &[Value]| course_answers("course", None, "USER_WEB", "DRAFT_SAVE", rows);
    assert_eq!(hash(&[b.clone(), a.clone()]), hash(&[a.clone(), b]));
    let canonical = json!({"course_id":"course","source":"USER_WEB","operation":"DRAFT_SAVE","answers":[
        {"exercise_id":"a","answer_text":" A ","submission_id":null,"expected_version":null,"parent_submission_id":null,"task_id":null}
    ]});
    assert_eq!(hash(&[a.clone()]), JsonFingerprint::Ascii.hash(&canonical));
    assert_ne!(
        hash(&[a.clone()]),
        hash(&[json!({"exercise_id":"a","answer_text":"A"})])
    );
    assert_ne!(
        hash(&[a.clone()]),
        course_answers("course", Some("round"), "USER_WEB", "DRAFT_SAVE", &[a])
    );
}

#[test]
#[ignore = "Run with STUDYFLOW_F3_EVIDENCE and STUDYFLOW_F3_DATABASE set to the isolated W0.3 fixture"]
fn f3_original_receipts_match_rust_fingerprints() {
    let path = std::env::var_os("STUDYFLOW_F3_EVIDENCE").unwrap();
    let evidence: Vec<Value> = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let folder = std::env::var_os("STUDYFLOW_F3_DATABASE").unwrap();
    assert_eq!(evidence.len(), 7);
    for case in evidence {
        use studyflow_core::learning::{notebook, request_fingerprints as request};
        let filename = case["database"].as_str().unwrap();
        let db = studyflow_core::infrastructure::sqlite::read_existing(
            &Path::new(&folder).join(filename),
        )
        .unwrap();
        let args = &case["params"];
        let text = |key: &str| args[key].as_str().unwrap();
        let version = || args["expected_version"].as_i64().unwrap();
        let hash = match case["method"].as_str().unwrap() {
            "course.study.open" => request::open_study(
                text("course_id"),
                args["plan_line_id"].as_str(),
                args["new_version"].as_bool().unwrap_or(false),
                args["review_round"].as_bool().unwrap_or(false),
            ),
            "course.answers.draft.save" => request::course_answers(
                text("course_id"),
                args["study_session_id"].as_str(),
                args["source"].as_str().unwrap_or("USER_WEB"),
                "DRAFT_SAVE",
                args["answers"].as_array().unwrap(),
            ),
            "course.english.save" => request::english_save(
                text("study_session_id"),
                text("exercise_id"),
                text("answer_text"),
                version(),
                args["skipped"].as_bool().unwrap_or(false),
            ),
            "course.notes.save" => request::study_note(
                text("study_session_id"),
                text("lesson_id"),
                text("text"),
                version(),
            ),
            "plan.notebook.apply" => notebook::apply_fingerprint(
                text("plan_line_id"),
                version(),
                args["operations"].as_array().unwrap(),
                args["new_sources"]
                    .as_array()
                    .map(Vec::as_slice)
                    .unwrap_or_default(),
            ),
            "plan.notebook.save" => notebook::legacy_save_fingerprint(
                text("plan_line_id"),
                args["blocks"].as_array().unwrap(),
                version(),
            ),
            _ => panic!("unexpected fixture operation"),
        };
        let table = case["table"].as_str().unwrap();
        let lookup = match table {
            "course_write_receipts" => "SELECT operation,payload_hash,result_json FROM course_write_receipts WHERE idempotency_key=?",
            "study_note_receipts" => "SELECT NULL,payload_hash,result_json FROM study_note_receipts WHERE idempotency_key=?",
            "plan_notebook_receipts" => "SELECT NULL,payload_hash,result_json FROM plan_notebook_receipts WHERE idempotency_key=?",
            _ => panic!("unexpected fixture receipt table"),
        };
        let receipt = db
            .query_row(lookup, [case["key"].as_str().unwrap()], |row| {
                Ok(StoredReceipt {
                    operation: row.get(0)?,
                    payload_hash: row.get(1)?,
                    result_json: row.get(2)?,
                })
            })
            .unwrap();
        assert_eq!(
            Some(hash.as_str()),
            case["hash"].as_str(),
            "{}",
            case["key"]
        );
        let result = receipt.replay(case["operation"].as_str(), &hash).unwrap();
        assert_eq!(result, case["result"], "{}", case["key"]);
        assert_eq!(
            receipt
                .replay(
                    case["operation"].as_str(),
                    &JsonFingerprint::Ascii.hash(&json!([args, "changed"]))
                )
                .unwrap_err()
                .code,
            "IDEMPOTENCY_KEY_CONFLICT"
        );
    }
}
