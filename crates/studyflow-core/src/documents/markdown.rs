use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use pulldown_cmark::{html, CowStr, Event, Options, Parser, Tag, TagEnd};
use regex::Regex;
use serde_json::{Map, Value};

use crate::infrastructure::StorageError;

pub fn parse_front_matter(text: &str) -> Result<(Value, &str), StorageError> {
    let Some(after_open) = text
        .strip_prefix("---\r\n")
        .or_else(|| text.strip_prefix("---\n"))
    else {
        return Err(StorageError::new("FRONT_MATTER_REQUIRED"));
    };
    let mut offset = 0;
    for line in after_open.split_inclusive('\n') {
        if line.trim() == "---" {
            let parsed: Value = serde_yaml_ng::from_str(&after_open[..offset])
                .map_err(|error| StorageError::caused_by("FRONT_MATTER_INVALID", error))?;
            let metadata = match parsed {
                Value::Null => Value::Object(Map::new()),
                Value::Object(_) => parsed,
                _ => return Err(StorageError::new("FRONT_MATTER_INVALID")),
            };
            return Ok((
                metadata,
                after_open[offset + line.len()..].trim_start_matches(['\n', '\r']),
            ));
        }
        offset += line.len();
    }
    Err(StorageError::new("FRONT_MATTER_INVALID"))
}

pub fn validate_import_metadata(metadata: &Value) -> Result<Value, StorageError> {
    let mut result = metadata.clone();
    for key in ["course", "lesson", "plan_line"] {
        let text = metadata[key]
            .as_str()
            .map(str::trim)
            .filter(|text| !text.is_empty())
            .ok_or_else(|| StorageError::new("FRONT_MATTER_REQUIRED_FIELD"))?;
        result[key] = Value::String(text.into());
    }
    match &metadata["exercises"] {
        Value::Null => result["exercises"] = Value::Array(Vec::new()),
        Value::Array(items) if items.iter().all(Value::is_object) => {}
        _ => return Err(StorageError::new("FRONT_MATTER_INVALID_EXERCISES")),
    }
    Ok(result)
}

pub fn render(text: &str, strip_front_matter: bool) -> Result<String, StorageError> {
    static SCRIPTS: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?is)<script\b[^>]*>.*?</script\s*>|<style\b[^>]*>.*?</style\s*>")
            .expect("static expression")
    });
    let body = if strip_front_matter && text.starts_with("---") {
        parse_front_matter(text)?.1
    } else {
        text
    };
    let body = SCRIPTS.replace_all(body, "");
    let options = Options::ENABLE_TABLES
        | Options::ENABLE_STRIKETHROUGH
        | Options::ENABLE_TASKLISTS
        | Options::ENABLE_HEADING_ATTRIBUTES;
    let mut events = Parser::new_ext(&body, options).collect::<Vec<_>>();
    heading_ids(&mut events);
    let mut rendered = String::new();
    html::push_html(&mut rendered, events.into_iter());
    Ok(sanitizer().clean(&rendered).to_string())
}

fn sanitizer() -> &'static ammonia::Builder<'static> {
    static BUILDER: LazyLock<ammonia::Builder<'static>> = LazyLock::new(|| {
        let tags = [
            "a",
            "abbr",
            "acronym",
            "b",
            "blockquote",
            "br",
            "code",
            "del",
            "em",
            "h1",
            "h2",
            "h3",
            "h4",
            "hr",
            "i",
            "input",
            "li",
            "ol",
            "p",
            "pre",
            "strong",
            "table",
            "tbody",
            "td",
            "th",
            "thead",
            "tr",
            "ul",
        ]
        .into_iter()
        .collect();
        let mut attrs: HashMap<&str, HashSet<&str>> = [
            ("a", ["href", "title"].into_iter().collect()),
            ("abbr", ["title"].into_iter().collect()),
            ("acronym", ["title"].into_iter().collect()),
            (
                "input",
                ["type", "checked", "disabled"].into_iter().collect(),
            ),
            ("code", ["class"].into_iter().collect()),
            ("pre", ["class"].into_iter().collect()),
        ]
        .into_iter()
        .collect();
        for heading in ["h1", "h2", "h3", "h4"] {
            attrs.insert(heading, ["id"].into_iter().collect());
        }
        let mut builder = ammonia::Builder::default();
        builder
            .tags(tags)
            .tag_attributes(attrs)
            .generic_attributes(HashSet::new())
            .clean_content_tags(["script", "style"].into_iter().collect())
            .url_schemes(["http", "https", "mailto"].into_iter().collect())
            .link_rel(None);
        builder
    });
    &BUILDER
}

fn heading_ids(events: &mut [Event<'_>]) {
    let mut used = HashSet::new();
    let mut index = 0;
    while index < events.len() {
        if let Event::Start(Tag::Heading { id, .. }) = &events[index] {
            let explicit = id.as_ref().map(ToString::to_string);
            let text = events[index + 1..]
                .iter()
                .take_while(|event| !matches!(event, Event::End(TagEnd::Heading(_))))
                .filter_map(|event| match event {
                    Event::Text(text) | Event::Code(text) => Some(text.as_ref()),
                    _ => None,
                })
                .collect::<String>();
            let base = explicit.unwrap_or_else(|| slug(&text));
            let mut candidate = base.clone();
            let mut suffix = 1;
            while candidate.is_empty() || !used.insert(candidate.clone()) {
                candidate = format!("{base}_{suffix}");
                suffix += 1;
            }
            if let Event::Start(Tag::Heading { id, .. }) = &mut events[index] {
                *id = Some(CowStr::Boxed(candidate.into_boxed_str()));
            }
        }
        index += 1;
    }
}

fn slug(text: &str) -> String {
    text.to_lowercase()
        .split_whitespace()
        .map(|word| {
            word.chars()
                .filter(|ch| ch.is_alphanumeric() || *ch == '_' || *ch == '-')
                .collect::<String>()
        })
        .filter(|word| !word.is_empty())
        .collect::<Vec<_>>()
        .join("-")
}
