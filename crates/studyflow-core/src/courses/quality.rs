use std::collections::{BTreeMap, BTreeSet};
use std::sync::LazyLock;

use regex::Regex;
use serde_json::{json, Value};

use super::groups::normalize_answer;
use crate::{audio::assets::digest, infrastructure::fingerprint::JsonFingerprint};

const RULE_VERSION: &str = "authoring-quality/4";
const CLASSES: [&str; 5] = [
    "deterministic_error",
    "content_defect",
    "review_required",
    "presentation_defect",
    "advisory",
];

pub struct Options<'a> {
    pub blueprint: Option<&'a Value>,
    pub sources: Option<&'a Value>,
    pub related: &'a [Value],
    pub validation_receipt: Option<&'a Value>,
    pub rendering_receipt: Option<&'a Value>,
    pub long_section_chars: usize,
}

impl Default for Options<'_> {
    fn default() -> Self {
        Self {
            blueprint: None,
            sources: None,
            related: &[],
            validation_receipt: None,
            rendering_receipt: None,
            long_section_chars: 400,
        }
    }
}

#[derive(Default)]
struct EnglishMetrics {
    items: usize,
    tokens: usize,
    annotated: usize,
    annotated_phonetic: usize,
    phonetic: usize,
    short: usize,
    stages: BTreeMap<String, usize>,
    targets: BTreeMap<String, usize>,
    hashes: Vec<Value>,
    structure: Vec<Value>,
}

#[derive(Default)]
struct Report {
    notes: Vec<Value>,
    english: EnglishMetrics,
    sections: usize,
    exercise_locations: Vec<(String, Value)>,
    teaching_ids: BTreeSet<String>,
}

