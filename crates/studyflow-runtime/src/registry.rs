use std::{path::Path, sync::LazyLock};

use serde_json::{json, Map, Value};
use studyflow_core::{
    audio::{dictionary::DictionaryProvider, resolution::FrozenPronunciation},
    courses::{packages, practice::GroupKind},
    documents,
    infrastructure::{
        config::{path_at_cwd, Settings},
        installation, StorageError,
    },
    workspace::{archive, Workspace},
    APP_VERSION,
};

use crate::{
    author, course, english, learning, notebook, planning, practice, review, speech, ApiError,
};

pub const PROTOCOL_VERSION: &str = "1.2";
const SCHEMA_VERSION: &str = "studyflow.agent-contract/2";

pub type Params = Map<String, Value>;

#[derive(Clone, Copy)]
pub enum Kind {
    Read,
    Write,
    Diagnostic,
}

#[derive(Clone, Copy)]
enum FieldType {
    LegacyValue,
    TextMax {
        max: usize,
    },
    VersionMap,
    IntegerBounds {
        min: i64,
        max: Option<i64>,
    },
    TrimmedKey,
    EssayAnswers,
    BoundedSource,

    NullableChoice(&'static [&'static str]),
    BoundedCount {
        max: u64,
        default: u64,
    },
    Text,
    OptionalText,
    NullableText,
    NullablePositiveInteger,
    Digest,
    NullableDigest,
    NullableNonnegativeInteger,
    PositiveInteger,
    RequiredChoice(&'static [&'static str]),
    Boolean,
    BooleanDefaultFalse,
    Object,
    BoundedText {
        max: usize,
    },
    PracticeAnswers,
    Choice {
        values: &'static [&'static str],
        default: &'static str,
    },
    OptionalIndex {
        max: u64,
    },
}

#[derive(Clone, Copy)]
struct Field {
    value_type: FieldType,
    key: &'static str,
    title: &'static str,
    required: bool,
}

const PATH: Field = Field {
    value_type: FieldType::Text,
    key: "path",
    title: "Path",
    required: true,
};
const TARGET: Field = Field {
    value_type: FieldType::Text,
    key: "target_root",
    title: "Target Root",
    required: true,
};
const METHOD: Field = Field {
    value_type: FieldType::Text,
    key: "method",
    title: "Method",
    required: false,
};

const RENDER: Field = Field {
    value_type: FieldType::Boolean,
    key: "render",
    title: "Render",
    required: false,
};

const STUDY_SESSION_ID: Field = Field {
    value_type: FieldType::Text,
    key: "study_session_id",
    title: "Study Session Id",
    required: true,
};
const EXERCISE_ID: Field = Field {
    value_type: FieldType::Text,
    key: "exercise_id",
    title: "Exercise Id",
    required: true,
};
const WORD_INDEX: Field = Field {
    value_type: FieldType::OptionalIndex { max: 79 },
    key: "word_index",
    title: "Word Index",
    required: false,
};
const ACCENT: Field = Field {
    value_type: FieldType::Choice {
        values: &["en-US", "en-GB"],
        default: "en-US",
    },
    key: "accent",
    title: "Accent",
    required: false,
};

const PACKAGE: Field = Field {
    value_type: FieldType::Object,
    key: "package",
    title: "Package",
    required: true,
};
const LESSON_ID: Field = Field {
    value_type: FieldType::BoundedText {
        max: author::ID_LIMIT,
    },
    key: "lesson_id",
    title: "Lesson Id",
    required: true,
};
const PRACTICE_EXERCISE: Field = Field {
    value_type: FieldType::BoundedText {
        max: author::ID_LIMIT,
    },
    ..EXERCISE_ID
};
const PREVIEW_ANSWERS: Field = Field {
    value_type: FieldType::PracticeAnswers,
    key: "answers",
    title: "Answers",
    required: false,
};
const PREVIEW_AUDIO: Field = Field {
    value_type: FieldType::BooleanDefaultFalse,
    key: "audio",
    title: "Audio",
    required: false,
};
const PREVIEW_CAPTIONS: Field = Field {
    value_type: FieldType::BooleanDefaultFalse,
    key: "captions",
    title: "Captions",
    required: false,
};

pub struct Method {
    pub name: &'static str,
    pub method: &'static str,
    pub kind: Kind,
    fields: &'static [Field],
    schema_title: Option<&'static str>,
    handle: fn(&Params) -> Result<Value, ApiError>,
}

