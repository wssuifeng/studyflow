use serde_json::{json, Value};
use studyflow_core::{
    courses::practice::{self, PreviewError, PreviewMode},
    infrastructure::config::Settings,
};

use crate::{registry::Params, ApiError};

pub const ID_LIMIT: usize = 80;
const QUESTION_LIMIT: usize = 20;
const BLANK_LIMIT: usize = 10;
const BLANK_ANSWER_LIMIT: usize = 120;

pub fn preview(params: &Params) -> Result<Value, ApiError> {
    let audio = params
        .get("audio")
        .and_then(Value::as_bool)
        .unwrap_or_default();
    let captions = params
        .get("captions")
        .and_then(Value::as_bool)
        .unwrap_or_default();
    let mode = match (audio, captions) {
        (true, true) => {
            return Err(PreviewError::Invalid("请选择听力题组，并分别请求音频和字幕。").into())
        }
        (true, false) => PreviewMode::Audio,
        (false, true) => PreviewMode::Captions,
        (false, false) => PreviewMode::Practice(params.get("answers").and_then(Value::as_object)),
    };
    let root = Settings::from_env()?.workspace;
    Ok(practice::author_preview(
        &root,
        &params["package"],
        params["lesson_id"].as_str().unwrap_or_default(),
        params["exercise_id"].as_str().unwrap_or_default(),
        mode,
    )?)
}

fn identifier(value: &str) -> bool {
    !value.is_empty() && value.chars().count() <= ID_LIMIT
}

pub fn answers_valid(answers: &Value) -> bool {
    answers.as_object().is_some_and(|questions| {
        questions.len() <= QUESTION_LIMIT
            && questions.iter().all(|(id, answer)| {
                identifier(id)
                    && match answer {
                        Value::String(option) => identifier(option),
                        Value::Object(blanks) => {
                            blanks.len() <= BLANK_LIMIT
                                && blanks.iter().all(|(id, answer)| {
                                    identifier(id)
                                        && answer.as_str().is_some_and(|text| {
                                            text.chars().count() <= BLANK_ANSWER_LIMIT
                                        })
                                })
                        }
                        _ => false,
                    }
            })
    })
}

pub fn answers_schema(title: &str) -> Value {
    let id = json!({"type": "string", "minLength": 1, "maxLength": ID_LIMIT});
    let name = json!({"minLength": 1, "maxLength": ID_LIMIT});
    json!({
        "title": title, "default": null, "anyOf": [
            {"type": "object", "maxProperties": QUESTION_LIMIT, "propertyNames": name,
             "additionalProperties": {"anyOf": [id, {
                 "type": "object", "maxProperties": BLANK_LIMIT, "propertyNames": name,
                 "additionalProperties": {"type":"string", "maxLength": BLANK_ANSWER_LIMIT}
             }]}},
             {"type": "null"}
        ],
    })
}

impl From<PreviewError> for ApiError {
    fn from(error: PreviewError) -> Self {
        match error {
            PreviewError::Package(error) => error.into(),
            PreviewError::Storage(error) => error.into(),
            PreviewError::Invalid(message) => Self {
                code: "INVALID_ARGUMENT",
                message: message.into(),
                next_action: "重新读取当前对象状态后重试。".into(),
            },
            PreviewError::NotFound => Self {
                code: "OBJECT_NOT_FOUND",
                message: "所选知识点没有这个听力或阅读题组。".into(),
                next_action: "重新读取当前对象状态后重试。".into(),
            },
            PreviewError::Incomplete { code, missing } => Self {
                code,
                message: "请完成全部题目与空位后确认。".into(),
                next_action: missing.join(", ").into(),
            },
        }
    }
}