pub fn analyze(package: &Value, package_sha256: &str, options: Options<'_>) -> Value {
    let lessons = rows(&package["lessons"]);
    let related: Vec<_> = options
        .related
        .iter()
        .flat_map(|package| rows(&package["lessons"]))
        .flat_map(|lesson| rows(&lesson["exercises"]))
        .map(|exercise| &exercise["english"])
        .filter(|item| present(item))
        .collect();
    let mut report = Report::default();
    for (index, lesson) in lessons.iter().enumerate() {
        let loc = format!("/lessons/{index}");
        report.lesson(
            lesson,
            &loc,
            package["schema"].as_str().unwrap_or_default(),
            options.long_section_chars,
            &related,
        );
    }
    let blueprint = options.blueprint.filter(|value| present(value));
    if let Some(blueprint) = blueprint {
        report.blueprint(blueprint);
    }
    let english = &report.english;
    let duplicate_targets: BTreeMap<_, _> = english
        .targets
        .iter()
        .filter(|(_, count)| **count > 1)
        .collect();
    let cross_course: BTreeSet<_> = related
        .iter()
        .map(|item| normalized(s(&item["target"])))
        .filter(|target| english.targets.contains_key(target))
        .collect();
    let mut metrics = json!({
        "lessons": lessons.len(), "exercises": report.exercise_locations.len(), "sections": report.sections,
        "english_items": english.items, "english_tokens": english.tokens, "annotated_words": english.annotated,
        "annotated_phonetic_words": english.annotated_phonetic, "item_phonetics": english.phonetic,
        "short_items_1_to_3_tokens": english.short, "declared_stages": english.stages,
        "semantic_frames": "not_inferred", "duplicate_targets": duplicate_targets,
        "short_item_denominator": english.items, "cross_course_exact_reuse": cross_course,
    });
    if let Some(blueprint) = blueprint {
        metrics["declared_frames"] = blueprint
            .get("frames")
            .cloned()
            .unwrap_or_else(|| json!([]));
    }
    let validation = receipt_status(options.validation_receipt, package_sha256);
    let rendering = receipt_status(options.rendering_receipt, package_sha256);
    let mut scope = vec![
        "Deterministic structural and lexical triggers only; semantic conclusions stay with human review",
        "Reference answer presence, placeholder patterns and whole-answer leak in learner-visible fields",
        "Variant duplicate normalization plus punctuation/case and token-count structure candidates",
        "Section hierarchy length threshold and main/supplement composition",
        "English role projection with authored POS, gloss senses, authored phonetics and prompt language",
        "Receipt binding of every provided slot to the package SHA-256",
    ];
    if blueprint.is_some() {
        scope.push("Blueprint objective references and exercise mapping");
    }
    if !options.related.is_empty() {
        scope
            .push("Cross-course exact reuse and near-template candidates against related packages");
    }
    let conclusion: BTreeMap<_, _> = CLASSES
        .into_iter()
        .map(|class| {
            let matching: Vec<_> = report
                .notes
                .iter()
                .filter(|note| note["classification"] == class)
                .collect();
            let rules: BTreeSet<_> = matching
                .iter()
                .filter_map(|note| note["rule"].as_str())
                .collect();
            (class, json!({"count": matching.len(), "rules": rules}))
        })
        .collect();
    let blocked = conclusion["deterministic_error"]["count"] != 0;
    let mut output = json!({
        "report_schema": "studyflow.authoring-quality/2", "rule_version": RULE_VERSION,
        "package_sha256": package_sha256, "protocol_validation": validation,
        "source_verification": if options.sources.is_some_and(present) { "declared_not_verified" } else { "not_provided" },
        "blueprint_provided": blueprint.is_some(), "metrics": metrics, "advisories": report.notes,
        "english_structure_review": english.structure, "teaching_chain_list": teaching_chains(lessons),
        "conclusion_summary": conclusion,
        "capability_config": {"rule_version": RULE_VERSION, "options": {"long_section_chars": options.long_section_chars}},
        "semantic_ids": {"package_id": package["package_id"],
            "lesson_ids": lessons.iter().map(|lesson| &lesson["id"]).collect::<Vec<_>>(),
            "exercise_ids": report.exercise_locations.iter().map(|(_, id)| id).collect::<Vec<_>>()},
        "target_hashes": english.hashes, "checked_scope": scope,
        "publication_gate": {"protocol": validation, "content": null, "rendering": rendering, "writeback": "not_provided"},
        "manual_review_required": ["fact_accuracy", "teaching_alignment", "variant_equivalence", "phonetic_accuracy_and_license", "real_rendering", "role_span_alignment", "independent_expression"],
        "semantic_acceptance": "not_evaluated", "blocked": blocked,
        "unchecked_scope": ["No live workspace queried", "No schema validator reimplemented", "Similarity is not semantic frame inference", "Optional empty phonetics are not errors", "No learner mastery evaluated"],
    });
    let hash = JsonFingerprint::CompactUtf8.hash(&output);
    output["publication_gate"]["content"] = json!({"status": "self_reference", "report_sha256": hash,
        "reconstruction": "SHA-256 of this report serialized with publication_gate.content=null (json.dumps sort_keys=True, ensure_ascii=False, separators=(',',':'))"});
    output
}

impl Report {
    fn warn(&mut self, rule: &str, path: &str, evidence: Value) {
        let classification = match rule {
            "LONG_SECTION_REVIEW" => "advisory",
            "DUPLICATE_VARIANT" | "BLUEPRINT_REFERENCE_MISSING" => "deterministic_error",
            _ => "review_required",
        };
        self.notes.push(json!({"rule": rule, "path": path, "evidence": evidence, "classification": classification}));
    }

    fn lesson(
        &mut self,
        lesson: &Value,
        loc: &str,
        schema: &str,
        threshold: usize,
        related: &[&Value],
    ) {
        let blocks = rows(&lesson["blocks"]);
        let mut titles = BTreeMap::new();
        for (index, block) in blocks.iter().enumerate() {
            self.teaching_ids.insert(s(&block["id"]).into());
            *titles.entry(normalized(s(&block["title"]))).or_insert(0) += 1;
            let path = format!("{loc}/blocks/{index}/sections");
            let sections = rows(&block["sections"]);
            let mut roles = Vec::new();
            let count = self.sections(sections, &path, threshold, &mut roles);
            if count != 0 && !roles.iter().any(|role| role == "main") {
                self.warn("MISSING_MAIN_SECTION", &path, json!({"sections": count, "roles": roles,
                    "action": "All sections are supplement/collapsed with no role=main backbone; review solvability, not a semantic verdict"}));
            }
        }
        for (title, count) in titles {
            if !title.is_empty() && count > 1 {
                self.warn(
                    "REPEATED_BLOCK_TITLE",
                    loc,
                    json!({"title": title, "count": count}),
                );
            }
        }
        for (index, exercise) in rows(&lesson["exercises"]).iter().enumerate() {
            let path = format!("{loc}/exercises/{index}");
            self.exercise_locations
                .push((path.clone(), exercise["id"].clone()));
            self.references(exercise, blocks, loc, &path, schema);
            if present(&exercise["english"]) {
                self.english(exercise, &path, related);
            }
        }
    }

