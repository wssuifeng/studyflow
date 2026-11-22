use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use rusqlite::{named_params, params, Connection, OptionalExtension};
use serde_json::{json, Value};
use time::{
    format_description::well_known::Iso8601, macros::format_description, Date, OffsetDateTime,
    PrimitiveDateTime,
};

use crate::{
    infrastructure::{fingerprint::JsonFingerprint::Ascii, StorageError},
    learning::study_sessions,
};

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Domain {
    General,
    English,
}

impl Domain {
    pub(super) fn name(self) -> &'static str {
        match self {
            Self::English => "english",
            Self::General => "general",
        }
    }
    pub(super) fn table(self) -> &'static str {
        match self {
            Self::English => "english_error_aggregates",
            Self::General => "general_mistake_entries",
        }
    }
    fn evidence(self) -> (&'static str, &'static str) {
        match self {
            Self::English => ("english_error_evidence", "aggregate_id"),
            Self::General => ("general_mistake_occurrences", "entry_id"),
        }
    }
}

fn invalid() -> StorageError {
    StorageError::new("INVALID_ARGUMENT")
}

pub(super) fn normalize(input: &Value) -> Value {
    let mut scope = json!({"notebook_id":null,"plan_line_id":null,"domain":null,"course_id":null,"archived":false,"objective_id":null,"since":null,"until":null,"view":"training_errors"});
    for (key, value) in scope.as_object_mut().unwrap() {
        if let Some(field) = input.get(key) {
            *value = field.clone();
        }
    }
    scope
}

fn date(value: Option<&str>) -> Result<Option<String>, StorageError> {
    let Some(value) = value.filter(|value| !value.is_empty()) else {
        return Ok(None);
    };
    let iso = value.replacen(' ', "T", 1);
    let date = PrimitiveDateTime::parse(&iso, &Iso8601::DEFAULT)
        .ok()
        .or_else(|| {
            OffsetDateTime::parse(&iso, &Iso8601::DEFAULT)
                .ok()
                .map(|timestamp| PrimitiveDateTime::new(timestamp.date(), timestamp.time()))
        })
        .or_else(|| {
            Date::parse(&iso, format_description!("[year]-[month]-[day]"))
                .ok()
                .map(|date| date.midnight())
        })
        .ok_or_else(invalid)?;
    Ok(Some(
        date.format(format_description!(
            "[year]-[month]-[day] [hour]:[minute]:[second].[subsecond digits:6]"
        ))
        .map_err(|_| invalid())?,
    ))
}

pub(super) struct Scope {
    pub(super) value: Value,
    pub(super) domain: Domain,
    book: Option<String>,
    since: Option<String>,
    until: Option<String>,
}

pub(super) struct Entry {
    pub(super) id: String,
    pub(super) version: i64,
    pub(super) course: String,
    pub(super) rule: String,
    pub(super) status: Option<String>,
    exercise: String,
    title: String,
    course_title: String,
    objectives: Option<String>,
    attempts: i64,
    rounds: i64,
    review: Option<String>,
}