impl Method {
    pub fn from_name(name: &str) -> Option<&'static Self> {
        let canonical = if name == "study.status" {
            "study.today"
        } else {
            name
        };
        METHODS.iter().find(|method| method.method == canonical)
    }

    pub fn validate(&self, params: &Params) -> Result<(), ApiError> {
        for key in params.keys() {
            if !self.fields.iter().any(|field| field.key == key) {
                return Err(ApiError::invalid_argument(format!("未知参数 {key}。")));
            }
        }
        for field in self.fields {
            match (field.value_type, params.get(field.key)) {
                (FieldType::IntegerBounds { min, max }, Some(value))
                    if value
                        .as_i64()
                        .is_some_and(|n| n >= min && max.is_none_or(|max| n <= max)) => {}
                (FieldType::TrimmedKey, Some(Value::String(value)))
                    if (1..=160).contains(&value.trim().chars().count()) => {}
                (FieldType::EssayAnswers, Some(value)) if essay_answers_valid(value) => {}
                (FieldType::BoundedSource, Some(Value::String(value)))
                    if (1..=32).contains(&value.chars().count()) => {}
                (FieldType::TextMax { max }, Some(Value::String(value)))
                    if value.chars().count() <= max => {}
                (FieldType::VersionMap, Some(Value::Object(versions)))
                    if versions.values().all(|value| value.as_i64().is_some()) => {}
                (FieldType::LegacyValue, Some(_)) => {}
                (FieldType::NullableChoice(_), Some(Value::Null)) => {}
                (FieldType::NullableChoice(values), Some(Value::String(value)))
                    if values.contains(&value.as_str()) => {}
                (FieldType::BoundedCount { max, .. }, Some(value))
                    if value
                        .as_u64()
                        .is_some_and(|number| (1..=max).contains(&number)) => {}
                (FieldType::Text, Some(Value::String(value)))
                    if !field.required || !value.is_empty() => {}
                (FieldType::Boolean | FieldType::BooleanDefaultFalse, Some(Value::Bool(_))) => {}
                (FieldType::Object, Some(Value::Object(_))) => {}
                (FieldType::NullablePositiveInteger, Some(Value::Null)) => {}
                (FieldType::Digest | FieldType::NullableDigest, Some(Value::String(value)))
                    if value.len() == 64
                        && value
                            .bytes()
                            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) => {}
                (
                    FieldType::OptionalText | FieldType::NullableText,
                    Some(Value::Null | Value::String(_)),
                ) => {}
                (FieldType::PositiveInteger | FieldType::NullablePositiveInteger, Some(value))
                    if value.as_i64().is_some_and(|n| n >= 1) => {}
                (FieldType::NullableNonnegativeInteger, Some(value))
                    if value.as_i64().is_some_and(|n| n >= 0) => {}
                (FieldType::RequiredChoice(values), Some(Value::String(value)))
                    if values.contains(&value.as_str()) => {}
                (FieldType::BoundedText { max }, Some(Value::String(value)))
                    if !value.is_empty() && value.chars().count() <= max => {}
                (FieldType::PracticeAnswers, Some(value))
                    if (!field.required || value.is_object()) && author::answers_valid(value) => {}
                (FieldType::Choice { values, .. }, Some(Value::String(value)))
                    if values.contains(&value.as_str()) => {}
                (FieldType::OptionalIndex { max }, Some(value))
                    if value.as_u64().is_some_and(|index| index <= max) => {}
                (FieldType::Choice { .. } | FieldType::BooleanDefaultFalse, Some(Value::Null)) => {
                    return Err(ApiError::invalid_argument(format!(
                        "参数 {} 不能为 null。",
                        field.key
                    )));
                }
                (_, Some(Value::Null) | None) if !field.required => {}
                _ => {
                    return Err(ApiError::invalid_argument(format!(
                        "参数 {} 的类型或长度无效。",
                        field.key
                    )))
                }
            }
        }
        Ok(())
    }

    pub fn execute(&self, params: &Params) -> Result<Value, ApiError> {
        (self.handle)(params)
    }

    fn capability(&self) -> Value {
        json!({"name": self.name, "method": self.method, "kind": match self.kind { Kind::Read => "read", Kind::Write => "write", Kind::Diagnostic => "diagnostic" }})
    }

    fn schema(&self) -> Option<Value> {
        if let Some(schema) = notebook::schema(self.method)
            .or_else(|| review::schema(self.method))
            .or_else(|| speech::schema(self.method))
        {
            return Some(schema);
        }
        let title = self.schema_title?;
        let properties: Params = self
            .fields
            .iter()
            .map(|field| {
                (
                    field.key.to_owned(),
                    match field.value_type {
                        FieldType::Text => {
                            json!({"title":field.title,"type":"string","minLength":1})
                        }
                        FieldType::Digest => json!({"title":field.title,"type":"string","pattern":"^[a-f0-9]{64}$"}),
                        FieldType::NullableDigest => json!({"title":field.title,"default":null,"anyOf":[{"type":"string","pattern":"^[a-f0-9]{64}$"},{"type":"null"}]}),
                        FieldType::NullableNonnegativeInteger => json!({"title":field.title,"default":null,"anyOf":[{"type":"integer","minimum":0},{"type":"null"}]}),
                        FieldType::NullableText => json!({"title":field.title,"default":null,"anyOf":[{"type":"string"},{"type":"null"}]}),
                        FieldType::NullablePositiveInteger => json!({"title":field.title,"default":null,"anyOf":[{"type":"integer","minimum":1},{"type":"null"}]}),
                        FieldType::OptionalText => json!({"title":field.title,"type":"string"}),
                        FieldType::PositiveInteger => json!({"title":field.title,"type":"integer","minimum":1}),
                        FieldType::RequiredChoice(values) => json!({"title":field.title,"type":"string","enum":values}),
                        FieldType::NullableChoice(values) => json!({"title":field.title,"default":null,"anyOf":[{"enum":values,"type":"string"},{"type":"null"}]}),
                        FieldType::BoundedCount {max,default} => json!({"title":field.title,"type":"integer","minimum":1,"maximum":max,"default":default}),
                        FieldType::IntegerBounds {min,max} => {
                            let mut schema=json!({"title":field.title,"type":"integer","minimum":min});
                            if let Some(max)=max {schema["maximum"]=json!(max);}
                            schema
                        },
                        FieldType::TrimmedKey => json!({"title":field.title,"type":"string","minLength":1,"maxLength":160}),
                        FieldType::EssayAnswers => json!({"title":field.title,"type":"array","minItems":1,"maxItems":1,"items":{"$ref":"#/$defs/EssayAnswer"}}),
                        FieldType::BoundedSource => json!({"title":field.title,"type":"string","minLength":1,"maxLength":32,"default":"USER_WEB"}),
                        FieldType::TextMax {max} => json!({"title":field.title,"type":"string","maxLength":max}),
                        FieldType::VersionMap => json!({"title":field.title,"type":"object","additionalProperties":{"type":"integer"}}),
                        FieldType::LegacyValue => json!({"title":field.title}),
                        FieldType::Boolean => json!({"title":field.title,"type":"boolean"}),
                        FieldType::BooleanDefaultFalse => json!({"title":field.title,"type":"boolean","default":false}),
                        FieldType::Object => json!({"title":field.title,"type":"object","additionalProperties":true}),
                        FieldType::BoundedText { max } => json!({"title":field.title,"type":"string","minLength":1,"maxLength":max}),
                        FieldType::PracticeAnswers => {
                            let mut schema=author::answers_schema(field.title);
                            if field.required {
                                let mut exact=schema["anyOf"][0].take();
                                exact["title"]=json!(field.title);
                                exact
                            } else {schema}
                        },
                        FieldType::Choice { values, default } => json!({"title":field.title,"type":"string","enum":values,"default":default}),
                        FieldType::OptionalIndex { max } => json!({"title":field.title,"default":null,"anyOf":[{"type":"integer","minimum":0,"maximum":max},{"type":"null"}]}),
                    },
                )
            })
            .collect();
        let required: Vec<_> = self
            .fields
            .iter()
            .filter(|f| f.required)
            .map(|f| f.key)
            .collect();
        let mut schema = json!({"title":title,"type":"object","additionalProperties":false,"properties":properties});
        if !required.is_empty() {
            schema["required"] = json!(required);
        }
        if title == "EssayRequest" {
            schema["$defs"] = json!({"EssayAnswer":essay_answer_schema()});
        }
        Some(schema)
    }
}

const PLAN_ID: Field = Field {
    value_type: FieldType::Text,
    key: "plan_line_id",
    title: "Plan Line Id",
    required: true,
};
const OPTIONAL_PLAN_ID: Field = Field {
    value_type: FieldType::OptionalText,
    required: false,
    ..PLAN_ID
};
const DATE: Field = Field {
    value_type: FieldType::OptionalText,
    key: "date",
    title: "Date",
    required: false,
};
const TASK_KIND: Field = Field {
    value_type: FieldType::OptionalText,
    key: "task_kind",
    title: "Task Kind",
    required: false,
};
const INCLUDE_INACTIVE: Field = Field {
    value_type: FieldType::Boolean,
    key: "include_inactive",
    title: "Include Inactive",
    required: false,
};
const SCOPE: Field = Field {
    value_type: FieldType::OptionalText,
    key: "scope",
    title: "Scope",
    required: false,
};
const PLAN_EDIT_FIELDS: &[Field] = &[
    PLAN_ID,
    Field {
        value_type: FieldType::PositiveInteger,
        key: "expected_version",
        title: "Expected Version",
        required: true,
    },
    Field {
        value_type: FieldType::BoundedText { max: 160 },
        key: "idempotency_key",
        title: "Idempotency Key",
        required: true,
    },
    Field {
        value_type: FieldType::RequiredChoice(&[
            "UPDATE",
            "REORDER",
            "SCHEDULE",
            "RESCHEDULE",
            "CANCEL_SCHEDULE",
            "COURSE_POSITION",
        ]),
        key: "operation",
        title: "Operation",
        required: true,
    },
    Field {
        value_type: FieldType::Object,
        key: "values",
        title: "Values",
        required: true,
    },
];