    fn sections(
        &mut self,
        rows_here: &[Value],
        loc: &str,
        threshold: usize,
        roles: &mut Vec<Value>,
    ) -> usize {
        let mut count = rows_here.len();
        self.sections += count;
        for (index, section) in rows_here.iter().enumerate() {
            let path = format!("{loc}/{index}");
            self.teaching_ids.insert(s(&section["id"]).into());
            if !roles.contains(&section["role"]) {
                roles.push(section["role"].clone());
            }
            let size = s(&section["body"]).chars().count();
            if size > threshold {
                self.warn("LONG_SECTION_REVIEW", &path, json!({"characters": size, "threshold": threshold, "action": "Review hierarchy, not automatic splitting"}));
            }
            count += self.sections(
                rows(&section["children"]),
                &format!("{path}/children"),
                threshold,
                roles,
            );
        }
        count
    }

    fn references(
        &mut self,
        exercise: &Value,
        blocks: &[Value],
        lesson: &str,
        loc: &str,
        schema: &str,
    ) {
        let answer = s(&exercise["review_reference"]["answer"]);
        let local_group = matches!(
            schema,
            "studyflow.course-package/7" | "studyflow.course-package/8"
        ) && matches!(
            exercise["type"].as_str(),
            Some("READING_GROUP" | "LISTENING_GROUP")
        );
        static PLACEHOLDER: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"(?i)TODO|TBD|待补|原理对比[；;]|^写出.{0,12}步骤$").unwrap()
        });
        if answer.trim().is_empty() && !local_group {
            self.warn(
                "REFERENCE_MISSING",
                &format!("{loc}/review_reference"),
                json!({"legacy_schema_may_allow_missing": true}),
            );
        } else if PLACEHOLDER.is_match(answer) {
            self.warn(
                "REFERENCE_PLACEHOLDER",
                &format!("{loc}/review_reference/answer"),
                json!({"excerpt": answer.chars().take(160).collect::<String>()}),
            );
        }
        let prompt = s(&exercise["prompt"]);
        let visible = format!("{prompt}\n{}", s(&exercise["requirements"]));
        let answer = normalized(answer);
        if answer.chars().count() >= 12 && normalized(&visible).contains(&answer) {
            self.warn("POSSIBLE_ANSWER_LEAK", loc, json!({"reason":"Whole reference is present in learner-visible fields; inspect context"}));
        }
        static NUMBERS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\d+(?:\.\d+)?").unwrap());
        let numbers: Vec<_> = NUMBERS.find_iter(prompt).map(|m| m.as_str()).collect();
        if numbers.len() > 1 {
            for (index, block) in blocks
                .iter()
                .enumerate()
                .filter(|(_, block)| block["type"] == "example")
            {
                if numbers
                    .iter()
                    .copied()
                    .eq(NUMBERS.find_iter(s(&block["given"])).map(|m| m.as_str()))
                {
                    self.warn("EXAMPLE_REHEARSAL_CANDIDATE", loc, json!({"example_path": format!("{lesson}/blocks/{index}"), "shared_numbers": numbers, "not_a_semantic_verdict": true}));
                }
            }
        }
    }

    fn blueprint(&mut self, blueprint: &Value) {
        let ids: BTreeSet<_> = self
            .exercise_locations
            .iter()
            .map(|(_, id)| s(id).to_owned())
            .collect();
        let mut referenced = BTreeSet::new();
        for (index, objective) in rows(&blueprint["objectives"]).iter().enumerate() {
            let exercise_ids = rows(&objective["exercise_ids"]);
            let missing: Vec<_> = exercise_ids
                .iter()
                .filter(|id| !ids.contains(s(id)))
                .collect();
            let missing_teaching: Vec<_> = rows(&objective["teaching_ids"])
                .iter()
                .filter(|id| !self.teaching_ids.contains(s(id)))
                .collect();
            referenced.extend(exercise_ids.iter().map(s));
            if !missing.is_empty() || !missing_teaching.is_empty() {
                self.warn(
                    "BLUEPRINT_REFERENCE_MISSING",
                    &format!("/blueprint/objectives/{index}"),
                    json!({"exercise_ids": missing, "teaching_ids": missing_teaching}),
                );
            }
        }
        let unmapped: Vec<_> = self
            .exercise_locations
            .iter()
            .filter(|(_, id)| !referenced.contains(s(id)))
            .cloned()
            .collect();
        for (path, id) in unmapped {
            self.warn("UNMAPPED_EXERCISE", &path, json!({"exercise_id": id, "action": "No blueprint objective references this exercise; confirm placement or extend the blueprint"}));
        }
    }
}

