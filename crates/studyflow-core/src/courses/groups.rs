use std::collections::HashSet;

use icu_casemap::CaseMapper;
use icu_normalizer::ComposingNormalizer;
use serde_json::Value;

use super::validation::*;
use crate::infrastructure::file_paths::is_sha256;

pub fn normalize_answer(text: &str) -> String {
    let normalized = ComposingNormalizer::new_nfkc().normalize(text);
    CaseMapper::new()
        .fold_string(normalized.trim())
        .into_owned()
}

pub(super) fn validate_exercise(
    exercise: &Value,
    kind: &str,
    loc: &str,
    focused: bool,
) -> Checked<()> {
    for (key, exercise_type) in [
        ("reading", "READING_GROUP"),
        ("listening", "LISTENING_GROUP"),
    ] {
        if kind == exercise_type {
            if exercise.get("review_reference").is_some() {
                return invalid(
                    loc,
                    if key == "reading" {
                        "阅读题组由本地判分"
                    } else {
                        "听力题组由本地判分"
                    },
                );
            }
            validate_group(
                &exercise[key],
                &format!("{loc}.{key}"),
                key == "reading",
                focused,
            )?;
        } else if exercise.get(key).is_some() {
            return invalid(loc, format!("{key} 仅用于 {exercise_type}"));
        }
    }
    if let Some(essay) = exercise.get("essay") {
        let loc = format!("{loc}.essay");
        if kind != "ESSAY" {
            return invalid(&loc, "essay 仅用于 ESSAY");
        }
        object(essay, &loc, &["suggested_words", "points"], &[])?;
        if let Some(range) = essay.get("suggested_words") {
            let field = format!("{loc}.suggested_words");
            let range = list(range, &field, 2, 2)?;
            let min = range[0].as_u64().unwrap_or(0);
            let max = range[1].as_u64().unwrap_or(0);
            if min == 0 || min > max || max > 5000 {
                return invalid(&field, "填写递增的整数词数范围，最多 5000 词");
            }
        }
        if let Some(points) = essay.get("points") {
            let field = format!("{loc}.points");
            for item in list(points, &field, 1, 12)? {
                text(item, &field, 1000, false)?;
            }
        }
    }
    Ok(())
}

fn validate_group(group: &Value, loc: &str, reading: bool, focused: bool) -> Checked<()> {
    let base: &[&str] = if reading {
        &["title", "paragraphs", "questions"]
    } else {
        &["title", "audio", "transcript", "questions"]
    };
    let mut allowed = base.to_vec();
    if !reading && focused {
        allowed.push("captions");
    }
    object(group, loc, &allowed, base)?;
    text(&group["title"], &format!("{loc}.title"), 200, false)?;
    let mut question_base = vec!["id", "prompt", "explanation"];
    let paragraphs = if reading {
        question_base.push("evidence");
        text_items(
            &group["paragraphs"],
            &format!("{loc}.paragraphs"),
            1,
            40,
            4000,
        )?
    } else {
        text(
            &group["transcript"],
            &format!("{loc}.transcript"),
            20_000,
            false,
        )?;
        if let Some(captions) = group.get("captions") {
            validate_captions(captions, &format!("{loc}.captions"))?;
        }
        let audio = &group["audio"];
        let fields = ["sha256", "format"];
        let field = format!("{loc}.audio");
        object(audio, &field, &fields, &fields)?;
        if !audio["sha256"].as_str().is_some_and(is_sha256)
            || !matches!(audio["format"].as_str(), Some("wav" | "mp3"))
        {
            return invalid(&field, "使用已采用的 WAV 或 MP3 音频摘要");
        }
        HashSet::new()
    };
    let field = format!("{loc}.questions");
    let allow_cloze = !reading || focused;
    let mut allowed = question_base.clone();
    allowed.extend(["options", "correct_option_id"]);
    if allow_cloze {
        allowed.extend(["parts", "blanks"]);
    }
    let mut seen = HashSet::new();
    for (index, question) in list(&group["questions"], &field, 1, 20)?.iter().enumerate() {
        let loc = format!("{field}[{index}]");
        let fields = object(question, &loc, &allowed, &question_base)?;
        unique_id(&question["id"], &loc, &mut seen)?;
        text(&question["prompt"], &format!("{loc}.prompt"), 2000, false)?;
        text(
            &question["explanation"],
            &format!("{loc}.explanation"),
            4000,
            false,
        )?;
        let exactly_one_shape = fields.len() == question_base.len() + 2;
        if exactly_one_shape
            && fields.contains_key("options")
            && fields.contains_key("correct_option_id")
        {
            validate_options(question, &loc)?;
        } else if exactly_one_shape
            && allow_cloze
            && fields.contains_key("parts")
            && fields.contains_key("blanks")
        {
            validate_cloze(question, &loc, focused)?;
        } else {
            let reason = match (reading, focused) {
                (true, true) => "阅读题须为单选或填空",
                (true, false) => "阅读题须为单选",
                _ => "听力题须为单选或对话补全",
            };
            return invalid(&loc, reason);
        }
        if reading {
            let field = format!("{loc}.evidence");
            for item in list(&question["evidence"], &field, 1, paragraphs.len())? {
                if !paragraphs.contains(identifier(item, &field)?) {
                    return invalid(&field, "证据须引用本篇段落");
                }
            }
        }
    }
    Ok(())
}