const FILE: Field = Field {
    key: "file",
    title: "File",
    required: false,
    ..PATH
};
const IMPORT_PATH: Field = Field {
    required: false,
    ..PATH
};

const COURSE_ID: Field = Field {
    value_type: FieldType::Text,
    key: "course_id",
    title: "Course Id",
    required: true,
};
const fn legacy(key: &'static str) -> Field {
    Field {
        value_type: FieldType::LegacyValue,
        key,
        title: "",
        required: false,
    }
}
const fn nullable(key: &'static str) -> Field {
    Field {
        value_type: FieldType::NullableText,
        key,
        title: "",
        required: false,
    }
}
const fn required_text(key: &'static str) -> Field {
    Field {
        value_type: FieldType::Text,
        key,
        title: "",
        required: true,
    }
}
const ANSWER_WRITE_FIELDS: &[Field] = &[
    COURSE_ID,
    nullable("study_session_id"),
    required_text("idempotency_key"),
    legacy("answers"),
    legacy("source"),
];

const ANSWER_SINGLE_FIELDS: &[Field] = &[
    nullable("exercise_id"),
    nullable("submission_id"),
    nullable("idempotency_key"),
    nullable("task_id"),
    legacy("expected_version"),
    legacy("answer_text"),
    nullable("source"),
];
const FOLLOWUP_FIELDS: &[Field] = &[
    required_text("parent_submission_id"),
    legacy("answer_text"),
    nullable("idempotency_key"),
    nullable("source"),
];
const BRANCH_FIELDS: &[Field] = &[
    Field {
        title: "Parent Submission Id",
        ..required_text("parent_submission_id")
    },
    Field {
        title: "Child Submission Id",
        ..required_text("child_submission_id")
    },
    Field {
        value_type: FieldType::BoundedText { max: 10000 },
        title: "Reason",
        ..required_text("reason")
    },
];
const EVIDENCE_FIELDS: &[Field] = &[
    PLAN_ID,
    Field {
        title: "Course Id",
        ..nullable("course_id")
    },
    Field {
        value_type: FieldType::NullableChoice(&["general", "english"]),
        title: "Learning Mode",
        ..legacy("learning_mode")
    },
    Field {
        value_type: FieldType::BoundedCount {
            max: 100,
            default: 20,
        },
        title: "Limit",
        ..legacy("limit")
    },
    Field {
        title: "Cursor",
        ..nullable("cursor")
    },
];

const PRACTICE_STUDY: Field = Field {
    value_type: FieldType::BoundedText { max: 80 },
    ..STUDY_SESSION_ID
};
const PRACTICE_FIELDS: &[Field] = &[PRACTICE_STUDY, PRACTICE_EXERCISE];
const PRACTICE_WRITE_FIELDS: &[Field] = &[
    PRACTICE_STUDY,
    PRACTICE_EXERCISE,
    Field {
        required: true,
        ..PREVIEW_ANSWERS
    },
    Field {
        key: "position",
        title: "Position",
        required: true,
        value_type: FieldType::IntegerBounds {
            min: 0,
            max: Some(19),
        },
    },
    Field {
        key: "expected_version",
        title: "Expected Version",
        required: true,
        value_type: FieldType::IntegerBounds { min: 0, max: None },
    },
    Field {
        key: "idempotency_key",
        title: "Idempotency Key",
        required: true,
        value_type: FieldType::TrimmedKey,
    },
];
const ESSAY_FIELDS: &[Field] = &[
    Field {
        value_type: FieldType::BoundedText { max: 80 },
        ..COURSE_ID
    },
    PRACTICE_STUDY,
    Field {
        key: "answers",
        title: "Answers",
        required: true,
        value_type: FieldType::EssayAnswers,
    },
    Field {
        key: "idempotency_key",
        title: "Idempotency Key",
        required: true,
        value_type: FieldType::BoundedText { max: 160 },
    },
    Field {
        key: "source",
        title: "Source",
        required: false,
        value_type: FieldType::BoundedSource,
    },
];

fn essay_answers_valid(answers: &Value) -> bool {
    answers.as_array().is_some_and(|rows| {
        rows.len() == 1
            && rows[0]["exercise_id"]
                .as_str()
                .is_some_and(|id| (1..=80).contains(&id.chars().count()))
            && rows[0]["answer_text"]
                .as_str()
                .is_some_and(|text| text.chars().count() <= 100000)
    })
}

fn essay_answer_schema() -> Value {
    let optional =
        |title| json!({"title":title,"default":null,"anyOf":[{"type":"string"},{"type":"null"}]});
    json!({"title":"EssayAnswer","type":"object","additionalProperties":false,"required":["exercise_id","answer_text"],"properties":{
        "exercise_id":{"title":"Exercise Id","type":"string","minLength":1,"maxLength":80},
        "answer_text":{"title":"Answer Text","type":"string","maxLength":100000},
        "expected_version":{"title":"Expected Version","default":null,"anyOf":[{"type":"integer","minimum":1},{"type":"null"}]},
        "submission_id":optional("Submission Id"),"parent_submission_id":optional("Parent Submission Id"),"retest_task_id":optional("Retest Task Id"),"task_id":optional("Task Id")}})
}

const ENGLISH_KEY: Field = Field {
    key: "idempotency_key",
    title: "Idempotency Key",
    required: true,
    value_type: FieldType::BoundedText { max: 160 },
};
const VERSION_ZERO: Field = Field {
    key: "expected_version",
    title: "Expected Version",
    required: true,
    value_type: FieldType::IntegerBounds { min: 0, max: None },
};
const VERSION_ONE: Field = Field {
    value_type: FieldType::IntegerBounds { min: 1, max: None },
    ..VERSION_ZERO
};
const ANSWER_TEXT: Field = Field {
    key: "answer_text",
    title: "Answer Text",
    required: true,
    value_type: FieldType::TextMax { max: 100000 },
};
const RETEST_TEXT: Field = Field {
    value_type: FieldType::TextMax { max: 4000 },
    ..ANSWER_TEXT
};
const RETEST_TASK_ID: Field = Field {
    title: "Task Id",
    ..required_text("task_id")
};
const ENGLISH_ITEM: &[Field] = &[STUDY_SESSION_ID, EXERCISE_ID];
const ENGLISH_SAVE: &[Field] = &[
    STUDY_SESSION_ID,
    EXERCISE_ID,
    ANSWER_TEXT,
    VERSION_ZERO,
    ENGLISH_KEY,
    Field {
        key: "skipped",
        title: "Skipped",
        required: false,
        value_type: FieldType::BooleanDefaultFalse,
    },
];
const ENGLISH_CHECK: &[Field] = &[STUDY_SESSION_ID, EXERCISE_ID, VERSION_ONE, ENGLISH_KEY];
const ENGLISH_SUBMIT: &[Field] = &[
    STUDY_SESSION_ID,
    ENGLISH_KEY,
    Field {
        key: "expected_versions",
        title: "Expected Versions",
        required: true,
        value_type: FieldType::VersionMap,
    },
];
const ENGLISH_NAVIGATE: &[Field] = &[
    STUDY_SESSION_ID,
    Field {
        key: "position",
        title: "Position",
        required: true,
        value_type: FieldType::IntegerBounds {
            min: 0,
            max: Some(499),
        },
    },
    VERSION_ZERO,
    ENGLISH_KEY,
];
const ENGLISH_RETEST_SAVE: &[Field] = &[RETEST_TASK_ID, RETEST_TEXT, VERSION_ZERO, ENGLISH_KEY];
const ENGLISH_RETEST_CHECK: &[Field] = &[
    RETEST_TASK_ID,
    Field {
        value_type: FieldType::BoundedText { max: 4000 },
        ..RETEST_TEXT
    },
    ENGLISH_KEY,
    VERSION_ZERO,
];

