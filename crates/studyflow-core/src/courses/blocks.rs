use std::collections::HashSet;

use serde_json::Value;

use super::{packages::Contract, validation::*};

pub(super) fn validate(
    blocks: &Value,
    field: &str,
    contract: Contract,
    exercise_ids: &HashSet<&str>,
) -> Checked<()> {
    let mut seen = HashSet::new();
    for (index, block) in list(blocks, field, 1, 80)?.iter().enumerate() {
        let loc = format!("{field}[{index}]");
        let kind = block["type"].as_str().unwrap_or_default();
        let (extra, required): (&[&str], &[&str]) = match kind {
            "details" if contract.revision < 3 => return invalid(&loc, "折叠详解需要课程包/3"),
            "details" => (&["summary", "body"], &["summary", "body"]),
            "concept" if contract.revision >= 5 => {
                if block.get("body").is_some() == block.get("sections").is_some() {
                    return invalid(&loc, "concept必须二选一body或sections");
                }
                (&["body", "sections"], &[])
            }
            "concept" => (&["body"], &["body"]),
            "comparison" => (&["columns", "rows"], &["columns", "rows"]),
            "steps" | "summary" => (&["items"], &["items"]),
            "example" => (
                &["given", "steps", "conclusion"],
                &["given", "steps", "conclusion"],
            ),
            "callout" => (&["body", "tone"], &["body"]),
            "practice" => (&["exercise_ids"], &["exercise_ids"]),
            _ => return invalid(&loc, "未知内容块类型"),
        };
        let base = ["id", "type", "title"];
        object(
            block,
            &loc,
            &[&base[..], extra].concat(),
            &[&base[..], required].concat(),
        )?;
        if let Some(sections) = block.get("sections") {
            let field = format!("{loc}.sections");
            let mut ids = HashSet::new();
            let chars = validate_sections(sections, &field, &field, 1, &mut ids)?;
            if chars > 20_000 {
                return invalid(&field, "摘要和正文合计最多20000字符");
            }
        }
        let id = identifier(&block["id"], &format!("{loc}.id"))?;
        text(&block["title"], &format!("{loc}.title"), 200, false)?;
        if !seen.insert(id) {
            return invalid(&loc, "重复内容块id");
        }
        if let Some(body) = block.get("body") {
            text(body, &format!("{loc}.body"), 20_000, false)?;
        }
        match kind {
            "details" => {
                text(&block["summary"], &format!("{loc}.summary"), 3000, false)?;
            }
            "callout" => {
                choice(
                    block.get("tone"),
                    "note",
                    &["note", "warning", "tip"],
                    &loc,
                    "未知提醒类型",
                )?;
            }
            "comparison" => validate_table(block, &loc)?,
            "steps" | "example" => {
                let key = if kind == "steps" { "items" } else { "steps" };
                for step in list(&block[key], &format!("{loc}.steps"), 1, 20)? {
                    object(
                        step,
                        &format!("{loc}.step"),
                        &["title", "body"],
                        &["title", "body"],
                    )?;
                    text(&step["title"], &loc, 200, false)?;
                    text(&step["body"], &loc, 20_000, false)?;
                }
                if kind == "example" {
                    for key in ["given", "conclusion"] {
                        text(&block[key], &format!("{loc}.{key}"), 20_000, false)?;
                    }
                }
            }
            "summary" => {
                for item in list(&block["items"], &format!("{loc}.items"), 1, 20)? {
                    text(item, &loc, 3000, false)?;
                }
            }
            "practice" => {
                let field = format!("{loc}.exercise_ids");
                let mut refs = HashSet::new();
                for reference in list(&block["exercise_ids"], &field, 1, 100)? {
                    let id = identifier(reference, &field)?;
                    if !exercise_ids.contains(id) {
                        return invalid(&loc, format!("引用不存在的题目 {id}"));
                    }
                    if !refs.insert(id) {
                        return invalid(&loc, "重复题目引用");
                    }
                }
            }
            _ => {}
        }
    }
    Ok(())
}

fn validate_table(block: &Value, loc: &str) -> Checked<()> {
    let cols = list(&block["columns"], &format!("{loc}.columns"), 2, 6)?;
    for col in cols {
        text(col, &format!("{loc}.columns"), 200, false)?;
    }
    let field = format!("{loc}.rows");
    for row in list(&block["rows"], &field, 1, 50)? {
        for cell in list(row, &field, cols.len(), cols.len())? {
            text(cell, &format!("{loc}.cell"), 3000, true)?;
        }
    }
    Ok(())
}

fn validate_sections<'a>(
    items: &'a Value,
    field: &str,
    root: &str,
    depth: usize,
    ids: &mut HashSet<&'a str>,
) -> Checked<usize> {
    let mut chars = 0;
    for (index, item) in list(items, field, 1, 40)?.iter().enumerate() {
        let loc = format!("{field}[{index}]");
        object(
            item,
            &loc,
            &["id", "title", "role", "body", "summary", "children"],
            &["id", "title", "role", "body"],
        )?;
        let id = identifier(&item["id"], &format!("{loc}.id"))?;
        text(&item["title"], &format!("{loc}.title"), 200, false)?;
        if !ids.insert(id) {
            return invalid(&loc, "重复小节id");
        }
        if ids.len() > 40 {
            return invalid(root, "每块最多40个小节");
        }
        let role = choice(
            item.get("role"),
            "",
            &["main", "supplement"],
            &loc,
            "小节角色仅main/supplement",
        )?;
        chars += text(&item["body"], &format!("{loc}.body"), 20_000, false)?
            .chars()
            .count();
        if role == "supplement" || item.get("summary").is_some() {
            chars += text(&item["summary"], &format!("{loc}.summary"), 3000, false)?
                .chars()
                .count();
        }
        if let Some(children) = item.get("children") {
            if depth == 2 {
                return invalid(&loc, "小节最多两层");
            }
            chars += validate_sections(children, &format!("{loc}.children"), root, depth + 1, ids)?;
        }
    }
    Ok(chars)
}