impl Scope {
    pub(super) fn new(db: &Connection, input: &Value) -> Result<Self, StorageError> {
        let value = normalize(input);
        for key in [
            "notebook_id",
            "plan_line_id",
            "domain",
            "course_id",
            "objective_id",
            "since",
            "until",
        ] {
            if !value[key].is_null() && !value[key].is_string() {
                return Err(invalid());
            }
        }
        let nonempty = |key: &str| value[key].as_str().filter(|text| !text.is_empty());
        let plan = nonempty("plan_line_id");
        let requested = nonempty("domain");
        if requested.is_some_and(|domain| !matches!(domain, "english" | "general"))
            || !value["archived"].is_boolean()
            || !matches!(
                value["view"].as_str(),
                Some("training_errors" | "review_queue")
            )
        {
            return Err(invalid());
        }
        let (book, domain) = if let Some(id) = nonempty("notebook_id") {
            let (stored, member) = db
                .query_row(
                    "SELECT domain,plan_line_id FROM mistake_notebooks WHERE id=?",
                    [id],
                    |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?)),
                )
                .optional()?
                .ok_or_else(|| StorageError::new("SCOPE_MISMATCH"))?;
            if requested.is_some_and(|domain| domain != stored)
                || plan.is_some_and(|plan| Some(plan) != member.as_deref())
            {
                return Err(StorageError::new("SCOPE_MISMATCH"));
            }
            (Some(id.to_owned()), stored)
        } else {
            let (Some(plan), Some(domain)) = (plan, requested) else {
                return Err(StorageError::new("SCOPE_REQUIRED"));
            };
            if !db.query_row(
                "SELECT EXISTS(SELECT 1 FROM plan_lines WHERE id=?)",
                [plan],
                |row| row.get::<_, bool>(0),
            )? {
                return Err(StorageError::new("OBJECT_NOT_FOUND"));
            }
            (
                super::notebook(db, Some(plan), domain, false)?,
                domain.to_owned(),
            )
        };
        let domain = match domain.as_str() {
            "english" => Domain::English,
            "general" => Domain::General,
            _ => return Err(invalid()),
        };
        if domain == Domain::General && nonempty("objective_id").is_some() {
            return Err(invalid());
        }
        Ok(Self {
            since: date(nonempty("since"))?,
            until: date(nonempty("until"))?,
            value,
            domain,
            book,
        })
    }

    fn tagged(&self) -> bool {
        self.since.is_some() || self.until.is_some()
    }

    pub(super) fn hash(&self, id: Option<&str>) -> String {
        Ascii.hash(&json!({"scope":self.value,"domain":self.domain.name(),"notebook_id":self.book,"identifier":id}))
    }

    pub(super) fn entries(
        &self,
        db: &Connection,
        identifier: Option<&str>,
        after: Option<&str>,
        limit: i64,
    ) -> Result<Vec<Entry>, StorageError> {
        let table = self.domain.table();
        let (evidence, key) = self.domain.evidence();
        let english = self.domain == Domain::English;
        let columns = if english {
            "a.objective_ids_json,a.failed_attempts,a.failed_rounds,r.status,NULL"
        } else {
            "NULL,0,0,NULL,a.status"
        };
        let join = if english {
            "LEFT JOIN english_review_items r ON r.aggregate_id=a.id"
        } else {
            ""
        };
        let objective = if english {
            "AND (:objective IS NULL OR instr(a.objective_ids_json,'\"'||:objective||'\"')>0) AND (NOT :review OR r.status IN ('PENDING','RETESTING'))"
        } else {
            "AND (:objective IS NULL) AND (:review IN (0,1))"
        };
        let mut query=db.prepare(&format!("SELECT a.id,a.version,a.course_id,a.exercise_key,a.rule_hash,c.title,COALESCE(e.title,'历史训练项'),{columns}
            FROM {table} a JOIN courses c ON c.id=a.course_id LEFT JOIN exercises e ON e.id=a.exercise_key {join}
            WHERE a.notebook_id=:book AND a.archived=:archived AND (:course IS NULL OR a.course_id=:course)
            AND (:id IS NULL OR a.id=:id) AND (:after IS NULL OR a.id>:after) {objective}
            AND ((:since IS NULL AND :until IS NULL) OR EXISTS(SELECT 1 FROM {evidence} ev WHERE ev.{key}=a.id AND (:since IS NULL OR ev.created_at>=:since) AND (:until IS NULL OR ev.created_at<=:until)))
            ORDER BY a.id LIMIT :limit"))?;
        let entries=query.query_map(named_params!{":book":self.book,":archived":self.value["archived"]==true,":course":self.value["course_id"].as_str().filter(|text|!text.is_empty()),":id":identifier,":after":after,":objective":self.value["objective_id"].as_str().filter(|text|!text.is_empty()),":review":self.value["view"]=="review_queue",":since":self.since,":until":self.until,":limit":limit}, |row|Ok(Entry{id:row.get(0)?,version:row.get(1)?,course:row.get(2)?,exercise:row.get(3)?,rule:row.get(4)?,course_title:row.get(5)?,title:row.get(6)?,objectives:row.get(7)?,attempts:row.get(8)?,rounds:row.get(9)?,review:row.get(10)?,status:row.get(11)?}))?.collect::<Result<Vec<_>,_>>()?;
        Ok(entries)
    }

    fn evidence_counts(
        &self,
        db: &Connection,
        ids: &[&str],
    ) -> Result<(i64, i64, i64), StorageError> {
        Ok(db.query_row("SELECT COUNT(*),COUNT(DISTINCT round_key),COALESCE(SUM(valid_error),0) FROM english_error_evidence WHERE aggregate_id IN (SELECT value FROM json_each(?1)) AND (?2 IS NULL OR created_at>=?2) AND (?3 IS NULL OR created_at<=?3)",params![json!(ids).to_string(),self.since,self.until],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?)))?)
    }
}