const RESET_IN_PLACE: Field = Field {
    key: "reset_current_state",
    title: "Reset Current State",
    required: false,
    value_type: FieldType::BooleanDefaultFalse,
};
const RESET_CONTENT_HASH: Field = Field {
    key: "expected_content_hash",
    title: "Expected Content Hash",
    required: true,
    value_type: FieldType::Digest,
};
const RESET_STATE_HASH: Field = Field {
    key: "expected_state_hash",
    title: "Expected State Hash",
    required: true,
    value_type: FieldType::Digest,
};
const RESET_CONFIRM: Field = Field {
    key: "confirm",
    title: "Confirm",
    required: false,
    value_type: FieldType::BooleanDefaultFalse,
};
const RESET_TRAINING_VERSION: Field = Field {
    key: "expected_training_version",
    title: "Expected Training Version",
    required: false,
    value_type: FieldType::NullableNonnegativeInteger,
};

const COURSE_REVISION: Field = Field {
    value_type: FieldType::PositiveInteger,
    key: "expected_revision",
    title: "Expected Revision",
    required: true,
};
const PREVIEW_HASH: Field = Field {
    value_type: FieldType::Digest,
    key: "preview_hash",
    title: "Preview Hash",
    required: true,
};
const REQUEST_KEY: Field = Field {
    value_type: FieldType::BoundedText { max: 160 },
    key: "idempotency_key",
    title: "Idempotency Key",
    required: true,
};
const SOURCE_LESSON_ID: Field = Field {
    value_type: FieldType::Text,
    ..LESSON_ID
};
const BLOCK_ID: Field = Field {
    value_type: FieldType::NullableText,
    key: "block_id",
    title: "Block Id",
    required: false,
};
const SECTION_ID: Field = Field {
    value_type: FieldType::NullableText,
    key: "section_id",
    title: "Section Id",
    required: false,
};
const REFERENCE_FIELDS: &[Field] = &[
    Field {
        value_type: FieldType::NullableText,
        required: false,
        ..STUDY_SESSION_ID
    },
    Field {
        value_type: FieldType::NullableText,
        required: false,
        ..EXERCISE_ID
    },
    Field {
        value_type: FieldType::NullableText,
        key: "submission_id",
        title: "Submission Id",
        required: false,
    },
    Field {
        value_type: FieldType::NullablePositiveInteger,
        key: "reference_revision",
        title: "Reference Revision",
        required: false,
    },
];

