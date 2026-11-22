use std::path::Path;

use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Map, Value};

use crate::{
    audio::assets::{self, AudioRef},
    infrastructure::StorageError,
};

use super::{
    groups::normalize_answer,
    packages::{self, PackageError},
};

#[derive(Clone, Copy)]
pub enum GroupKind {
    Reading,
    Listening,
}

#[derive(Debug)]
pub enum PreviewError {
    Package(PackageError),
    Storage(StorageError),
    Invalid(&'static str),
    NotFound,
    Incomplete {
        code: &'static str,
        missing: Vec<String>,
    },
}

impl From<StorageError> for PreviewError {
    fn from(error: StorageError) -> Self {
        Self::Storage(error)
    }
}

impl From<rusqlite::Error> for PreviewError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Storage(error.into())
    }
}

impl GroupKind {
    pub(crate) fn field(self) -> &'static str {
        match self {
            Self::Reading => "reading",
            Self::Listening => "listening",
        }
    }

    fn incomplete(self) -> &'static str {
        match self {
            Self::Reading => "INCOMPLETE_READING_GROUP",
            Self::Listening => "INCOMPLETE_LISTENING_GROUP",
        }
    }
}

pub enum PreviewMode<'a> {
    Practice(Option<&'a Map<String, Value>>),
    Audio,
    Captions,
}

pub fn author_preview(
    root: &Path,
    package: &Value,
    lesson_id: &str,
    exercise_id: &str,
    mode: PreviewMode<'_>,
) -> Result<Value, PreviewError> {
    packages::validate(package).map_err(PreviewError::Package)?;
    let exercise = package["lessons"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|lesson| lesson["id"] == lesson_id)
        .and_then(|lesson| lesson["exercises"].as_array())
        .and_then(|exercises| exercises.iter().find(|item| item["id"] == exercise_id))
        .ok_or(PreviewError::NotFound)?;
    let kind = match exercise["type"].as_str() {
        Some("READING_GROUP") => GroupKind::Reading,
        Some("LISTENING_GROUP") => GroupKind::Listening,
        _ => return Err(PreviewError::NotFound),
    };
    let group = &exercise[kind.field()];
    if matches!(kind, GroupKind::Reading) && !matches!(mode, PreviewMode::Practice(_)) {
        return Err(PreviewError::Invalid(
            "请选择听力题组，并分别请求音频和字幕。",
        ));
    }
    if matches!(mode, PreviewMode::Captions) {
        return Ok(caption_payload(group));
    }
    if matches!(kind, GroupKind::Listening) {
        if matches!(mode, PreviewMode::Audio) {
            return audio_payload(root, group);
        }
        read_audio(root, group)?;
    }

    let mut state = json!({"version": 0, "answers": {}, "position": 0, "result": null});
    if let PreviewMode::Practice(Some(answers)) = mode {
        state["answers"] = json!(answers);
        state["result"] = evaluate(group, answers, kind, true)?;
    }
    Ok(public_group(group, kind, state, false))
}

pub(crate) fn read_audio(
    root: &Path,
    group: &Value,
) -> Result<(assets::AudioAsset, AudioRef), PreviewError> {
    let reference: AudioRef = serde_json::from_value(group["audio"].clone())
        .map_err(|error| StorageError::caused_by("INVALID_AUDIO", error))?;
    Ok((assets::read(root, &reference)?, reference))
}

pub(crate) fn audio_payload(root: &Path, group: &Value) -> Result<Value, PreviewError> {
    let (asset, reference) = read_audio(root, group)?;
    Ok(json!({"data":STANDARD.encode(asset.bytes),"mime":reference.format.mime()}))
}

pub fn caption_payload(group: &Value) -> Value {
    match group.get("captions") {
        Some(captions) => json!({"captions": captions}),
        None => json!({"transcript": group["transcript"]}),
    }
}