fn cursor(input: &Value, hash: &str) -> Result<Option<String>, StorageError> {
    let invalid = || StorageError::new("INVALID_CURSOR");
    let Some(input) = input.as_str().filter(|value| !value.is_empty()) else {
        return if input.is_null() || input.is_string() {
            Ok(None)
        } else {
            Err(invalid())
        };
    };
    if input.len() > 512 {
        return Err(invalid());
    }
    let raw = URL_SAFE_NO_PAD.decode(input).map_err(|_| invalid())?;
    let value: Value = serde_json::from_slice(&raw).map_err(|_| invalid())?;
    if value["v"] != 1 || value["scope"] != hash {
        return Err(invalid());
    }
    Ok(Some(
        value["last"]
            .as_str()
            .filter(|value| value.chars().count() == 36)
            .ok_or_else(invalid)?
            .into(),
    ))
}

fn encode(id: &str, hash: &str) -> String {
    URL_SAFE_NO_PAD.encode(format!(
        "{{\"v\":1,\"last\":{},\"scope\":\"{hash}\"}}",
        json!(id)
    ))
}

fn parse_json(raw: &str) -> Result<Value, StorageError> {
    serde_json::from_str(raw).map_err(|err| StorageError::caused_by("DATABASE_ERROR", err))
}

pub fn notebooks(db: &Connection) -> Result<Value, StorageError> {
    let mut q=db.prepare("SELECT b.id,b.plan_line_id,b.domain,COALESCE(p.name,'未归属课程') FROM mistake_notebooks b LEFT JOIN plan_lines p ON p.id=b.plan_line_id ORDER BY b.scope_key,b.domain")?;
    let items=q.query_map([],|row|Ok(json!({"id":row.get::<_,String>(0)?,"plan_line_id":row.get::<_,Option<String>>(1)?,"domain":row.get::<_,String>(2)?,"title":row.get::<_,String>(3)?})))?.collect::<Result<Vec<_>,_>>()?;
    Ok(json!({"notebooks":items}))
}

pub fn summary(db: &Connection, input: &Value) -> Result<Value, StorageError> {
    let scope = Scope::new(db, input)?;
    let rows = scope.entries(db, None, None, -1)?;
    let mut result = json!({"domain":scope.domain.name(),"notebook_id":scope.book,"entry_total":rows.len(),"scope":scope.value,
        "counting_basis":"失败尝试为历史未匹配/批改证据；轮次数按范围内学习轮次/任务去重；有效错误排除Agent已接受的表达。"});
    if scope.domain == Domain::English {
        let (attempts, rounds, valid) = scope.evidence_counts(
            db,
            &rows.iter().map(|row| row.id.as_str()).collect::<Vec<_>>(),
        )?;
        result["failed_attempts"] = json!(if scope.tagged() {
            attempts
        } else {
            rows.iter().map(|row| row.attempts).sum()
        });
        result["failed_rounds"] = json!(rounds);
        result["review_total"] = json!(rows
            .iter()
            .filter(|row| matches!(row.review.as_deref(), Some("PENDING" | "RETESTING")))
            .count());
        result["valid_error_evidence"] = json!(valid);
    }
    Ok(result)
}

fn limit(input: &Value) -> Result<usize, StorageError> {
    input
        .get("limit")
        .map_or(Some(30), Value::as_u64)
        .filter(|value| (1..=100).contains(value))
        .map(|value| value as usize)
        .ok_or_else(invalid)
}

pub fn list(db: &Connection, input: &Value) -> Result<Value, StorageError> {
    let scope = Scope::new(db, input)?;
    let limit = limit(input)?;
    let hash = scope.hash(None);
    let after = cursor(&input["cursor"], &hash)?;
    let entries = scope.entries(db, None, after.as_deref(), limit as i64 + 1)?;
    let mut items = Vec::new();
    for row in entries.iter().take(limit) {
        let mut item = json!({"id":row.id,"notebook_id":scope.book,"course_id":row.course,"course_title":row.course_title,"exercise_id":row.exercise,"title":row.title,"rule_hash":row.rule,"version":row.version,"archived":scope.value["archived"]});
        if scope.domain == Domain::English {
            let (attempts, rounds) = if scope.tagged() {
                let (a, r, _) = scope.evidence_counts(db, &[&row.id])?;
                (a, r)
            } else {
                (row.attempts, row.rounds)
            };
            item.as_object_mut().unwrap().extend(json!({"failed_attempts":attempts,"failed_rounds":rounds,"lifetime_failed_attempts":row.attempts,"lifetime_failed_rounds":row.rounds,"objective_ids":parse_json(row.objectives.as_deref().unwrap_or("[]"))?,"review_status":row.review}).as_object().unwrap().clone());
        } else {
            item["status"] = json!(row.status);
        }
        items.push(item);
    }
    let next = (entries.len() > limit).then(|| encode(&entries[limit - 1].id, &hash));
    Ok(json!({"items":items,"domain":scope.domain.name(),"next_cursor":next}))
}