fn normalized(text: &str) -> String {
    normalize_answer(text)
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim_matches(['.', ',', '!', '?', ';', '。', '！', '？'])
        .to_owned()
}

fn s(value: &Value) -> &str {
    value.as_str().unwrap_or_default()
}
fn rows(value: &Value) -> &[Value] {
    value.as_array().map_or(&[], Vec::as_slice)
}
fn present(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Object(fields) => !fields.is_empty(),
        Value::Array(items) => !items.is_empty(),
        Value::String(text) => !text.is_empty(),
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64() != Some(0.0),
    }
}
fn receipt_status(receipt: Option<&Value>, hash: &str) -> &'static str {
    match receipt.filter(|value| present(value)) {
        None => "not_provided",
        Some(receipt) if receipt["package_sha256"] != hash => "unbound_receipt",
        Some(receipt) if receipt["result"]["ok"] == true => "passed",
        Some(_) => "failed",
    }
}

fn teaching_chains(lessons: &[Value]) -> Vec<Value> {
    lessons.iter().map(|lesson| {
        let mut chains: Vec<Value> = Vec::new();
        let mut without = Vec::new();
        for exercise in rows(&lesson["exercises"]).iter().filter(|item| present(&item["english"])) {
            let progression = &exercise["english"]["progression"];
            let id = &progression["chain_id"];
            if !present(id) { without.push(exercise["id"].clone()); continue; }
            let index = chains.iter().position(|chain| chain["chain_id"] == *id).unwrap_or_else(|| {
                chains.push(json!({"chain_id": id, "stage_sequence": [], "items": []}));
                chains.len() - 1
            });
            let stage = &progression["stage"];
            chains[index]["stage_sequence"].as_array_mut().unwrap().push(stage.clone());
            chains[index]["items"].as_array_mut().unwrap().push(json!({"exercise_id": exercise["id"], "stage": stage}));
        }
        json!({"lesson_id": lesson["id"], "chains": chains, "english_exercises_without_chain": without})
    }).collect()
}

