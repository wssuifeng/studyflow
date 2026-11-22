use std::collections::{BTreeMap, HashMap, HashSet};

use icu_normalizer::ComposingNormalizer;
use serde_json::{json, Value};

use super::{invalid, rows, text, Record};
use crate::infrastructure::StorageError;

const BLOCKS: &[&str] = &["paragraph", "heading", "bulletList", "orderedList"];
const MAX_NODES: usize = 50_000;

pub(super) fn normalize(text: &str) -> String {
    ComposingNormalizer::new_nfc()
        .normalize(&text.replace("\r\n", "\n").replace('\r', "\n"))
        .into_owned()
}

pub(super) fn plain(content: &Value) -> String {
    fn append(output: &mut String, node: &Value) {
        match text(&node["type"]) {
            "text" => output.push_str(text(&node["text"])),
            "hardBreak" => output.push('\n'),
            kind => {
                let separated = matches!(kind, "listItem" | "bulletList" | "orderedList");
                for (index, child) in rows(&node["content"]).iter().enumerate() {
                    if index > 0 && separated {
                        output.push('\n');
                    }
                    append(output, child);
                }
            }
        }
    }
    let mut output = String::new();
    for (index, node) in rows(content).iter().enumerate() {
        if index > 0 {
            output.push('\n');
        }
        append(&mut output, node);
    }
    output
}

pub(super) fn fields(value: &Value, allowed: &[&str]) -> bool {
    value
        .as_object()
        .is_some_and(|fields| fields.keys().all(|key| allowed.contains(&key.as_str())))
}

pub(super) fn identity(value: &Value) -> Result<&str, StorageError> {
    value
        .as_str()
        .filter(|id| !id.trim().is_empty() && id.chars().count() <= 64)
        .ok_or_else(invalid)
}