pub fn context(db: &Connection, input: &Value) -> Result<Value, StorageError> {
    let scope = Scope::new(db, input)?;
    let id = input["identifier"]
        .as_str()
        .filter(|id| !id.is_empty())
        .ok_or_else(invalid)?;
    let entry = scope
        .entries(db, Some(id), None, 1)?
        .pop()
        .ok_or_else(|| StorageError::new("SCOPE_MISMATCH"))?;
    if !input["expected_version"].is_null() {
        let expected = input["expected_version"]
            .as_i64()
            .filter(|version| *version >= 1)
            .ok_or_else(invalid)?;
        if expected != entry.version {
            return Err(StorageError::new("VERSION_CONFLICT"));
        }
    }
    let hash = scope.hash(Some(id));
    let after = cursor(&input["cursor"], &hash)?;
    let limit = if input.get("limit").is_some() {
        limit(input)?
    } else {
        30
    };
    let (table, key) = scope.domain.evidence();
    let (attempt, valid) = if scope.domain == Domain::English {
        ("ev.attempt_id", "ev.valid_error")
    } else {
        ("NULL", "1")
    };
    let mut query=db.prepare(&format!("SELECT ev.id,s.study_session_id,s.id,ca.id,COALESCE(ca.answer_text,s.answer_text),ca.result_json,{valid},f.id,f.summary,f.issues_json,f.decision,s.exercise_id
        FROM {table} ev LEFT JOIN english_check_attempts ca ON ca.id={attempt} LEFT JOIN review_feedback f ON f.id=ev.feedback_id
        JOIN submissions s ON s.id=COALESCE(ca.submission_id,f.submission_id)
        WHERE ev.{key}=?1 AND (?2 IS NULL OR ev.created_at>=?2) AND (?3 IS NULL OR ev.created_at<=?3) AND (?4 IS NULL OR ev.id>?4)
        ORDER BY ev.id LIMIT ?5"))?;
    let mut rows = query.query(params![
        id,
        scope.since,
        scope.until,
        after,
        limit as i64 + 1
    ])?;
    let mut items = Vec::new();
    let mut more = false;
    while let Some(row) = rows.next()? {
        if items.len() == limit {
            more = true;
            break;
        }
        let study: Option<String> = row.get(1)?;
        let exercise: String = row.get(11)?;
        let frozen = study
            .as_deref()
            .map(|study| study_sessions::frozen_context(db, study, &exercise))
            .transpose()?
            .flatten();
        let result = row
            .get::<_, Option<String>>(5)?
            .as_deref()
            .map(parse_json)
            .transpose()?;
        let feedback = match row.get::<_, Option<String>>(7)? {
            None => None,
            Some(id) => Some(
                json!({"id":id,"summary":row.get::<_,String>(8)?,"issues":parse_json(&row.get::<_,String>(9)?)?,"decision":row.get::<_,String>(10)?}),
            ),
        };
        items.push(json!({"id":row.get::<_,String>(0)?,"study_session_id":study,"submission_id":row.get::<_,String>(2)?,"attempt_id":row.get::<_,Option<String>>(3)?,"answer_text":row.get::<_,String>(4)?,"result":result,"valid_error":row.get::<_,bool>(6)?,"feedback":feedback,"frozen_context":frozen}));
    }
    let next = more.then(|| encode(items.last().unwrap()["id"].as_str().unwrap(), &hash));
    Ok(
        json!({"id":entry.id,"version":entry.version,"rule_hash":entry.rule,"evidence":items,"next_cursor":next}),
    )
}

impl Entry {
    pub(super) fn archive_blocked(&self, domain: Domain) -> bool {
        match domain {
            Domain::English => matches!(self.review.as_deref(), Some("PENDING" | "RETESTING")),
            Domain::General => self.status.as_deref() != Some("PASSED"),
        }
    }
}