impl Report {
    fn english(&mut self, exercise: &Value, loc: &str, related: &[&Value]) {
        let item = &exercise["english"];
        let target = s(&item["target"]);
        let prompt = s(&exercise["prompt"]);
        let tokens: Vec<_> = target.split_whitespace().collect();
        let stage = &item["progression"]["stage"];
        let parts = rows(&item["sentence_parts"]);
        self.english.items += 1;
        self.english.tokens += tokens.len();
        *self.english.targets.entry(normalized(target)).or_default() += 1;
        self.english.short += usize::from(tokens.len() <= 3);
        self.english.phonetic += usize::from(present(&item["phonetic"]));
        *self
            .english
            .stages
            .entry(stage.as_str().unwrap_or("undeclared").into())
            .or_default() += 1;
        let latin = prompt.bytes().any(|byte| byte.is_ascii_alphabetic());
        let cjk = prompt
            .chars()
            .any(|ch| matches!(ch, '\u{3400}'..='\u{4dbf}' | '\u{4e00}'..='\u{9fff}'));
        if prompt.trim().is_empty() || (latin && !cjk) {
            self.warn("ENGLISH_PROMPT_LANGUAGE_REVIEW", &format!("{loc}/prompt"), json!({
                "reason": if prompt.trim().is_empty() { "empty_prompt" } else { "same_language_as_target" },
                "prompt_excerpt": prompt.chars().take(80).collect::<String>(),
                "action": "English items need a distinct Chinese prompt; review empty or same-language prompts",
            }));
        }
        let projected = self.project(parts, &tokens, loc);
        self.english.structure.push(json!({"exercise_id": exercise["id"], "path": loc, "prompt": prompt,
            "target": target, "stage": stage, "parts": projected, "semantic_acceptance": "not_evaluated"}));
        if stage == "chunk" && (prompt.contains("__") || prompt.contains("＿＿")) {
            self.warn("FRAGMENT_INDEPENDENCE_REVIEW", &format!("{loc}/english/target"), json!({"target": target,
                "action": "Read the answer without its blank-filling carrier. Prefer a natural base-form phrase or a complete simple sentence; explicit contextual drills must not masquerade as independent expressions", "not_a_grammar_verdict": true}));
        }
        if matches!(stage.as_str(), Some("vocabulary" | "chunk"))
            && parts.iter().any(|part| part["role"] != "other")
        {
            self.warn("FRAGMENT_ROLE_CONTEXT_REVIEW", &format!("{loc}/english/sentence_parts"), json!({"stage": stage,
                "action": "Distinguish phrase structure from clause function; supply the actual sentence context, not an inferred role"}));
        }
        self.word_notes(parts, s(&item["phonetic"]), loc);
        let variants: Vec<_> = std::iter::once(target)
            .chain(rows(&item["accepted_answers"]).iter().map(s))
            .collect();
        self.variants(&variants, loc);
        self.near_templates(target, stage, related, loc);
        let mut ordered = variants;
        ordered.sort_unstable();
        self.english.hashes.push(
            json!({"exercise_id": exercise["id"], "target_sha256": digest(target.as_bytes()),
            "variants_sha256": JsonFingerprint::Utf8.hash(&json!(ordered))}),
        );
    }

    fn project(&mut self, parts: &[Value], tokens: &[&str], loc: &str) -> Vec<Value> {
        parts.iter().enumerate().map(|(index, part)| {
            static AUX: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\b(?:aux\.|modal\b)|助动词|情态动词").unwrap());
            static POS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\b(?:n|v|vt|vi|aux|adj|adv|prep|pron|det|conj)\.|\bmodal\b|动词|名词|形容词|副词|介词|代词|限定词|连词").unwrap());
            static VERB: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\b(?:v|vt|vi|aux)\.|\bmodal\b|动词").unwrap());
            static PREP: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\bprep\.").unwrap());
            let span = match (part["start"].as_i64(), part["end"].as_i64()) {
                (Some(start), Some(end)) => {
                    let limit = tokens.len() as i64;
                    let index = |n: i64| (if n < 0 { limit + n } else { n }).clamp(0, limit) as usize;
                    tokens.get(index(start)..index(end)).unwrap_or_default().join(" ")
                }
                _ => String::new(),
            };
            let labels: Vec<_> = rows(&part["words"]).iter().map(|word| s(&word["pos"]).trim().to_lowercase()).collect();
            let reason = match part["role"].as_str() {
                Some("subject") if labels.iter().any(|pos| AUX.is_match(pos)) => Some("A subject span includes an authored auxiliary/modal POS; inspect the actual clause boundary"),
                Some("predicate") if !labels.is_empty() && labels.iter().all(|pos| POS.is_match(pos))
                    && !labels.iter().any(|pos| VERB.is_match(pos)) => Some("The predicate span has no authored verbal POS; verify both the role and POS"),
                Some("object") if labels.last().is_some_and(|pos| PREP.is_match(pos)) => Some("The object span ends at an authored preposition; inspect whether a following phrase was cut"),
                _ => None,
            };
            if let Some(reason) = reason {
                self.warn("ROLE_POS_CONFLICT_REVIEW", &format!("{loc}/english/sentence_parts/{index}"),
                    json!({"text": span, "role": part["role"], "authored_pos": labels, "action": reason, "not_a_grammar_verdict": true}));
            }
            json!({"role": part["role"], "start": part["start"], "end": part["end"], "text": span, "word_pos": labels})
        }).collect()
    }