const METHODS: &[Method] = &[
    Method {
        name: "speech_job_preview",
        method: "speech.job.preview",
        kind: Kind::Read,
        fields: &[legacy("job_id")],
        schema_title: None,
        handle: speech::preview_job,
    },
    Method {
        name: "speech_asset_adopt",
        method: "speech.asset.adopt",
        kind: Kind::Write,
        fields: &[legacy("job_id")],
        schema_title: None,
        handle: speech::adopt_asset,
    },
    Method {
        name: "speech_job_start",
        method: "speech.job.start",
        kind: Kind::Write,
        fields: &[
            legacy("job_id"),
            legacy("profile_id"),
            legacy("retry"),
            legacy("segments"),
            legacy("expected_profile_version"),
            legacy("text"),
            legacy("instruction"),
        ],
        schema_title: None,
        handle: speech::start_job,
    },
    Method {
        name: "speech_job_get",
        method: "speech.job.get",
        kind: Kind::Write,
        fields: &[legacy("job_id")],
        schema_title: None,
        handle: speech::get_job,
    },
    Method {
        name: "speech_profile_get",
        method: "speech.profile.get",
        kind: Kind::Read,
        fields: &[legacy("profile_id")],
        schema_title: None,
        handle: speech::get_profile,
    },
    Method {
        name: "speech_profile_list",
        method: "speech.profile.list",
        kind: Kind::Read,
        fields: &[],
        schema_title: None,
        handle: speech::list_profiles,
    },
    Method {
        name: "speech_profile_save",
        method: "speech.profile.save",
        kind: Kind::Write,
        fields: &[
            legacy("profile_id"),
            legacy("name"),
            legacy("provider"),
            legacy("endpoint"),
            legacy("model"),
            legacy("voice"),
            legacy("format"),
            legacy("credential"),
            legacy("clear_credential"),
            legacy("expected_version"),
        ],
        schema_title: None,
        handle: speech::save_profile,
    },
    Method {
        name: "course_list",
        method: "course.list",
        kind: Kind::Read,
        fields: &[OPTIONAL_PLAN_ID],
        schema_title: None,
        handle: course::list_engine,
    },
    Method {
        name: "course_learning_reset_preview",
        method: "course.learning.reset.preview",
        kind: Kind::Read,
        fields: &[COURSE_ID],
        schema_title: Some("LearningResetPreviewRequest"),
        handle: learning::reset_preview,
    },
    Method {
        name: "course_learning_reset_apply",
        method: "course.learning.reset.apply",
        kind: Kind::Write,
        fields: &[
            COURSE_ID,
            RESET_STATE_HASH,
            RESET_CONTENT_HASH,
            REQUEST_KEY,
            RESET_CONFIRM,
        ],
        schema_title: Some("LearningResetApplyRequest"),
        handle: learning::reset,
    },
    Method {
        name: "course_study_restart_preview",
        method: "course.study.restart.preview",
        kind: Kind::Read,
        fields: &[STUDY_SESSION_ID, RESET_IN_PLACE],
        schema_title: Some("RestartPreviewRequest"),
        handle: learning::restart_preview,
    },
    Method {
        name: "course_study_restart",
        method: "course.study.restart",
        kind: Kind::Write,
        fields: &[
            STUDY_SESSION_ID,
            RESET_IN_PLACE,
            Field {
                value_type: FieldType::NullableDigest,
                required: false,
                ..RESET_STATE_HASH
            },
            RESET_TRAINING_VERSION,
            VERSION_ONE,
            RESET_CONTENT_HASH,
            REQUEST_KEY,
        ],
        schema_title: Some("RestartRequest"),
        handle: learning::restart,
    },
    Method {
        name: "course_study_open",
        method: "course.study.open",
        kind: Kind::Write,
        fields: &[
            COURSE_ID,
            required_text("idempotency_key"),
            nullable("plan_line_id"),
            Field {
                value_type: FieldType::Boolean,
                ..legacy("new_version")
            },
            Field {
                value_type: FieldType::Boolean,
                ..legacy("review_round")
            },
        ],
        schema_title: None,
        handle: learning::open,
    },
    Method {
        name: "course_study_get",
        method: "course.study.get",
        kind: Kind::Read,
        fields: &[STUDY_SESSION_ID],
        schema_title: None,
        handle: learning::detail,
    },
    Method {
        name: "course_study_progress_save",
        method: "course.study.progress.save",
        kind: Kind::Write,
        fields: &[
            STUDY_SESSION_ID,
            required_text("lesson_id"),
            legacy("progress_percent"),
            legacy("last_position"),
            legacy("expected_version"),
        ],
        schema_title: None,
        handle: learning::save_progress,
    },
    Method {
        name: "course_study_reading_complete",
        method: "course.study.reading.complete",
        kind: Kind::Write,
        fields: &[STUDY_SESSION_ID],
        schema_title: None,
        handle: learning::complete_reading,
    },
    Method {
        name: "course_answers_get",
        method: "course.answers.get",
        kind: Kind::Read,
        fields: &[COURSE_ID, nullable("study_session_id")],
        schema_title: None,
        handle: learning::answers,
    },
    Method {
        name: "course_answers_draft_save",
        method: "course.answers.draft.save",
        kind: Kind::Write,
        fields: ANSWER_WRITE_FIELDS,
        schema_title: None,
        handle: learning::save_answers,
    },
    Method {
        name: "course_answers_submit",
        method: "course.answers.submit",
        kind: Kind::Write,
        fields: ANSWER_WRITE_FIELDS,
        schema_title: None,
        handle: learning::submit_answers,
    },
    Method {
        name: "submission_get",
        method: "submission.get",
        kind: Kind::Read,
        fields: &[required_text("submission_id")],
        schema_title: None,
        handle: learning::submission,
    },
    Method {
        name: "submission_draft_save",
        method: "submission.draft.save",
        kind: Kind::Write,
        fields: ANSWER_SINGLE_FIELDS,
        schema_title: None,
        handle: learning::save_single,
    },
    Method {
        name: "submission_submit",
        method: "submission.submit",
        kind: Kind::Write,
        fields: ANSWER_SINGLE_FIELDS,
        schema_title: None,
        handle: learning::submit_single,
    },
    Method {
        name: "learning_progress_save",
        method: "learning.progress.save",
        kind: Kind::Write,
        fields: &[
            COURSE_ID,
            required_text("lesson_id"),
            legacy("progress_percent"),
            nullable("last_position"),
            nullable("source"),
        ],
        schema_title: None,
        handle: learning::save_legacy_progress,
    },
    Method {
        name: "submission_revise",
        method: "submission.revise",
        kind: Kind::Write,
        fields: FOLLOWUP_FIELDS,
        schema_title: None,
        handle: learning::revise,
    },
    Method {
        name: "submission_retest",
        method: "submission.retest",
        kind: Kind::Write,
        fields: FOLLOWUP_FIELDS,
        schema_title: None,
        handle: learning::retest,
    },
    Method {
        name: "submission_resolve-branch",
        method: "submission.resolve-branch",
        kind: Kind::Write,
        fields: BRANCH_FIELDS,
        schema_title: Some("BranchRequest"),
        handle: learning::resolve_branch,
    },
    Method {
        name: "learning_evidence",
        method: "learning.evidence",
        kind: Kind::Read,
        fields: EVIDENCE_FIELDS,
        schema_title: Some("EvidenceRequest"),
        handle: learning::evidence,
    },
    Method {
        name: "practice_reading_get",
        method: "practice.reading.get",
        kind: Kind::Read,
        fields: PRACTICE_FIELDS,
        schema_title: Some("PracticeRequest"),
        handle: |params| practice::read_group(params, GroupKind::Reading),
    },
    Method {
        name: "practice_reading_save",
        method: "practice.reading.save",
        kind: Kind::Write,
        fields: PRACTICE_WRITE_FIELDS,
        schema_title: Some("PracticeWriteRequest"),
        handle: |params| practice::write_group(params, GroupKind::Reading, false),
    },
    Method {
        name: "practice_reading_confirm",
        method: "practice.reading.confirm",
        kind: Kind::Write,
        fields: PRACTICE_WRITE_FIELDS,
        schema_title: Some("PracticeWriteRequest"),
        handle: |params| practice::write_group(params, GroupKind::Reading, true),
    },
    Method {
        name: "practice_listening_get",
        method: "practice.listening.get",
        kind: Kind::Read,
        fields: PRACTICE_FIELDS,
        schema_title: Some("PracticeRequest"),
        handle: |params| practice::read_group(params, GroupKind::Listening),
    },
    Method {
        name: "practice_listening_save",
        method: "practice.listening.save",
        kind: Kind::Write,
        fields: PRACTICE_WRITE_FIELDS,
        schema_title: Some("PracticeWriteRequest"),
        handle: |params| practice::write_group(params, GroupKind::Listening, false),
    },
    Method {
        name: "practice_listening_confirm",
        method: "practice.listening.confirm",
        kind: Kind::Write,
        fields: PRACTICE_WRITE_FIELDS,
        schema_title: Some("PracticeWriteRequest"),
        handle: |params| practice::write_group(params, GroupKind::Listening, true),
    },
    Method {
        name: "practice_listening_audio",
        method: "practice.listening.audio",
        kind: Kind::Read,
        fields: PRACTICE_FIELDS,
        schema_title: Some("PracticeRequest"),
        handle: |params| practice::asset(params, false),
    },
    Method {
        name: "practice_listening_captions",
        method: "practice.listening.captions",
        kind: Kind::Read,
        fields: PRACTICE_FIELDS,
        schema_title: Some("PracticeRequest"),
        handle: |params| practice::asset(params, true),
    },
    Method {
        name: "practice_essay_submit",
        method: "practice.essay.submit",
        kind: Kind::Write,
        fields: ESSAY_FIELDS,
        schema_title: Some("EssayRequest"),
        handle: practice::essay,
    },
    Method {
        name: "course_english_get",
        method: "course.english.get",
        kind: Kind::Read,
        fields: &[STUDY_SESSION_ID],
        schema_title: Some("EnglishStudyRequest"),
        handle: |params| english::read(params, "get"),
    },
    Method {
        name: "course_english_save",
        method: "course.english.save",
        kind: Kind::Write,
        fields: ENGLISH_SAVE,
        schema_title: Some("EnglishSaveRequest"),
        handle: |params| english::write(params, "save"),
    },
    Method {
        name: "course_english_check",
        method: "course.english.check",
        kind: Kind::Write,
        fields: ENGLISH_CHECK,
        schema_title: Some("EnglishCheckRequest"),
        handle: |params| english::write(params, "check"),
    },
    Method {
        name: "course_english_reveal",
        method: "course.english.reveal",
        kind: Kind::Write,
        fields: &[STUDY_SESSION_ID, EXERCISE_ID, ENGLISH_KEY],
        schema_title: Some("EnglishRevealRequest"),
        handle: |params| english::write(params, "reveal"),
    },
    Method {
        name: "course_english_answer",
        method: "course.english.answer",
        kind: Kind::Read,
        fields: ENGLISH_ITEM,
        schema_title: Some("EnglishItemRequest"),
        handle: |params| english::read(params, "answer"),
    },
    Method {
        name: "course_english_submit",
        method: "course.english.submit",
        kind: Kind::Write,
        fields: ENGLISH_SUBMIT,
        schema_title: Some("EnglishSubmitRequest"),
        handle: |params| english::write(params, "submit"),
    },
    Method {
        name: "course_english_navigate",
        method: "course.english.navigate",
        kind: Kind::Write,
        fields: ENGLISH_NAVIGATE,
        schema_title: Some("EnglishMoveRequest"),
        handle: |params| english::write(params, "navigate"),
    },
    Method {
        name: "course_english_request_review",
        method: "course.english.request-review",
        kind: Kind::Write,
        fields: ENGLISH_CHECK,
        schema_title: Some("EnglishCheckRequest"),
        handle: |params| english::write(params, "request-review"),
    },
    Method {
        name: "course_english_retest_get",
        method: "course.english.retest-get",
        kind: Kind::Read,
        fields: &[RETEST_TASK_ID],
        schema_title: Some("RetestGetRequest"),
        handle: |params| english::read(params, "retest-get"),
    },
    Method {
        name: "course_english_retest_save",
        method: "course.english.retest-save",
        kind: Kind::Write,
        fields: ENGLISH_RETEST_SAVE,
        schema_title: Some("RetestSaveRequest"),
        handle: |params| english::write(params, "retest-save"),
    },
    Method {
        name: "course_english_retest_check",
        method: "course.english.retest-check",
        kind: Kind::Write,
        fields: ENGLISH_RETEST_CHECK,
        schema_title: Some("RetestCheckRequest"),
        handle: |params| english::write(params, "retest-check"),
    },
    Method {
        name: "course_detail",
        method: "course.detail",
        kind: Kind::Read,
        fields: &[COURSE_ID],
        schema_title: None,
        handle: course::detail_engine,
    },
    Method {
        name: "course_update_preview",
        method: "course.update.preview",
        kind: Kind::Read,
        fields: &[COURSE_ID, PATH, COURSE_REVISION],
        schema_title: Some("UpdatePreviewRequest"),
        handle: course::preview_engine,
    },
    Method {
        name: "course_update_apply",
        method: "course.update.apply",
        kind: Kind::Write,
        fields: &[COURSE_ID, PATH, COURSE_REVISION, PREVIEW_HASH, REQUEST_KEY],
        schema_title: Some("UpdateApplyRequest"),
        handle: course::apply_engine,
    },
    Method {
        name: "mistakes_notebooks",
        method: "mistakes.notebooks",
        kind: Kind::Read,
        fields: &[],
        schema_title: None,
        handle: review::notebooks,
    },
    Method {
        name: "mistakes_summary",
        method: "mistakes.summary",
        kind: Kind::Read,
        fields: &[
            nullable("notebook_id"),
            nullable("plan_line_id"),
            nullable("domain"),
            nullable("course_id"),
            legacy("archived"),
            nullable("objective_id"),
            nullable("since"),
            nullable("until"),
            legacy("view"),
        ],
        schema_title: None,
        handle: review::mistake_summary,
    },
    Method {
        name: "mistakes_list",
        method: "mistakes.list",
        kind: Kind::Read,
        fields: &[
            nullable("notebook_id"),
            nullable("plan_line_id"),
            nullable("domain"),
            nullable("course_id"),
            legacy("archived"),
            nullable("objective_id"),
            nullable("since"),
            nullable("until"),
            legacy("view"),
            legacy("limit"),
            nullable("cursor"),
        ],
        schema_title: None,
        handle: review::mistake_list,
    },
    Method {
        name: "mistakes_context",
        method: "mistakes.context",
        kind: Kind::Read,
        fields: &[
            nullable("notebook_id"),
            nullable("plan_line_id"),
            nullable("domain"),
            nullable("course_id"),
            legacy("archived"),
            nullable("objective_id"),
            nullable("since"),
            nullable("until"),
            legacy("view"),
            legacy("limit"),
            nullable("cursor"),
            required_text("identifier"),
            legacy("expected_version"),
        ],
        schema_title: None,
        handle: review::mistake_context,
    },
    Method {
        name: "mistakes_english_review_select",
        method: "mistakes.english.review.select",
        kind: Kind::Write,
        fields: &[
            nullable("notebook_id"),
            nullable("plan_line_id"),
            nullable("domain"),
            nullable("course_id"),
            legacy("archived"),
            nullable("objective_id"),
            nullable("since"),
            nullable("until"),
            legacy("view"),
            required_text("identifier"),
            legacy("expected_version"),
            required_text("idempotency_key"),
        ],
        schema_title: None,
        handle: review::mistake_review,
    },
    Method {
        name: "mistakes_retest_request",
        method: "mistakes.retest.request",
        kind: Kind::Write,
        fields: &[
            nullable("notebook_id"),
            nullable("plan_line_id"),
            nullable("domain"),
            nullable("course_id"),
            legacy("archived"),
            nullable("objective_id"),
            nullable("since"),
            nullable("until"),
            legacy("view"),
            required_text("identifier"),
            legacy("expected_version"),
            required_text("idempotency_key"),
        ],
        schema_title: None,
        handle: review::mistake_retest,
    },
    Method {
        name: "mistakes_archive_preview",
        method: "mistakes.archive.preview",
        kind: Kind::Read,
        fields: &[
            nullable("notebook_id"),
            nullable("plan_line_id"),
            nullable("domain"),
            nullable("course_id"),
            legacy("archived"),
            nullable("objective_id"),
            nullable("since"),
            nullable("until"),
            legacy("view"),
        ],
        schema_title: None,
        handle: review::archive_preview,
    },
    Method {
        name: "mistakes_archive_apply",
        method: "mistakes.archive.apply",
        kind: Kind::Write,
        fields: &[
            nullable("notebook_id"),
            nullable("plan_line_id"),
            nullable("domain"),
            nullable("course_id"),
            legacy("archived"),
            nullable("objective_id"),
            nullable("since"),
            nullable("until"),
            legacy("view"),
            required_text("preview_hash"),
            required_text("idempotency_key"),
        ],
        schema_title: None,
        handle: review::archive_apply,
    },
    Method {
        name: "course_remediation_preview",
        method: "course.remediation.preview",
        kind: Kind::Read,
        fields: &[
            PLAN_ID,
            PATH,
            legacy("objective_ids"),
            required_text("rationale"),
            legacy("sources"),
        ],
        schema_title: None,
        handle: review::remediation_preview,
    },
    Method {
        name: "course_remediation_publish",
        method: "course.remediation.publish",
        kind: Kind::Write,
        fields: &[
            PLAN_ID,
            PATH,
            legacy("objective_ids"),
            required_text("rationale"),
            legacy("sources"),
            required_text("preview_hash"),
            required_text("idempotency_key"),
        ],
        schema_title: None,
        handle: review::remediation_publish,
    },
    Method {
        name: "course_remediation_list",
        method: "course.remediation.list",
        kind: Kind::Read,
        fields: &[
            PLAN_ID,
            nullable("source_course_id"),
            nullable("aggregate_id"),
            legacy("limit"),
            legacy("offset"),
        ],
        schema_title: None,
        handle: review::remediation_list,
    },
    Method {
        name: "course_remediation_get",
        method: "course.remediation.get",
        kind: Kind::Read,
        fields: &[COURSE_ID],
        schema_title: None,
        handle: review::remediation_get,
    },
    Method {
        name: "assignment_queue",
        method: "assignment.queue",
        kind: Kind::Read,
        fields: &[OPTIONAL_PLAN_ID],
        schema_title: None,
        handle: review::queue,
    },
    Method {
        name: "assignment_summary",
        method: "assignment.summary",
        kind: Kind::Read,
        fields: &[
            nullable("plan_line_id"),
            nullable("course_id"),
            nullable("status"),
            nullable("cursor"),
            legacy("role"),
            legacy("limit"),
            legacy("history"),
        ],
        schema_title: None,
        handle: review::summary,
    },
    Method {
        name: "assignment_context",
        method: "assignment.context",
        kind: Kind::Read,
        fields: &[legacy("submission_ids")],
        schema_title: None,
        handle: review::context,
    },
    Method {
        name: "review_write",
        method: "review.write",
        kind: Kind::Write,
        fields: &[
            required_text("submission_id"),
            required_text("summary"),
            legacy("detail_markdown"),
            legacy("issue_count"),
            legacy("needs_revision"),
            nullable("idempotency_key"),
            legacy("source"),
            nullable("decision"),
            legacy("next_action"),
            legacy("issues"),
            nullable("reference_hash"),
            legacy("reference_revision"),
            legacy("reference_reason"),
        ],
        schema_title: None,
        handle: review::write,
    },
    Method {
        name: "retest_publish",
        method: "review.retest.publish",
        kind: Kind::Write,
        fields: &[
            required_text("parent_submission_id"),
            required_text("title"),
            required_text("prompt"),
            required_text("objective"),
            legacy("requirements"),
            legacy("agent_reference"),
            required_text("idempotency_key"),
        ],
        schema_title: None,
        handle: review::publish,
    },
    Method {
        name: "plan_notebook_get",
        method: "plan.notebook.get",
        kind: Kind::Read,
        fields: &[required_text("plan_line_id")],
        schema_title: None,
        handle: notebook::get,
    },
    Method {
        name: "plan_notebook_save",
        method: "plan.notebook.save",
        kind: Kind::Write,
        fields: &[
            required_text("plan_line_id"),
            legacy("blocks"),
            legacy("expected_version"),
            legacy("idempotency_key"),
        ],
        schema_title: None,
        handle: notebook::save,
    },
    Method {
        name: "course_notes_get",
        method: "course.notes.get",
        kind: Kind::Read,
        fields: &[STUDY_SESSION_ID],
        schema_title: None,
        handle: notebook::notes,
    },
    Method {
        name: "course_notes_save",
        method: "course.notes.save",
        kind: Kind::Write,
        fields: &[
            STUDY_SESSION_ID,
            required_text("lesson_id"),
            legacy("text"),
            legacy("expected_version"),
            legacy("idempotency_key"),
        ],
        schema_title: None,
        handle: notebook::save_note,
    },
    Method {
        name: "plan_notebook_read",
        method: "plan.notebook.read",
        kind: Kind::Read,
        fields: &[
            PLAN_ID,
            nullable("course_id"),
            nullable("lesson_id"),
            legacy("entry_ids"),
            legacy("query"),
            legacy("offset"),
            legacy("limit"),
            legacy("expected_version"),
        ],
        schema_title: None,
        handle: notebook::read,
    },
    Method {
        name: "plan_notebook_apply",
        method: "plan.notebook.apply",
        kind: Kind::Write,
        fields: &[
            PLAN_ID,
            legacy("expected_version"),
            legacy("idempotency_key"),
            legacy("operations"),
            legacy("new_sources"),
        ],
        schema_title: None,
        handle: notebook::apply,
    },
    Method {
        name: "plan_notebook_search",
        method: "plan.notebook.search",
        kind: Kind::Read,
        fields: &[
            PLAN_ID,
            nullable("course_id"),
            nullable("lesson_id"),
            legacy("query"),
        ],
        schema_title: None,
        handle: notebook::search,
    },
    Method {
        name: "plan_notebook_export",
        method: "plan.notebook.export",
        kind: Kind::Read,
        fields: &[PLAN_ID],
        schema_title: Some("PlanRequest"),
        handle: notebook::export,
    },
    Method {
        name: "course_source_read",
        method: "course.source.read",
        kind: Kind::Read,
        fields: &[STUDY_SESSION_ID, SOURCE_LESSON_ID, BLOCK_ID, SECTION_ID],
        schema_title: Some("SourceRequest"),
        handle: course::source_engine,
    },
    Method {
        name: "exercise_reference_read",
        method: "exercise.reference.read",
        kind: Kind::Read,
        fields: REFERENCE_FIELDS,
        schema_title: Some("ReferenceRequest"),
        handle: course::reference_read,
    },
    Method {
        name: "exercise_reference_view",
        method: "exercise.reference.view",
        kind: Kind::Write,
        fields: REFERENCE_FIELDS,
        schema_title: Some("ReferenceRequest"),
        handle: course::reference_view,
    },
    Method {
        name: "course_import",
        method: "course.import",
        kind: Kind::Write,
        fields: &[IMPORT_PATH, FILE],
        schema_title: None,
        handle: course::import_engine,
    },
    Method {
        name: "system_changes",
        method: "system.changes",
        kind: Kind::Read,
        fields: &[],
        schema_title: None,
        handle: planning::changes,
    },
    Method {
        name: "plan_list",
        method: "plan.list",
        kind: Kind::Read,
        fields: &[INCLUDE_INACTIVE],
        schema_title: None,
        handle: planning::list,
    },
    Method {
        name: "plan_detail",
        method: "plan.detail",
        kind: Kind::Read,
        fields: &[PLAN_ID, DATE],
        schema_title: None,
        handle: planning::detail,
    },
    Method {
        name: "plan_edit",
        method: "plan.edit",
        kind: Kind::Write,
        fields: PLAN_EDIT_FIELDS,
        schema_title: Some("PlanEditRequest"),
        handle: planning::edit,
    },
    Method {
        name: "plan_schedule_list",
        method: "plan.schedule.list",
        kind: Kind::Read,
        fields: &[PLAN_ID],
        schema_title: Some("PlanRequest"),
        handle: planning::schedules,
    },
    Method {
        name: "today",
        method: "study.today",
        kind: Kind::Read,
        fields: &[DATE, OPTIONAL_PLAN_ID, TASK_KIND],
        schema_title: None,
        handle: planning::today,
    },
    Method {
        name: "snapshot_generate",
        method: "snapshot.generate",
        kind: Kind::Write,
        fields: &[DATE, SCOPE],
        schema_title: None,
        handle: planning::snapshot,
    },
    Method {
        name: "practice_author_preview",
        method: "practice.author.preview",
        kind: Kind::Read,
        fields: &[
            PACKAGE,
            LESSON_ID,
            PRACTICE_EXERCISE,
            PREVIEW_ANSWERS,
            PREVIEW_AUDIO,
            PREVIEW_CAPTIONS,
        ],
        schema_title: Some("PreviewRequest"),
        handle: author::preview,
    },
    Method {
        name: "audio_dictionary_lookup",
        method: "audio.dictionary.lookup",
        kind: Kind::Read,
        fields: &[STUDY_SESSION_ID, EXERCISE_ID, WORD_INDEX, ACCENT],
        schema_title: Some("DictionaryRequest"),
        handle: dictionary_lookup,
    },
    Method {
        name: "audio_dictionary_metadata",
        method: "audio.dictionary.metadata",
        kind: Kind::Read,
        fields: &[STUDY_SESSION_ID, EXERCISE_ID, ACCENT],
        schema_title: Some("EnglishMetadataRequest"),
        handle: dictionary_metadata,
    },
    Method {
        name: "document_read",
        method: "document.read",
        kind: Kind::Read,
        fields: &[PATH, RENDER],
        schema_title: None,
        handle: document_read,
    },
    Method {
        name: "version",
        method: "system.version",
        kind: Kind::Read,
        fields: &[],
        schema_title: None,
        handle: version,
    },
    Method {
        name: "capabilities",
        method: "system.capabilities",
        kind: Kind::Read,
        fields: &[],
        schema_title: None,
        handle: capabilities,
    },
    Method {
        name: "system_schema",
        method: "system.schema",
        kind: Kind::Read,
        fields: &[METHOD],
        schema_title: None,
        handle: schema,
    },
    Method {
        name: "doctor",
        method: "system.doctor",
        kind: Kind::Diagnostic,
        fields: &[],
        schema_title: None,
        handle: doctor,
    },
    Method {
        name: "system_installation",
        method: "system.installation",
        kind: Kind::Read,
        fields: &[],
        schema_title: None,
        handle: installation,
    },
    Method {
        name: "workspace_export",
        method: "workspace.export",
        kind: Kind::Write,
        fields: &[PATH],
        schema_title: Some("BackupRequest"),
        handle: workspace_export,
    },
    Method {
        name: "workspace_validate",
        method: "workspace.validate",
        kind: Kind::Read,
        fields: &[PATH],
        schema_title: Some("BackupRequest"),
        handle: workspace_validate,
    },
    Method {
        name: "workspace_restore",
        method: "workspace.restore",
        kind: Kind::Write,
        fields: &[PATH, TARGET],
        schema_title: Some("RestoreRequest"),
        handle: workspace_restore,
    },
];

