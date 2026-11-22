use std::{collections::HashSet, fs::File, io::Read, path::Path};

use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{json, Map, Value};

use crate::infrastructure::fingerprint::JsonFingerprint;

pub use super::validation::PackageError;
use super::{blocks, english, groups, validation::*};

const MAX_FILE_BYTES: u64 = 4 * 1024 * 1024;
const SCHEMA_PREFIX: &str = "studyflow.course-package/";
const GENERAL_TYPES: &[&str] = &[
    "SHORT_ANSWER",
    "CODE",
    "ESSAY",
    "EXAM_QUESTION",
    "CHECKLIST",
    "SELF_EXPLANATION",
    "PROJECT_ANALYSIS",
    "OTHER",
];

#[derive(Clone, Copy)]
pub(super) struct Contract {
    pub(super) revision: u8,
    pub(super) english: bool,
}

impl Contract {
    pub(super) fn training(self) -> bool {
        matches!(self.revision, 6 | 8)
    }
}

pub fn capabilities() -> Value {
    let schemas: Vec<_> = (1..=8)
        .map(|revision| format!("{SCHEMA_PREFIX}{revision}"))
        .collect();
    let all_blocks = [
        "callout",
        "comparison",
        "concept",
        "details",
        "example",
        "practice",
        "steps",
        "summary",
    ];
    let schema_blocks: Map<_, _> = schemas
        .iter()
        .enumerate()
        .map(|(index, schema)| {
            let types: Vec<_> = all_blocks
                .iter()
                .copied()
                .filter(|kind| index >= 2 || *kind != "details")
                .collect();
            (schema.clone(), json!(types))
        })
        .collect();
    json!({
        "course_package_schemas": schemas,
        "learning_modes": ["general", "english"],
        "teaching_block_types": all_blocks,
        "schema_block_types": schema_blocks,
        "details": {"schema": schemas[2], "required_fields": ["id", "type", "title", "summary", "body"],
            "max_chars": {"title": 200, "summary": 3000, "body": 20_000}, "nested_blocks": false, "default_expanded": false},
        "structured_sections": {"schema": schemas[4], "max_depth": 2, "max_sections": 40, "max_body_chars": 20_000, "roles": ["main", "supplement"]},
        "progression": {"schema": schemas[3], "fields": ["chain_id", "stage"], "stages": english::STAGES,
            "supplement_requires": ["vocabulary", "pattern", "transfer"], "original_errors_auto_resolved": false},
    })
}

pub fn read(path: &Path) -> Result<Value, PackageError> {
    let mut bytes = Vec::new();
    File::open(path)
        .and_then(|file| file.take(MAX_FILE_BYTES + 1).read_to_end(&mut bytes))
        .map_err(|_| PackageError::at("file", "课程包不存在或超过4MiB"))?;
    if bytes.len() as u64 > MAX_FILE_BYTES {
        return invalid("file", "课程包不存在或超过4MiB");
    }
    parse(&bytes)
}

pub fn parse(bytes: &[u8]) -> Result<Value, PackageError> {
    if bytes.len() as u64 > MAX_FILE_BYTES {
        return invalid("file", "课程包超过4MiB");
    }
    let payload = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(bytes);
    let UniqueJson(package) = serde_json::from_slice(payload)
        .map_err(|error| PackageError::at("json", format!("JSON无法读取：{error}")))?;
    validate(&package)?;
    Ok(package)
}

pub fn inspect(package: &Value) -> Result<Value, PackageError> {
    validate(package)?;
    let lessons = package["lessons"].as_array().expect("validated lessons");
    Ok(json!({
        "valid": true, "schema": package["schema"], "learning_mode": package["course"]["learning_mode"].as_str().unwrap_or("general"),
        "package_id": package["package_id"], "content_hash": JsonFingerprint::CompactUtf8.hash(package),
        "course_title": package["course"]["title"], "plan_line": package["plan_line"],
        "knowledge_total": lessons.len(),
        "exercise_total": lessons.iter().map(|lesson| lesson["exercises"].as_array().map_or(0, Vec::len)).sum::<usize>(),
        "block_total": lessons.iter().map(|lesson| lesson["blocks"].as_array().expect("validated blocks").len()).sum::<usize>(),
    }))
}