/// Material that may be shown before confirmation. The same projection is used
/// by author preview and frozen learning rounds.
pub fn public_group(group: &Value, kind: GroupKind, mut state: Value, read_only: bool) -> Value {
    let questions: Vec<_> = group["questions"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|question| {
            ["id", "prompt", "options", "parts"]
                .into_iter()
                .filter_map(|key| {
                    question
                        .get(key)
                        .cloned()
                        .map(|value| (key.to_owned(), value))
                })
                .collect::<Map<_, _>>()
        })
        .collect();
    match kind {
        GroupKind::Reading => state["paragraphs"] = group["paragraphs"].clone(),
        GroupKind::Listening => {
            state["audio"] = group["audio"].clone();
            if !state["result"].is_null() {
                state["transcript"] = group["transcript"].clone();
            }
        }
    }
    state["title"] = group["title"].clone();
    state["questions"] = json!(questions);
    state["read_only"] = json!(read_only);
    state
}

pub fn evaluate(
    group: &Value,
    answers: &Map<String, Value>,
    kind: GroupKind,
    confirm: bool,
) -> Result<Value, PreviewError> {
    let questions = group["questions"]
        .as_array()
        .expect("validated or frozen questions");
    if answers
        .keys()
        .any(|id| !questions.iter().any(|question| question["id"] == *id))
    {
        return Err(PreviewError::Invalid("题号超出题组范围。"));
    }
    let mut items = Vec::with_capacity(questions.len());
    let mut missing = Vec::new();
    for question in questions {
        let id = question["id"]
            .as_str()
            .expect("validated or frozen question ID");
        let answer = answers.get(id);
        let mut item = json!({"id": id, "explanation": question["explanation"]});
        if let Some(options) = question["options"].as_array() {
            match answer {
                Some(value)
                    if value.is_string() && options.iter().any(|option| &option["id"] == value) => {
                }
                Some(_) => return Err(PreviewError::Invalid("所选答案须属于对应题目。")),
                None => missing.push(id.to_owned()),
            }
            item["correct_option_id"] = question["correct_option_id"].clone();
            item["correct"] = json!(answer == question.get("correct_option_id"));
        } else {
            let blanks = evaluate_blanks(&question["blanks"], answer, id, &mut missing)?;
            item["correct"] = json!(blanks.iter().all(|blank| blank["correct"] == true));
            item["blanks"] = json!(blanks);
        }
        if let Some(evidence) = question.get("evidence") {
            item["evidence"] = evidence.clone();
        }
        items.push(item);
    }
    if !confirm {
        return Ok(Value::Null);
    }
    if !missing.is_empty() {
        return Err(PreviewError::Incomplete {
            code: kind.incomplete(),
            missing,
        });
    }
    Ok(
        json!({"correct": items.iter().filter(|item| item["correct"] == true).count(), "total": items.len(), "items": items}),
    )
}

fn evaluate_blanks(
    blanks: &Value,
    answer: Option<&Value>,
    question: &str,
    missing: &mut Vec<String>,
) -> Result<Vec<Value>, PreviewError> {
    let blanks = blanks.as_array().expect("validated or frozen blanks");
    let empty = Map::new();
    let error = || PreviewError::Invalid("只能编辑题目中定义的空位。");
    let values = match answer {
        Some(value) => value.as_object().ok_or_else(error)?,
        None => &empty,
    };
    if values
        .iter()
        .any(|(key, value)| !value.is_string() || !blanks.iter().any(|blank| blank["id"] == *key))
    {
        return Err(error());
    }
    let mut marked = Vec::with_capacity(blanks.len());
    for blank in blanks {
        let id = blank["id"].as_str().expect("validated or frozen blank ID");
        let accepted = blank["accepted"]
            .as_array()
            .expect("validated or frozen accepted answers");
        let candidate =
            normalize_answer(values.get(id).and_then(Value::as_str).unwrap_or_default());
        if candidate.is_empty() {
            missing.push(format!("{question}/{id}"));
        }
        let correct = accepted
            .iter()
            .filter_map(Value::as_str)
            .any(|value| normalize_answer(value) == candidate);
        marked.push(json!({"id": id, "correct": correct, "accepted": accepted[0]}));
    }
    Ok(marked)
}