fn present(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|number| number != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn check_node(
    node: &Value,
    allowed: &[&str],
    depth: usize,
    count: &mut usize,
    sources: &BTreeMap<String, Value>,
) -> Result<(), StorageError> {
    *count += 1;
    let kind = text(&node["type"]);
    if *count > MAX_NODES
        || depth > 12
        || !allowed.contains(&kind)
        || !fields(node, &["type", "text", "attrs", "content", "marks"])
    {
        return Err(invalid());
    }
    let attrs = match kind {
        "heading" => &["level"][..],
        "orderedList" => &["start"][..],
        _ => &[],
    };
    if node
        .get("attrs")
        .is_some_and(|attrs_value| !fields(attrs_value, attrs))
        || (kind == "heading" && !matches!(node["attrs"]["level"].as_u64(), Some(2 | 3)))
        || (kind == "orderedList"
            && node["attrs"]
                .get("start")
                .is_some_and(|start| !matches!(start.as_u64(), Some(1..=10000))))
    {
        return Err(invalid());
    }
    if kind == "text" {
        if text(&node["text"]).is_empty() || node.get("content").is_some() {
            return Err(invalid());
        }
        let mut seen = HashSet::new();
        if node
            .get("marks")
            .is_some_and(|marks| !marks.is_array() || rows(marks).len() > 4)
        {
            return Err(invalid());
        }
        for mark in rows(&node["marks"]) {
            let mark_type = text(&mark["type"]);
            if !fields(mark, &["type", "attrs"]) || !seen.insert(mark_type) {
                return Err(invalid());
            }
            match mark_type {
                "citation" => {
                    let attrs = &mark["attrs"];
                    if !fields(attrs, &["sourceId", "occurrenceId"])
                        || !sources.contains_key(identity(&attrs["sourceId"])?)
                    {
                        return Err(invalid());
                    }
                    identity(&attrs["occurrenceId"])?;
                }
                "bold" | "italic" | "code" if !present(&mark["attrs"]) => {}
                _ => return Err(invalid()),
            }
        }
        return Ok(());
    }
    if node.get("text").is_some()
        || present(&node["marks"])
        || node
            .get("content")
            .is_some_and(|children| !children.is_array())
    {
        return Err(invalid());
    }
    let children = rows(&node["content"]);
    let allowed_children: &[&str] = match kind {
        "paragraph" | "heading" => &["text", "hardBreak"],
        "bulletList" | "orderedList" if !children.is_empty() => &["listItem"],
        "listItem"
            if children
                .first()
                .is_some_and(|first| first["type"] == "paragraph") =>
        {
            &["paragraph", "bulletList", "orderedList"]
        }
        "hardBreak" if children.is_empty() => &[],
        _ => return Err(invalid()),
    };
    for child in children {
        check_node(child, allowed_children, depth + 1, count, sources)?;
    }
    Ok(())
}

pub(super) fn check_content(
    content: &Value,
    count: &mut usize,
    sources: &BTreeMap<String, Value>,
) -> Result<(), StorageError> {
    if rows(content).is_empty() {
        return Err(invalid());
    }
    for node in rows(content) {
        check_node(node, BLOCKS, 0, count, sources)?;
    }
    if plain(content).chars().count() > 200_000 {
        return Err(invalid());
    }
    Ok(())
}

fn walk<'a>(node: &'a Value, visit: &mut impl FnMut(&'a Value)) {
    visit(node);
    for child in rows(&node["content"]) {
        walk(child, visit);
    }
}

fn citation(node: &Value) -> Option<(&str, &str)> {
    let mark = rows(&node["marks"])
        .iter()
        .find(|mark| mark["type"] == "citation")?;
    Some((
        text(&mark["attrs"]["occurrenceId"]),
        text(&mark["attrs"]["sourceId"]),
    ))
}

pub(super) fn validate(document: &Record) -> Result<(), StorageError> {
    if document.entries.len() > 1000
        || document
            .sources
            .values()
            .map(|source| text(&source["original"]).chars().count())
            .sum::<usize>()
            > 1_000_000
    {
        return Err(invalid());
    }
    let mut count = 0;
    let mut total = 0;
    let mut owners = HashMap::new();
    let mut ids = HashSet::new();
    for entry in &document.entries {
        let id = identity(&entry["id"])?;
        if !ids.insert(id) {
            return Err(invalid());
        }
        let content = &entry["content"];
        check_content(content, &mut count, &document.sources)?;
        total += plain(content).chars().count();
        let mut valid = true;
        let mut previous = None;
        let mut completed = HashSet::new();
        for node in rows(content) {
            walk(node, &mut |node| {
                if node["type"] != "text" {
                    return;
                }
                let reference = citation(node);
                let current = reference.map(|(occurrence, _)| occurrence);
                if current != previous {
                    if let Some(previous) = previous {
                        completed.insert(previous);
                    }
                    valid &= current.is_none_or(|occurrence| !completed.contains(occurrence));
                    previous = current;
                }
                if let Some((occurrence, source)) = reference {
                    valid &= *owners.entry(occurrence).or_insert((id, source)) == (id, source);
                }
            });
        }
        if !valid {
            return Err(invalid());
        }
    }
    if total > 1_000_000
        || crate::infrastructure::fingerprint::JsonFingerprint::Utf8
            .serialize(&json!(document.entries))
            .len()
            > 8_000_000
    {
        return Err(invalid());
    }
    Ok(())
}

pub(super) fn citations(
    entries: &[Value],
    sources: &BTreeMap<String, Value>,
) -> Result<Vec<Value>, StorageError> {
    let mut result = Vec::new();
    for entry in entries {
        let mut occurrences = Vec::<(&str, &str, String, usize)>::new();
        let mut indexes = HashMap::new();
        for (paragraph, node) in rows(&entry["content"]).iter().enumerate() {
            walk(node, &mut |node| {
                let Some((id, source)) = citation(node) else {
                    return;
                };
                let index = *indexes.entry(id).or_insert_with(|| {
                    occurrences.push((id, source, String::new(), paragraph));
                    occurrences.len() - 1
                });
                let (_, _, chunk, last) = &mut occurrences[index];
                if *last != paragraph {
                    chunk.push('\n');
                    *last = paragraph;
                }
                chunk.push_str(text(&node["text"]));
            });
        }
        for (id, source, chunk, _) in occurrences {
            let original = sources
                .get(source)
                .ok_or_else(|| StorageError::new("DATABASE_ERROR"))?;
            let original = normalize(text(&original["original"]));
            let chunk = normalize(&chunk);
            let state = if chunk == original {
                "ORIGINAL"
            } else if !chunk.is_empty() && original.contains(&chunk) {
                "PARTIAL"
            } else {
                "EDITED"
            };
            result.push(json!({"entry_id":entry["id"], "occurrence_id":id, "source_id":source, "state":state}));
        }
    }
    Ok(result)
}
