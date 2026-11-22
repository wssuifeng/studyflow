use std::collections::{BTreeMap, HashSet};

use serde_json::Value;

use super::{packages::Contract, validation::*};
use crate::learning::english_check::tokens;

pub(super) const STAGES: &[&str] = &["vocabulary", "chunk", "pattern", "variation", "transfer"];

pub(super) fn validate(spec: &Value, loc: &str, contract: Contract) -> Checked<()> {
    let mut fields = vec![
        "target",
        "accepted_answers",
        "evaluation_mode",
        "case_sensitive",
        "phonetic",
        "gloss",
        "explanation",
        "objective_ids",
    ];
    if contract.revision >= 4 {
        fields.push("progression");
    }
    if contract.training() {
        fields.push("sentence_parts");
    }
    object(spec, loc, &fields, &["target"])?;
    let target = text(&spec["target"], &format!("{loc}.target"), 2000, false)?;
    let length = tokens(target).len();
    if !(1..=80).contains(&length) {
        return invalid(loc, "英语目标必须有1—80个可输入词位");
    }
    let mode = choice(
        spec.get("evaluation_mode"),
        "local_exact",
        &["local_exact", "agent"],
        loc,
        "未知评估方式",
    )?;
    if spec
        .get("case_sensitive")
        .is_some_and(|value| !value.is_boolean())
    {
        return invalid(loc, "case_sensitive必须为布尔");
    }
    for answer in default_list(
        spec.get("accepted_answers"),
        &format!("{loc}.accepted_answers"),
        12,
    )? {
        let count = tokens(text(answer, loc, 2000, false)?).len();
        if !(1..=80).contains(&count) {
            return invalid(loc, "变体必须有1—80个词位");
        }
        if !contract.training() && count != length {
            return invalid(loc, "不同词位数完整变体需要课程包/6");
        }
    }
    for key in ["phonetic", "gloss", "explanation"] {
        default_text(spec.get(key), &format!("{loc}.{key}"), 4000)?;
    }
    let mut tags = HashSet::new();
    let field = format!("{loc}.objective_ids");
    for tag in default_list(spec.get("objective_ids"), &field, 20)? {
        if !tags.insert(identifier(tag, &field)?) {
            return invalid(loc, "重复目标标签");
        }
    }
    if let Some(value) = spec.get("progression") {
        let field = format!("{loc}.progression");
        let fields = ["chain_id", "stage"];
        object(value, &field, &fields, &fields)?;
        identifier(&value["chain_id"], &format!("{field}.chain_id"))?;
        choice(
            value.get("stage"),
            "",
            STAGES,
            &format!("{field}.stage"),
            "未知递进阶段",
        )?;
    }
    if contract.training() && mode != "local_exact" {
        return invalid(
            loc,
            "英语即时训练使用local_exact；可接受表达应预录完整accepted_answers",
        );
    }
    if let Some(parts) = spec.get("sentence_parts") {
        validate_sentence(parts, loc, length)?;
    }
    Ok(())
}

fn validate_sentence(parts: &Value, loc: &str, length: usize) -> Checked<()> {
    let mut cursor = 0;
    let field = format!("{loc}.sentence_parts");
    for (index, part) in list(parts, &field, 1, 20)?.iter().enumerate() {
        let field = format!("{field}[{index}]");
        let fields = ["role", "start", "end", "words"];
        object(part, &field, &fields, &fields)?;
        choice(
            part.get("role"),
            "",
            &[
                "subject",
                "predicate",
                "object",
                "complement",
                "modifier",
                "other",
            ],
            &field,
            "未知句法角色",
        )?;
        let start = part["start"]
            .as_u64()
            .and_then(|value| usize::try_from(value).ok());
        let end = part["end"]
            .as_u64()
            .and_then(|value| usize::try_from(value).ok())
            .unwrap_or(0);
        if start != Some(cursor) || !(cursor + 1..=length).contains(&end) {
            return invalid(&field, "句法范围应连续覆盖目标词位");
        }
        for word in list(
            &part["words"],
            &format!("{field}.words"),
            end - cursor,
            end - cursor,
        )? {
            object(
                word,
                &format!("{field}.words"),
                &["phonetic", "gloss", "pos"],
                &[],
            )?;
            for key in ["phonetic", "gloss", "pos"] {
                default_text(word.get(key), &format!("{field}.{key}"), 120)?;
            }
        }
        cursor = end;
    }
    if cursor != length {
        return invalid(loc, "句法范围未完整覆盖目标词位");
    }
    Ok(())
}

pub(crate) fn validate_chains(package: &Value, required: bool) -> Checked<Vec<&str>> {
    let mut chains: BTreeMap<&str, Vec<usize>> = BTreeMap::new();
    let mut order = Vec::new();
    for lesson in package["lessons"].as_array().into_iter().flatten() {
        for exercise in lesson["exercises"].as_array().into_iter().flatten() {
            let progression = &exercise["english"]["progression"];
            if let (Some(id), Some(stage)) = (
                progression["chain_id"].as_str(),
                progression["stage"].as_str(),
            ) {
                let rank = STAGES
                    .iter()
                    .position(|&value| value == stage)
                    .expect("validated stage");
                if !chains.contains_key(id) {
                    order.push(id);
                }
                chains.entry(id).or_default().push(rank);
            } else if required {
                return invalid(
                    "english.progression",
                    "补充课程的每项训练必须声明递进链和阶段",
                );
            }
        }
    }
    if required && chains.is_empty() {
        return invalid("progression", "至少一条递进链");
    }
    for (id, stages) in chains {
        if stages.windows(2).any(|pair| pair[0] > pair[1]) {
            return invalid(
                &format!("progression.{id}"),
                "同一链必须按词汇、短语、句型、变式、迁移顺序编写",
            );
        }
        if required
            && (stages.first() != Some(&0) || stages.last() != Some(&4) || !stages.contains(&2))
        {
            return invalid(
                &format!("progression.{id}"),
                "补充链需包含必要词汇、句型与最终迁移验证",
            );
        }
    }
    Ok(order)
}