fn discovery() -> Result<Value, ApiError> {
    let settings = Settings::from_env()?;
    Ok(json!({
        "protocol_version": PROTOCOL_VERSION,
        "app_version": APP_VERSION,
        "runtime": "rust",
        "workspace": {"root":settings.workspace,"exists":settings.workspace.is_dir()},
        "database": {"driver":"sqlite","managed_by_app":true,"status":"engine_managed"},
        "next_action": "读取 system.capabilities 或 system.schema，选择当前可用的方法。",
    }))
}

fn version(_: &Params) -> Result<Value, ApiError> {
    let mut base = discovery()?;
    base["capabilities"] = json!(METHODS.iter().map(|item| item.name).collect::<Vec<_>>());
    Ok(base)
}

fn content_capabilities() -> Value {
    let mut result = packages::capabilities();
    result["speech_generation"] = json!({"providers":["step_plan","compatible"],"provider_defaults":studyflow_core::speech_generation::profiles::provider_defaults(),"audio_formats":["mp3","wav"],"segmented_format":"wav","max_segments":10,"segmented_captions":true});
    result["notebook"] = json!({"formats":[1,2],"write_method":"plan.notebook.apply","read_method":"plan.notebook.read","read_limit":100,"max_entries":1000,"immutable_sources":true,"legacy_write_v2":false});
    result["learning_evidence"] =
        json!({"method":"learning.evidence","max_limit":100,"infers_mastery":false});
    result
}

