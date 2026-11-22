use std::{cell::RefCell, collections::BTreeMap};

use html5ever::tokenizer::{BufferQueue, TagKind, Token, TokenSink, TokenSinkResult, Tokenizer};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::{
    document::{fields, identity, normalize},
    invalid, rows, text,
};
use crate::{
    courses::presentation, documents, infrastructure::StorageError, learning::study_sessions,
};

pub(super) fn scope(cid: &Value, lid: &Value) -> &'static str {
    if !text(lid).is_empty() {
        "LESSON"
    } else if !text(cid).is_empty() {
        "COURSE"
    } else {
        "PLAN"
    }
}

pub(super) fn membership(
    db: &Connection,
    plan: &str,
    course: &Value,
    lesson: &Value,
    scope: &str,
) -> Result<Value, StorageError> {
    if scope == "PLAN" && text(course).is_empty() && text(lesson).is_empty() {
        return Ok(
            json!({"scope":scope,"course_id":null,"lesson_id":null,"course_title":null,"lesson_title":null}),
        );
    }
    let course_id = identity(course)?;
    let course_title: String = db.query_row("SELECT c.title FROM courses c WHERE c.id=?1 AND (c.plan_line_id=?2 OR EXISTS(SELECT 1 FROM plan_course_items p WHERE p.plan_line_id=?2 AND p.course_id=c.id))", params![course_id,plan], |row|row.get(0)).optional()?.ok_or_else(invalid)?;
    let lesson_title: Option<String> = match scope {
        "LESSON" => Some(
            db.query_row(
                "SELECT title FROM lessons WHERE id=? AND course_id=?",
                params![identity(lesson)?, course_id],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(invalid)?,
        ),
        "COURSE" if text(lesson).is_empty() => None,
        _ => return Err(invalid()),
    };
    Ok(
        json!({"scope":scope,"course_id":course,"lesson_id":lesson,"course_title":course_title,"lesson_title":lesson_title}),
    )
}

struct PlainText {
    text: RefCell<String>,
    legacy_space: bool,
}

impl TokenSink for PlainText {
    type Handle = ();
    fn process_token(&self, token: Token, _: u64) -> TokenSinkResult<()> {
        let mut output = self.text.borrow_mut();
        match token {
            Token::CharacterTokens(chunk) => output.push_str(&chunk),
            Token::TagToken(tag) => {
                let name = tag.name.as_ref();
                let end = tag.kind == TagKind::EndTag;
                let block = if self.legacy_space {
                    matches!(
                        name,
                        "p" | "div" | "li" | "h1" | "h2" | "h3" | "tr" | "td" | "th" | "pre" | "br"
                    )
                } else {
                    matches!(
                        name,
                        "p" | "div" | "li" | "h1" | "h2" | "h3" | "h4" | "tr" | "pre"
                    )
                };
                if (end && block) || (!end && name == "br") {
                    output.push(if self.legacy_space { ' ' } else { '\n' });
                }
            }
            _ => {}
        }
        TokenSinkResult::Continue
    }
}

fn html_text(html: &str, legacy: bool) -> String {
    let queue = BufferQueue::default();
    queue.push_back(html.into());
    let tokenizer = Tokenizer::new(
        PlainText {
            text: RefCell::new(String::new()),
            legacy_space: legacy,
        },
        Default::default(),
    );
    let _ = tokenizer.feed(&queue);
    tokenizer.end();
    tokenizer.sink.text.into_inner()
}

fn section<'a>(sections: &'a Value, id: &str) -> Option<&'a Value> {
    rows(sections).iter().find_map(|item| {
        if item["id"] == id {
            Some(item)
        } else {
            section(&item["children"], id)
        }
    })
}