pub fn validate(package: &Value) -> Result<(), PackageError> {
    let fields = ["schema", "package_id", "plan_line", "course", "lessons"];
    object(package, "package", &fields, &fields)?;
    let revision = schema_revision(&package["schema"])
        .ok_or_else(|| PackageError::at("schema", "不支持的课程协议版本"))?;
    identifier(&package["package_id"], "package_id")?;
    text(&package["plan_line"], "plan_line", 200, false)?;
    let mut course_fields = vec!["title", "summary", "subject", "difficulty"];
    if revision >= 2 {
        course_fields.push("learning_mode");
    }
    let course = &package["course"];
    object(course, "course", &course_fields, &["title"])?;
    let mode = choice(
        course.get("learning_mode"),
        "general",
        &["general", "english"],
        "course.learning_mode",
        "未知学习模式",
    )?;
    if revision == 7 && mode != "general" {
        return invalid(
            "course.learning_mode",
            "/7 使用 general 兼容入口；英语专注训练使用 /8",
        );
    }
    if revision == 8 && mode != "english" {
        return invalid("course.learning_mode", "/8 需要 english 课程入口");
    }
    text(&course["title"], "course.title", 200, false)?;
    for (key, limit) in [("summary", 4000), ("subject", 120), ("difficulty", 32)] {
        default_text(course.get(key), &format!("course.{key}"), limit)?;
    }
    let contract = Contract {
        revision,
        english: mode == "english",
    };
    let mut seen = HashSet::new();
    let mut count = 0;
    for (index, lesson) in list(&package["lessons"], "lessons", 1, 50)?
        .iter()
        .enumerate()
    {
        let field = format!("lessons[{index}]");
        let (id, exercises) = validate_lesson(lesson, &field, contract)?;
        if contract.english && exercises == 0 {
            return invalid("lessons", "英语训练组至少一项训练");
        }
        if !seen.insert(id) {
            return invalid("lessons", "重复知识点id");
        }
        count += exercises;
    }
    if count > 500 {
        return invalid("lessons.exercises", "整课最多500道题");
    }
    english::validate_chains(package, false).map(|_| ())
}

pub(super) fn schema_revision(schema: &Value) -> Option<u8> {
    schema
        .as_str()
        .and_then(|schema| schema.strip_prefix(SCHEMA_PREFIX))
        .filter(|suffix| suffix.len() == 1)
        .and_then(|suffix| suffix.parse::<u8>().ok())
        .filter(|revision| (1..=8).contains(revision))
}

pub(super) fn validate_lesson<'a>(
    lesson: &'a Value,
    field: &str,
    contract: Contract,
) -> Checked<(&'a str, usize)> {
    object(
        lesson,
        field,
        &["id", "title", "blocks", "exercises"],
        &["id", "title", "blocks"],
    )?;
    let id = identifier(&lesson["id"], &format!("{field}.id"))?;
    text(&lesson["title"], &format!("{field}.title"), 200, false)?;
    let exercises = validate_exercises(lesson.get("exercises"), field, contract)?;
    blocks::validate(
        &lesson["blocks"],
        &format!("{field}.blocks"),
        contract,
        &exercises,
    )?;
    Ok((id, exercises.len()))
}

