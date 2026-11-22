use std::collections::HashMap;

use serde_json::{json, Value};

use crate::{
    documents,
    infrastructure::{fingerprint::JsonFingerprint, StorageError},
};

use super::packages::{self, Contract, PackageError};

#[derive(Debug)]
pub enum PresentationError {
    Storage(StorageError),
    Package(PackageError),
}

fn s(item: &Value) -> &str {
    item.as_str().unwrap_or_default()
}
fn rows(item: &Value) -> &[Value] {
    item.as_array().map_or(&[], Vec::as_slice)
}

pub fn fallback_markdown(lesson: &Value) -> String {
    let mut lines = vec![format!("# {}", s(&lesson["title"]))];
    let exercise_titles: HashMap<_, _> = rows(&lesson["exercises"])
        .iter()
        .map(|item| (s(&item["id"]), s(&item["title"])))
        .collect();
    for block in rows(&lesson["blocks"]) {
        lines.push(format!("## {}", s(&block["title"])));
        match s(&block["type"]) {
            "concept" if block.get("sections").is_some() => {
                section_markdown(rows(&block["sections"]), 3, &mut lines)
            }
            "concept" | "callout" => lines.push(s(&block["body"]).into()),
            "details" => lines.extend([
                s(&block["summary"]).into(),
                "### 详解".into(),
                s(&block["body"]).into(),
            ]),
            "comparison" => {
                let columns = rows(&block["columns"]);
                lines.push(table_row(columns));
                lines.push(format!("| {} |", vec!["---"; columns.len()].join(" | ")));
                lines.extend(rows(&block["rows"]).iter().map(|row| table_row(rows(row))));
            }
            kind @ ("steps" | "example") => {
                let example = kind == "example";
                let steps = if example { "steps" } else { "items" };
                if example {
                    lines.extend(["### 已知条件".into(), s(&block["given"]).into()]);
                }
                for (index, step) in rows(&block[steps]).iter().enumerate() {
                    lines.push(format!("### {}. {}", index + 1, s(&step["title"])));
                    lines.push(s(&step["body"]).into());
                }
                if example {
                    lines.extend(["### 结论".into(), s(&block["conclusion"]).into()]);
                }
            }
            "summary" => lines.extend(
                rows(&block["items"])
                    .iter()
                    .map(|item| format!("- {}", s(item))),
            ),
            "practice" => lines.extend(
                rows(&block["exercise_ids"])
                    .iter()
                    .filter_map(|reference| exercise_titles.get(s(reference)))
                    .map(|title| format!("- {title}")),
            ),
            _ => {}
        }
        lines.push(String::new());
    }
    lines.join("\n\n") + "\n"
}

fn table_row(items: &[Value]) -> String {
    let cells: Vec<_> = items
        .iter()
        .map(|item| s(item).replace('|', "\\|").replace('\n', " "))
        .collect();
    format!("| {} |", cells.join(" | "))
}

pub(crate) fn source_section_markdown(section: &Value) -> String {
    let mut lines = Vec::new();
    section_markdown(std::slice::from_ref(section), 3, &mut lines);
    lines.join("\n\n")
}

fn section_markdown(sections: &[Value], level: usize, lines: &mut Vec<String>) {
    for item in sections {
        lines.push(format!("{} {}", "#".repeat(level), s(&item["title"])));
        lines.push(s(&item["summary"]).into());
        lines.push(s(&item["body"]).into());
        section_markdown(rows(&item["children"]), level + 1, lines);
    }
}

pub fn render_blocks(
    markdown: &str,
    exercise_ids: &[String],
) -> Result<Vec<Value>, PresentationError> {
    if !markdown.starts_with("---\n") && !markdown.starts_with("---\r\n") {
        return Ok(Vec::new());
    }
    let (meta, _) = documents::parse_front_matter(markdown).map_err(PresentationError::Storage)?;
    let Some(lesson) = meta
        .get("structured_lesson")
        .filter(|lesson| !lesson.is_null())
    else {
        return Ok(Vec::new());
    };
    let revision = packages::schema_revision(&meta["content_schema"]).ok_or_else(|| {
        PresentationError::Package(PackageError::at("content_schema", "不支持的组件版本"))
    })?;
    let contract = Contract {
        revision,
        english: meta["learning_mode"] == "english",
    };
    packages::validate_lesson(lesson, "lesson", contract).map_err(PresentationError::Package)?;
    let exercises = rows(&lesson["exercises"]);
    if exercises.len() != exercise_ids.len() {
        return Err(PresentationError::Package(PackageError::at(
            "exercises",
            "源题目与已登记题目不一致，请导入新包",
        )));
    }
    let ids: HashMap<_, _> = exercises
        .iter()
        .zip(exercise_ids)
        .map(|(source, id)| (s(&source["id"]), id))
        .collect();
    let mut blocks = rows(&lesson["blocks"]).to_vec();
    for block in &mut blocks {
        render_fields(block, &["body", "given", "conclusion", "summary"])?;
        if let Some(sections) = block.get_mut("sections").and_then(Value::as_array_mut) {
            render_sections(sections)?;
        }
        match s(&block["type"]) {
            "practice" => {
                let mapped: Vec<_> = rows(&block["exercise_ids"])
                    .iter()
                    .map(|id| ids[s(id)])
                    .collect();
                block["exercise_ids"] = json!(mapped);
            }
            kind @ ("steps" | "example") => {
                let key = if kind == "steps" { "items" } else { "steps" };
                for step in block[key].as_array_mut().into_iter().flatten() {
                    render_fields(step, &["body"])?;
                }
            }
            _ => {}
        }
    }
    Ok(blocks)
}

fn render_sections(sections: &mut [Value]) -> Result<(), PresentationError> {
    for section in sections {
        render_fields(section, &["body", "summary"])?;
        if let Some(children) = section.get_mut("children").and_then(Value::as_array_mut) {
            render_sections(children)?;
        }
    }
    Ok(())
}

fn render_fields(value: &mut Value, keys: &[&str]) -> Result<(), PresentationError> {
    for &key in keys {
        if let Some(text) = value.get(key).and_then(Value::as_str) {
            let html = documents::render(text, false).map_err(PresentationError::Storage)?;
            value[format!("{key}_html")] = json!(html);
        }
    }
    Ok(())
}

pub fn question_fingerprint(exercise: &Value) -> String {
    let mut english = exercise["english"].as_object().cloned().unwrap_or_default();
    english.remove("checker_version");
    JsonFingerprint::CompactUtf8.hash(&json!({"prompt": exercise["prompt"],
        "requirements": s(&exercise["requirements"]),
        "type": exercise["type"].as_str().unwrap_or("SHORT_ANSWER"), "english": english }))
}

pub fn reference_fingerprint(reference: &Value, question_hash: &str) -> String {
    JsonFingerprint::CompactUtf8
        .hash(&json!({"reference": reference, "question_hash": question_hash}))
}