pub fn quality_check(mut args: impl Iterator<Item = String>) -> std::process::ExitCode {
    use crate::cli::{self, ParseResult};
    use std::process::ExitCode;
    use studyflow_core::{audio::assets::digest, courses::quality};

    let mut ordinary = Vec::new();
    let mut related = Vec::new();
    while let Some(argument) = args.next() {
        if argument == "--related" {
            match args.next().filter(|value| !value.starts_with("--")) {
                Some(path) if !path.is_empty() => related.push(path),
                _ => return cli::usage_error(),
            }
        } else if let Some(path) = argument.strip_prefix("--related=") {
            if path.is_empty() {
                return cli::usage_error();
            }
            related.push(path.to_owned());
        } else {
            ordinary.push(argument);
        }
    }
    let (options, json_output) = match cli::parse_with_empty(
        ordinary.into_iter(),
        &[
            ("--file", true),
            ("--blueprint", false),
            ("--sources", false),
            ("--validation-receipt", false),
            ("--rendering-receipt", false),
            ("--long-section-chars", false),
            ("--format", false),
        ],
        Some("--long-section-chars"),
    ) {
        ParseResult::Valid(options, format) => (options, format.unwrap_or(false)),
        ParseResult::Help => return cli::help(),
        ParseResult::Invalid => return cli::usage_error(),
    };
    let outcome = (|| -> Result<Value, ApiError> {
        let (package, data) = quality_json(&options["--file"], "课程包")?;
        let load = |key: &str| {
            options
                .get(key)
                .map(|path| quality_json(path, key).map(|(value, _)| value))
                .transpose()
        };
        let blueprint = load("--blueprint")?;
        let sources = load("--sources")?;
        let validation_receipt = load("--validation-receipt")?;
        let rendering_receipt = load("--rendering-receipt")?;
        let related: Vec<_> = related
            .iter()
            .map(|path| quality_json(path, "--related").map(|(value, _)| value))
            .collect::<Result<_, _>>()?;
        let threshold = match options.get("--long-section-chars") {
            None => 400,
            Some(input) => input
                .trim()
                .parse::<usize>()
                .ok()
                .filter(|&value| value > 0)
                .ok_or_else(|| ApiError {
                    code: "INVALID_ARGUMENT",
                    message: "--long-section-chars 必须是正整数。".into(),
                    next_action: format!("当前值：'{input}'。不接受零或负数。").into(),
                })?,
        };
        let context = quality::Options {
            blueprint: blueprint.as_ref(),
            sources: sources.as_ref(),
            related: &related,
            validation_receipt: validation_receipt.as_ref(),
            rendering_receipt: rendering_receipt.as_ref(),
            long_section_chars: threshold,
        };
        Ok(quality::analyze(&package, &digest(&data), context))
    })();
    match outcome {
        Ok(mut report) => {
            report["ok"] = json!(true);
            cli::display(report, json_output);
            ExitCode::SUCCESS
        }
        Err(error) => cli::preflight_error(error),
    }
}

fn quality_json(path: &str, label: &str) -> Result<(Value, Vec<u8>), ApiError> {
    use std::{fs::File, io::Read};
    const LIMIT: u64 = 16 * 1024 * 1024;
    let mut bytes = Vec::new();
    if !std::path::Path::new(path).is_file() {
        return Err(ApiError {
            code: "DOCUMENT_UNREADABLE",
            message: format!("{label}文件不存在：{path}"),
            next_action: "提供存在的文件路径。".into(),
        });
    }
    File::open(path)
        .and_then(|file| file.take(LIMIT + 1).read_to_end(&mut bytes))
        .map_err(|_| ApiError {
            code: "DOCUMENT_UNREADABLE",
            message: format!("{label}文件无法读取：{path}"),
            next_action: "检查读取权限与路径。".into(),
        })?;
    if bytes.len() as u64 > LIMIT {
        return Err(ApiError::invalid_argument(format!("{label}超过 16 MiB。")));
    }
    let body = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&bytes);
    let text = std::str::from_utf8(body).map_err(|_| ApiError {
        code: "DOCUMENT_UNREADABLE",
        message: format!("{label}文件无法按 UTF-8 读取。"),
        next_action: "检查文件编码。".into(),
    })?;
    let value: Value = serde_json::from_str(text).map_err(|_| ApiError {
        code: "INVALID_ARGUMENT",
        message: format!("{label}不是合法JSON。"),
        next_action: "修正JSON语法后重试。".into(),
    })?;
    if !(value.is_object() || label == "--sources" && value.is_array()) {
        return Err(ApiError {
            code: "INVALID_ARGUMENT",
            message: format!("{label}必须是JSON对象。"),
            next_action: "按W1设计§3的输入结构提供。".into(),
        });
    }
    Ok((value, bytes))
}