fn unique_id<'a>(value: &'a Value, loc: &str, ids: &mut HashSet<&'a str>) -> Checked<()> {
    let field = format!("{loc}.id");
    let id = identifier(value, &field)?;
    if !ids.insert(id) {
        return invalid(&field, "ID 重复");
    }
    Ok(())
}

fn text_items<'a>(
    items: &'a Value,
    field: &str,
    min: usize,
    max: usize,
    limit: usize,
) -> Checked<HashSet<&'a str>> {
    let mut ids = HashSet::new();
    let fields = ["id", "text"];
    for (index, item) in list(items, field, min, max)?.iter().enumerate() {
        let loc = format!("{field}[{index}]");
        object(item, &loc, &fields, &fields)?;
        unique_id(&item["id"], &loc, &mut ids)?;
        text(&item["text"], &format!("{loc}.text"), limit, false)?;
    }
    Ok(ids)
}

fn validate_options(question: &Value, loc: &str) -> Checked<()> {
    let field = format!("{loc}.options");
    let ids = text_items(&question["options"], &field, 4, 4, 1200)?;
    let entries = question["options"].as_array().expect("validated options");
    let texts: HashSet<_> = entries
        .iter()
        .map(|option| option["text"].as_str().expect("validated option").trim())
        .collect();
    if texts.len() != 4 {
        return invalid(&field, "选项文字重复");
    }
    let field = format!("{loc}.correct_option_id");
    if !ids.contains(identifier(&question["correct_option_id"], &field)?) {
        return invalid(&field, "正确项须引用本题选项");
    }
    Ok(())
}

fn validate_cloze(question: &Value, loc: &str, phrases: bool) -> Checked<()> {
    let mut ids = HashSet::new();
    let field = format!("{loc}.blanks");
    let fields = ["id", "accepted"];
    for (index, blank) in list(&question["blanks"], &field, 1, 10)?.iter().enumerate() {
        let loc = format!("{field}[{index}]");
        object(blank, &loc, &fields, &fields)?;
        unique_id(&blank["id"], &loc, &mut ids)?;
        let field = format!("{loc}.accepted");
        for answer in list(&blank["accepted"], &field, 1, 10)? {
            let answer = text(answer, &field, 120, false)?;
            if !phrases && normalize_answer(answer).split_whitespace().count() != 1 {
                return invalid(&field, "每空仅接受一个单词");
            }
        }
    }
    let field = format!("{loc}.parts");
    for (index, part) in list(&question["parts"], &field, 2, 40)?.iter().enumerate() {
        let loc = format!("{field}[{index}]");
        let fields = object(part, &loc, &["text", "blank_id"], &[])?;
        match (fields.len(), part.get("text"), part.get("blank_id")) {
            (1, Some(value), None) => {
                text(value, &format!("{loc}.text"), 1200, false)?;
            }
            (1, None, Some(value)) => {
                if !ids.remove(identifier(value, &format!("{loc}.blank_id"))?) {
                    return invalid(&field, "每个空位必须且只能出现一次");
                }
            }
            _ => return invalid(&loc, "每个片段须为固定文字或一个空位"),
        }
    }
    if !ids.is_empty() {
        return invalid(&field, "每个空位必须且只能出现一次");
    }
    Ok(())
}

fn validate_captions(items: &Value, field: &str) -> Checked<()> {
    let mut previous_end = 0.0;
    let mut chars = 0;
    let fields = ["start", "end", "text"];
    for (index, item) in list(items, field, 1, 200)?.iter().enumerate() {
        let loc = format!("{field}[{index}]");
        object(item, &loc, &fields, &fields)?;
        let start = item["start"].as_f64().unwrap_or(f64::NAN);
        let end = item["end"].as_f64().unwrap_or(f64::NAN);
        if !(start >= previous_end && start < end && end.is_finite()) {
            return invalid(&loc, "字幕时间以秒为单位，须递增且不得重叠");
        }
        previous_end = end;
        chars += text(&item["text"], &format!("{loc}.text"), 1200, false)?
            .chars()
            .count();
    }
    if chars > 20_000 {
        return invalid(field, "字幕总长度最多 20000 字符");
    }
    Ok(())
}