fn capabilities(_: &Params) -> Result<Value, ApiError> {
    let mut base = discovery()?;
    base["capabilities"] = json!(METHODS.iter().map(Method::capability).collect::<Vec<_>>());
    base["content"] = content_capabilities();
    Ok(base)
}

fn schema(params: &Params) -> Result<Value, ApiError> {
    let selected = params
        .get("method")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty());
    let methods: Params = METHODS
        .iter()
        .filter(|item| selected.is_none_or(|name| name == item.method))
        .filter_map(|entry| {
            entry
                .schema()
                .map(|schema| (entry.method.to_owned(), schema))
        })
        .collect();
    if let Some(name) = selected.filter(|_| methods.is_empty()) {
        return Err(ApiError::missing_method(name));
    }
    Ok(json!({"schema_version":SCHEMA_VERSION,"content":content_capabilities(),"methods":methods}))
}

fn doctor(_: &Params) -> Result<Value, ApiError> {
    let mut result = studyflow_core::infrastructure::health::inspect(&Settings::from_env()?);
    result["protocol_version"] = json!(PROTOCOL_VERSION);
    result["capabilities"] = json!(METHODS.iter().map(|item| item.name).collect::<Vec<_>>());
    Ok(result)
}

fn installation(_: &Params) -> Result<Value, ApiError> {
    let settings = Settings::from_env()?;
    Ok(json!(installation::discover(&settings.workspace)?))
}