fn validate_exercises<'a>(
    exercises: Option<&'a Value>,
    field: &str,
    contract: Contract,
) -> Checked<HashSet<&'a str>> {
    let mut fields = vec!["id", "title", "prompt", "requirements", "type"];
    if contract.revision >= 5 {
        fields.push("review_reference");
    }
    if contract.english {
        fields.push("english");
    }
    if contract.revision >= 7 {
        fields.extend(["reading", "listening", "essay"]);
    }
    let mut seen = HashSet::new();
    for (index, exercise) in default_list(exercises, &format!("{field}.exercises"), 100)?
        .iter()
        .enumerate()
    {
        let loc = format!("{field}.exercises[{index}]");
        object(exercise, &loc, &fields, &["id", "title", "prompt"])?;
        let kind = exercise
            .get("type")
            .map_or(Some("SHORT_ANSWER"), Value::as_str)
            .unwrap_or("");
        let specialty =
            contract.revision >= 7 && matches!(kind, "READING_GROUP" | "LISTENING_GROUP" | "ESSAY");
        if specialty && exercise.get("english").is_some() {
            return invalid(&format!("{loc}.english"), "专项题使用各自的题型字段");
        }
        if contract.english && !specialty && exercise.get("english").is_none() {
            return invalid(&format!("{loc}.english"), "词句训练缺少 english");
        }
        if contract.revision >= 7 {
            groups::validate_exercise(exercise, kind, &loc, contract.revision == 8)?;
        }
        if let Some(reference) = exercise.get("review_reference") {
            validate_reference(reference, &format!("{loc}.review_reference"))?;
        }
        if contract.english && !specialty {
            english::validate(&exercise["english"], &format!("{loc}.english"), contract)?;
        }
        let id = identifier(&exercise["id"], &format!("{loc}.id"))?;
        if !seen.insert(id) {
            return invalid(&loc, "重复题目id");
        }
        text(&exercise["title"], &format!("{loc}.title"), 200, false)?;
        text(&exercise["prompt"], &format!("{loc}.prompt"), 20_000, false)?;
        default_text(
            exercise.get("requirements"),
            &format!("{loc}.requirements"),
            20_000,
        )?;
        if !specialty && !GENERAL_TYPES.contains(&kind) {
            return invalid(&loc, "未知题目类型");
        }
    }
    Ok(seen)
}

fn validate_reference(reference: &Value, loc: &str) -> Checked<()> {
    object(
        reference,
        loc,
        &[
            "answer",
            "explanation",
            "criteria",
            "accepted_variants",
            "source",
        ],
        &["answer", "explanation", "criteria"],
    )?;
    for key in ["answer", "explanation"] {
        text(&reference[key], &format!("{loc}.{key}"), 20_000, false)?;
    }
    for (key, min) in [("criteria", 1), ("accepted_variants", 0)] {
        if let Some(items) = reference.get(key) {
            let field = format!("{loc}.{key}");
            for item in list(items, &field, min, 30)? {
                text(item, &field, 3000, false)?;
            }
        }
    }
    if let Some(source) = reference.get("source") {
        text(source, &format!("{loc}.source"), 3000, false)?;
    }
    Ok(())
}

struct UniqueJson(Value);

impl<'de> Deserialize<'de> for UniqueJson {
    fn deserialize<D: Deserializer<'de>>(input: D) -> Result<Self, D::Error> {
        struct JsonVisitor;
        impl<'de> Visitor<'de> for JsonVisitor {
            type Value = UniqueJson;
            fn expecting(&self, out: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                out.write_str("JSON value")
            }
            fn visit_bool<E: de::Error>(self, value: bool) -> Result<Self::Value, E> {
                Ok(UniqueJson(value.into()))
            }
            fn visit_i64<E: de::Error>(self, value: i64) -> Result<Self::Value, E> {
                Ok(UniqueJson(value.into()))
            }
            fn visit_u64<E: de::Error>(self, value: u64) -> Result<Self::Value, E> {
                Ok(UniqueJson(value.into()))
            }
            fn visit_f64<E: de::Error>(self, value: f64) -> Result<Self::Value, E> {
                Ok(UniqueJson(value.into()))
            }
            fn visit_str<E: de::Error>(self, value: &str) -> Result<Self::Value, E> {
                Ok(UniqueJson(value.into()))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(UniqueJson(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(
                self,
                mut sequence: A,
            ) -> Result<Self::Value, A::Error> {
                let mut items = Vec::new();
                while let Some(UniqueJson(value)) = sequence.next_element()? {
                    items.push(value);
                }
                Ok(UniqueJson(Value::Array(items)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut fields: A) -> Result<Self::Value, A::Error> {
                use de::Error;
                let mut values = Map::new();
                while let Some((key, UniqueJson(value))) =
                    fields.next_entry::<String, UniqueJson>()?
                {
                    if values.insert(key.clone(), value).is_some() {
                        return Err(A::Error::custom(format!("重复字段 {key}")));
                    }
                }
                Ok(UniqueJson(Value::Object(values)))
            }
        }
        input.deserialize_any(JsonVisitor)
    }
}