    fn word_notes(&mut self, parts: &[Value], phonetic: &str, loc: &str) {
        static POS_IN_GLOSS: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"(?i)\b(?:n|v|vt|vi|adj|adv|prep|pron|det|conj)\.").unwrap()
        });
        let mut missing = Vec::new();
        for (part_index, part) in parts.iter().enumerate() {
            for (word_index, word) in rows(&part["words"]).iter().enumerate() {
                self.english.annotated += 1;
                if s(&word["phonetic"]).trim().is_empty() {
                    let start = part["start"].as_i64().unwrap_or(0);
                    missing.push(start.saturating_add(word_index as i64));
                } else {
                    self.english.annotated_phonetic += 1;
                }
                let gloss = s(&word["gloss"]);
                let chars = gloss.chars().count();
                if chars > 48
                    || POS_IN_GLOSS.find_iter(gloss).take(2).count() >= 2
                    || gloss.matches([';', '；']).take(3).count() >= 3
                {
                    let path = format!(
                        "{loc}/english/sentence_parts/{part_index}/words/{word_index}/gloss"
                    );
                    self.warn("WORD_GLOSS_SENSE_REVIEW", &path, json!({"characters": chars,
                        "action": "Author one concise sense and POS for this context; do not select dictionary senses automatically"}));
                }
            }
        }
        if phonetic.trim().is_empty() && (parts.is_empty() || !missing.is_empty()) {
            self.warn("AUTHOR_PHONETIC_REVIEW", &format!("{loc}/english"), json!({"missing_word_indices": missing,
                "action": "Author and verify phonetics with accent/context notes; runtime lookup is not a course-authoring substitute", "optional_in_protocol": true}));
        }
    }

    fn variants(&mut self, variants: &[&str], loc: &str) {
        let path = format!("{loc}/english");
        let mut seen = BTreeSet::new();
        for (index, value) in variants.iter().enumerate() {
            if !seen.insert(normalized(value)) {
                self.warn("DUPLICATE_VARIANT", &path, json!({"variant_index": index}));
            }
        }
        let target = variants[0];
        if target.trim().is_empty() {
            return;
        }
        let count = target.split_whitespace().count();
        for (index, variant) in variants.iter().enumerate().skip(1) {
            let variant_count = variant.split_whitespace().count();
            let reason = if count != variant_count {
                "token_count"
            } else if normalized(target) != normalized(variant)
                && structural_key(target) == structural_key(variant)
            {
                "punctuation_or_case"
            } else {
                continue;
            };
            self.warn("VARIANT_STRUCTURE_CANDIDATE", &path, json!({"variant_index": index, "reason": reason,
                "target_tokens": count, "variant_tokens": variant_count,
                "action": "Review whether this structural difference keeps the variant equivalent to the target; not a semantic verdict"}));
        }
    }

    fn near_templates(&mut self, target: &str, stage: &Value, related: &[&Value], loc: &str) {
        let current = normalize_answer(target);
        let mut count = BTreeMap::<&str, usize>::new();
        let mut total = 0;
        for word in current.split_whitespace() {
            *count.entry(word).or_default() += 1;
            total += 1;
        }
        if total == 0 {
            return;
        }
        for item in related
            .iter()
            .filter(|item| &item["progression"]["stage"] == stage)
        {
            let other_target = s(&item["target"]);
            let other = normalize_answer(other_target);
            let mut other_count = BTreeMap::<&str, usize>::new();
            let mut other_total = 0;
            for word in other.split_whitespace() {
                *other_count.entry(word).or_default() += 1;
                other_total += 1;
            }
            if total != other_total {
                continue;
            }
            let shared: usize = count
                .iter()
                .map(|(word, n)| *n.min(other_count.get(word).unwrap_or(&0)))
                .sum();
            let ratio = shared as f64 / total as f64;
            if ratio >= 0.6 {
                self.warn("NEAR_TEMPLATE_CANDIDATE", loc, json!({"related_target": other_target, "stage": stage,
                    "shared_tokens": shared, "total_tokens": total, "ratio": ratio,
                    "action": "Same stage and token count with high token overlap against a related package; review template reuse"}));
            }
        }
    }
}

fn structural_key(text: &str) -> String {
    static IGNORE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[\p{P}\p{S}]").unwrap());
    let normalized = normalize_answer(text);
    IGNORE
        .replace_all(&normalized, "")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}
