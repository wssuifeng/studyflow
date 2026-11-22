use icu_casemap::CaseMapper;
use icu_normalizer::ComposingNormalizer;
use serde_json::{json, Value};

use crate::infrastructure::{fingerprint::JsonFingerprint, StorageError};

pub const VERSION: &str = "english-exact/1";

pub fn tokens(text: &str) -> Vec<String> {
    ComposingNormalizer::new_nfkc()
        .normalize(text)
        .replace('’', "'")
        .split(|ch: char| ch.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&ch))
        .map(|word| word.trim_matches(['.', ',', '!', '?', ';', ':', '"', '(', ')', '[', ']']))
        .filter(|word| !word.is_empty())
        .map(str::to_owned)
        .collect()
}

pub(crate) fn variants(reference: &Value) -> impl Iterator<Item = &str> {
    reference["target"].as_str().into_iter().chain(
        reference["accepted_answers"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str),
    )
}

fn closest<'a>(reference: &'a Value, answer: &str) -> Result<(&'a str, Vec<Value>), StorageError> {
    if reference
        .get("checker_version")
        .is_some_and(|version| version != VERSION)
    {
        return Err(StorageError::new("ENGLISH_CHECKER_UNSUPPORTED"));
    }
    let actual = tokens(answer);
    let case_sensitive = reference["case_sensitive"].as_bool().unwrap_or(false);
    let fold = CaseMapper::new();
    let differences = |candidate: &str| {
        let expected = tokens(candidate);
        (0..actual.len().max(expected.len())).filter_map(|index| {
            let a=actual.get(index).map(String::as_str);
            let b=expected.get(index).map(String::as_str);
            let same=match (a,b) { (Some(a),Some(b)) if !case_sensitive => fold.fold_string(a)==fold.fold_string(b),_=>a==b };
            (!same).then(||json!({"index":index,"actual":a.unwrap_or_default(),"expected":b.unwrap_or_default()}))
        }).collect::<Vec<_>>()
    };
    variants(reference)
        .map(|candidate| (candidate, differences(candidate)))
        .min_by_key(|(_, items)| items.len())
        .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))
}

pub fn matched_variant<'a>(
    reference: &'a Value,
    answer: &str,
) -> Result<Option<&'a str>, StorageError> {
    let (variant, differences) = closest(reference, answer)?;
    Ok(differences.is_empty().then_some(variant))
}

pub(crate) fn evaluate(reference: &Value, answer: &str) -> Result<Value, StorageError> {
    let (variant, differences) = closest(reference, answer)?;
    let matched = differences.is_empty();
    Ok(
        json!({"matched":matched,"differences":differences,"matched_variant":matched.then_some(variant),"checker_version":VERSION}),
    )
}

pub(crate) fn rule_hash(spec: &Value, prompt: &str) -> String {
    let relevant = json!({"target":spec["target"].as_str().unwrap_or_default(),"accepted_answers":spec["accepted_answers"].as_array().map(Vec::as_slice).unwrap_or_default(),
        "case_sensitive":spec["case_sensitive"].as_bool().unwrap_or(false),"evaluation_mode":spec["evaluation_mode"].as_str().unwrap_or("local_exact")});
    JsonFingerprint::Utf8.hash(&json!({"spec":relevant,"prompt":prompt,"checker":spec["checker_version"].as_str().unwrap_or(VERSION)}))
}