pub(super) fn verify(
    db: &Connection,
    plan: &str,
    item: &Value,
    legacy: bool,
) -> Result<Value, StorageError> {
    if !fields(
        item,
        &[
            "id",
            "original",
            "course_id",
            "lesson_id",
            "source_study_id",
            "source_block_id",
            "source_section_id",
        ],
    ) {
        return Err(invalid());
    }
    identity(&item["id"])?;
    let quote = text(&item["original"]);
    if quote.trim().is_empty() || quote.chars().count() > 20_000 {
        return Err(invalid());
    }
    let course = &item["course_id"];
    membership(db, plan, course, &Value::Null, "COURSE")?;
    let round = study_sessions::require(db, text(&item["source_study_id"]), course.as_str(), false)
        .map_err(|error| {
            if !legacy && error.code == "OBJECT_NOT_FOUND" {
                invalid()
            } else {
                error
            }
        })?;
    let lesson = rows(&round.snapshot["lessons"])
        .iter()
        .find(|lesson| lesson["id"] == item["lesson_id"])
        .ok_or_else(invalid)?;
    let quote_normal = |text: &str| {
        if legacy {
            text.split_whitespace().collect::<Vec<_>>().join(" ")
        } else {
            normalize(text)
        }
    };
    let claimed = quote_normal(quote);
    let lesson_html = text(&lesson["rendered_html"]);
    let lesson_match = quote_normal(&html_text(lesson_html, legacy)).contains(&claimed);
    let block_id = item["source_block_id"].as_str();
    let section_id = item["source_section_id"].as_str();
    let valid = match block_id.filter(|id| !id.is_empty()) {
        Some(block_id) => {
            let block = rows(&lesson["content_blocks"])
                .iter()
                .find(|block| block["id"] == block_id)
                .ok_or_else(invalid)?;
            if block["type"] == "practice" {
                legacy && lesson_match
            } else {
                let markdown = match section_id {
                    Some(id) if !id.is_empty() => presentation::source_section_markdown(
                        section(&block["sections"], id).ok_or_else(invalid)?,
                    ),
                    _ => presentation::fallback_markdown(&json!({"title":"","blocks":[block]})),
                };
                let html = documents::render(&markdown, false)?;
                (!legacy || lesson_match)
                    && quote_normal(&html_text(&html, legacy)).contains(&claimed)
            }
        }
        None if section_id.is_some_and(|id| !id.is_empty()) => false,
        None => {
            lesson_match
                || (!legacy
                    && round.snapshot["course"]["learning_mode"] == "english"
                    && rows(&lesson["exercises"]).iter().any(|exercise| {
                        quote_normal(text(&exercise["english"]["target"])) == claimed
                    }))
        }
    };
    if !valid {
        return Err(invalid());
    }
    let mut result = item.clone();
    result["course_title"] = round.snapshot["course"]["title"].clone();
    result["lesson_title"] = lesson["title"].clone();
    result["content_hash"] = json!(round.hash);
    result["verification"] = json!("VERIFIED");
    Ok(result)
}

pub(super) fn legacy(
    db: &Connection,
    plan: &str,
    blocks: &[Value],
) -> Result<(Vec<Value>, BTreeMap<String, Value>), StorageError> {
    let mut entries = Vec::with_capacity(blocks.len());
    let mut sources = BTreeMap::new();
    for block in blocks {
        let mut content = Vec::new();
        if !text(&block["quote"]).is_empty() {
            let digest = format!("{:x}", Sha256::digest(text(&block["id"]).as_bytes()));
            let id = format!("legacy-{}", &digest[..40]);
            let mut item = json!({"id":id,"original":block["quote"],"course_id":block["course_id"],"lesson_id":block["lesson_id"],"source_study_id":block["source_study_id"]});
            if !text(&block["source_block_id"]).is_empty() {
                item["source_block_id"] = block["source_block_id"].clone();
            }
            let item = match verify(db, plan, &item, false) {
                Ok(item) => item,
                Err(error) if matches!(error.code, "INVALID_ARGUMENT" | "OBJECT_NOT_FOUND") => {
                    for field in ["course_title", "lesson_title", "content_hash"] {
                        item[field] = block[field].clone();
                    }
                    item["verification"] = json!("LEGACY_UNVERIFIED");
                    item
                }
                Err(error) => return Err(error),
            };
            sources.insert(id.clone(), item);
            content.push(json!({"type":"paragraph","content":[{"type":"text","text":block["quote"],"marks":[{"type":"citation","attrs":{"sourceId":id,"occurrenceId":id}}]}]}));
        }
        if !text(&block["text"]).is_empty() {
            content
                .push(json!({"type":"paragraph","content":[{"type":"text","text":block["text"]}]}));
        }
        if content.is_empty() {
            content.push(json!({"type":"paragraph"}));
        }
        let scope = block["scope"]
            .as_str()
            .unwrap_or_else(|| scope(&block["course_id"], &block["lesson_id"]));
        entries.push(json!({"id":block["id"],"scope":scope,"course_id":block["course_id"],"lesson_id":block["lesson_id"],"course_title":block["course_title"],"lesson_title":block["lesson_title"],"content":content}));
    }
    Ok((entries, sources))
}
