use std::{collections::HashSet, path::Path};

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

use super::write_contract::{atomic_write, record_course, replay_course, validate_key};
use crate::{
    courses::{english, packages, publication, validation},
    infrastructure::{events, file_paths, fingerprint::JsonFingerprint::Ascii, StorageError},
    mistakes::remediation as query,
    planning::Track,
    workspace::Workspace,
};

fn invalid() -> StorageError {
    StorageError::new("INVALID_ARGUMENT")
}
fn invalid_package(error: packages::PackageError) -> StorageError {
    StorageError::caused_by("INVALID_COURSE_PACKAGE", error)
}

struct Prepared {
    package: Value,
    summary: Value,
    provenance: Value,
    chains: Vec<String>,
    hash: String,
}

fn prepare(db: &Connection, root: &Path, input: &Value) -> Result<Prepared, StorageError> {
    let plan = input["plan_line_id"]
        .as_str()
        .filter(|value| !value.is_empty())
        .ok_or_else(invalid)?;
    let (name, status, version) = db
        .query_row(
            "SELECT name,status,version FROM plan_lines WHERE id=?",
            [plan],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                ))
            },
        )
        .optional()?
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    if status != "ACTIVE" {
        return Err(StorageError::new("PLAN_NOT_ACTIVE"));
    }
    let objectives = input["objective_ids"]
        .as_array()
        .filter(|items| (1..=5).contains(&items.len()))
        .ok_or_else(invalid)?;
    let mut ids = HashSet::new();
    for id in objectives {
        let value = validation::identifier(id, "objective_ids").map_err(invalid_package)?;
        if !ids.insert(value) {
            return Err(invalid());
        }
    }
    let rationale = input["rationale"]
        .as_str()
        .filter(|value| !value.trim().is_empty() && value.chars().count() <= 4000)
        .ok_or_else(invalid)?;
    let sources = input["sources"]
        .as_array()
        .filter(|items| (1..=30).contains(&items.len()))
        .ok_or_else(invalid)?;
    let path = input["path"]
        .as_str()
        .filter(|value| !value.is_empty())
        .ok_or_else(invalid)?;
    let path = file_paths::workspace_path(root, Path::new(path))?;
    let package = packages::read(&path).map_err(invalid_package)?;
    let summary = packages::inspect(&package).map_err(invalid_package)?;
    if !matches!(
        package["schema"].as_str(),
        Some(
            "studyflow.course-package/4"
                | "studyflow.course-package/5"
                | "studyflow.course-package/6"
        )
    ) || package["course"]["learning_mode"] != "english"
    {
        return Err(invalid());
    }
    if package["plan_line"] != name {
        return Err(StorageError::new("SCOPE_MISMATCH"));
    }
    let chains = english::validate_chains(&package, true)
        .map_err(invalid_package)?
        .into_iter()
        .map(str::to_owned)
        .collect();
    let declared: HashSet<_> = package["lessons"]
        .as_array()
        .into_iter()
        .flatten()
        .flat_map(|lesson| lesson["exercises"].as_array().into_iter().flatten())
        .flat_map(|question| {
            question["english"]["objective_ids"]
                .as_array()
                .into_iter()
                .flatten()
        })
        .filter_map(Value::as_str)
        .collect();
    if !ids.is_subset(&declared) {
        return Err(invalid());
    }
    let provenance = json!({"plan_line_id":plan,"objective_ids":objectives,"rationale":rationale,"sources":query::freeze_sources(db,plan,sources)?});
    let hash=Ascii.hash(&json!({"content_hash":summary["content_hash"],"plan_version":version,"provenance":provenance}));
    Ok(Prepared {
        package,
        summary,
        provenance,
        chains,
        hash,
    })
}

pub fn preview(workspace: &Workspace, input: &Value) -> Result<Value, StorageError> {
    workspace.read_consistent(|db| {
        let details=prepare(db,&workspace.settings().workspace,input)?;
        let sources=details.provenance["sources"].as_array().unwrap();
        let mut response=details.summary;
        response.as_object_mut().unwrap().extend(json!({"valid":true,"plan_line_id":input["plan_line_id"],"track":"SUPPLEMENT","source_count":sources.len(),"evidence_count":sources.iter().filter_map(|source|source["evidence_ids"].as_array().map(Vec::len)).sum::<usize>(),"objective_ids":input["objective_ids"],"chains":details.chains,"preview_hash":details.hash,"mainline_unchanged":true,"auto_resolves_original_errors":false}).as_object().unwrap().clone());
        Ok(response)
    })
}

pub fn publish(workspace: &Workspace, input: &Value) -> Result<Value, StorageError> {
    let key = input["idempotency_key"].as_str().ok_or_else(invalid)?;
    validate_key(key)?;
    let preview = input["preview_hash"]
        .as_str()
        .filter(|hash| file_paths::is_sha256(hash))
        .ok_or_else(invalid)?;
    let mut payload = input.clone();
    payload
        .as_object_mut()
        .ok_or_else(invalid)?
        .remove("idempotency_key");
    let hash = Ascii.hash(&payload);
    let operation = "REMEDIATION_PUBLISH";
    let root = &workspace.settings().workspace;
    let mut active = workspace.open()?;
    atomic_write(&mut active.connection, |db| {
        if let Some(replay) = replay_course(db, key, operation, &hash)? {
            return Ok(replay);
        }
        let prepared = prepare(db, root, input)?;
        if prepared.hash != preview {
            return Err(StorageError::new("PREVIEW_CHANGED"));
        }
        let provenance = Ascii.hash(&prepared.provenance);
        let imported = publication::import_package(
            db,
            root,
            &prepared.package,
            prepared.summary,
            Track::Supplement,
        )?;
        let course = imported["course_id"]
            .as_str()
            .ok_or_else(|| StorageError::new("DATABASE_ERROR"))?;
        let plan = input["plan_line_id"].as_str().unwrap();
        let sources = prepared.provenance["sources"].as_array().unwrap();
        if imported["created"] == true {
            db.execute("INSERT INTO english_remediation_courses(course_id,plan_line_id,objective_ids_json,rationale,provenance_hash) VALUES(?,?,?,?,?)",params![course,plan,input["objective_ids"].to_string(),input["rationale"].as_str(),provenance])?;
            for source in sources {
                let aggregate = source["aggregate_id"].as_str().unwrap();
                let version = source["source_version"].as_i64().unwrap();
                for evidence in source["evidence_ids"].as_array().unwrap() {
                    db.execute("INSERT INTO english_remediation_sources(id,course_id,aggregate_id,evidence_id,source_version,rule_hash) VALUES(?,?,?,?,?,?)",params![Uuid::new_v4().to_string(),course,aggregate,evidence.as_str(),version,source["rule_hash"].as_str()])?;
                }
            }
        } else {
            let same=db.query_row("SELECT EXISTS(SELECT 1 FROM english_remediation_courses WHERE course_id=? AND plan_line_id=? AND provenance_hash=?)",params![course,plan,provenance],|row|row.get::<_,bool>(0))?;
            if !same {
                return Err(StorageError::new("COURSE_REMEDIATION_CONFLICT"));
            }
        }
        let result = json!({"course_id":course,"plan_line_id":plan,"track":"SUPPLEMENT","created":imported["created"],"content_hash":imported["content_hash"],"source_count":sources.len(),"mainline_unchanged":true,"auto_resolves_original_errors":false});
        record_course(db, course, key, operation, &hash, &result)?;
        events::record(
            db,
            "AGENT_CLI",
            "course",
            course,
            operation,
            "关联英语错误并发布补充课程，保留原错误与主线。",
        )?;
        Ok(result)
    })
}