fn path(params: &Params, key: &str) -> Result<std::path::PathBuf, ApiError> {
    params
        .get(key)
        .and_then(Value::as_str)
        .map(Path::new)
        .map(Path::to_path_buf)
        .ok_or_else(|| ApiError::invalid_argument(format!("缺少参数 {key}。")))
}

fn workspace_export(params: &Params) -> Result<Value, ApiError> {
    Ok(json!(archive::export(
        &Settings::from_env()?,
        &path(params, "path")?
    )?))
}

fn workspace_validate(params: &Params) -> Result<Value, ApiError> {
    Ok(json!(archive::validate(&path(params, "path")?)?))
}

fn workspace_restore(params: &Params) -> Result<Value, ApiError> {
    let target = path(params, "target_root")?;
    if path_at_cwd(&target)? == Settings::from_env()?.workspace {
        return Err(StorageError::new("ACTIVE_WORKSPACE_RESTORE_FORBIDDEN").into());
    }
    Ok(json!(archive::restore(&path(params, "path")?, &target)?))
}

fn document_read(params: &Params) -> Result<Value, ApiError> {
    let settings = Settings::from_env()?;
    let name = params["path"]
        .as_str()
        .ok_or_else(|| ApiError::invalid_argument("需要文档相对路径。"))?;
    let render = params
        .get("render")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let mut result = json!(documents::read(&settings.workspace, name, render)?);
    result["protocol_version"] = json!(PROTOCOL_VERSION);
    Ok(result)
}

static DICTIONARY: LazyLock<DictionaryProvider> = LazyLock::new(DictionaryProvider::default);

fn frozen_pronunciation(params: &Params) -> Result<FrozenPronunciation, ApiError> {
    let session = params
        .get("study_session_id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let exercise = params
        .get("exercise_id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    Ok(FrozenPronunciation::read(
        &Workspace::new(Settings::from_env()?),
        session,
        exercise,
    )?)
}

fn dictionary_lookup(params: &Params) -> Result<Value, ApiError> {
    let frozen = frozen_pronunciation(params)?;
    let accent = params
        .get("accent")
        .and_then(Value::as_str)
        .unwrap_or("en-US");
    let word_index = params
        .get("word_index")
        .and_then(Value::as_u64)
        .map(|index| index as usize);
    Ok(json!(frozen.lookup(&DICTIONARY, accent, word_index)?))
}

fn dictionary_metadata(params: &Params) -> Result<Value, ApiError> {
    let frozen = frozen_pronunciation(params)?;
    let accent = params
        .get("accent")
        .and_then(Value::as_str)
        .unwrap_or("en-US");
    Ok(frozen.metadata(&DICTIONARY, accent)?)
}
