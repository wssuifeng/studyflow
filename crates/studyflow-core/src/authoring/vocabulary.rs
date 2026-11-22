use super::{
    bounded_read, digest, error, selections, sha, without_bom, MaterialRoot, Result, Sources,
};
use crate::infrastructure::fingerprint::JsonFingerprint;
use base64::{engine::general_purpose::URL_SAFE, Engine};
use icu_casemap::CaseMapper;
use icu_normalizer::ComposingNormalizer;
use serde_json::{json, Value};
use std::collections::BTreeSet;

const TSV_FORMAT: &str = "require word/phonetic/meaning/origin columns (Chinese aliases allowed)";

pub struct Query {
    pub sources: Sources,
    pub words: Vec<String>,
    pub contains: String,
    pub browse: bool,
    pub purpose: String,
    pub limit: usize,
    pub max_chars: usize,
    pub cursor: Option<String>,
    pub exclude_selections_dir: Option<String>,
}

pub(super) fn catalog(root: &MaterialRoot, sources: &Sources) -> Result<(Vec<Value>, Vec<Value>)> {
    let source_id = regex::Regex::new(r"^[a-z][a-z0-9-]{0,63}$").unwrap();
    let mut entries = Vec::new();
    let mut declarations = Vec::new();
    let mut seen = BTreeSet::new();
    let nfc = ComposingNormalizer::new_nfc();
    if !(1..=8).contains(&sources.len()) {
        return Err(error(
            "SOURCE_ID",
            "provide one to eight explicitly named TSV sources",
        ));
    }
    for (id, relative) in sources {
        if !source_id.is_match(id) || !seen.insert(id) {
            return Err(error("SOURCE_ID", "identifiers must be unique and stable"));
        }
        let path = root.path(relative)?;
        if !path
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| {
                extension.eq_ignore_ascii_case("tsv") || extension.eq_ignore_ascii_case("txt")
            })
        {
            return Err(error(
                "SOURCE_FORMAT",
                "only explicitly selected TSV/TXT material",
            ));
        }
        let raw = bounded_read(&path, 16 * 1024 * 1024, "source exceeds 16 MiB")?;
        let mut reader = csv::ReaderBuilder::new()
            .delimiter(b'\t')
            .flexible(true)
            .from_reader(without_bom(&raw));
        let header = reader
            .headers()
            .map_err(|_| error("SOURCE_FORMAT", TSV_FORMAT))?;
        if header.iter().collect::<BTreeSet<_>>().len() != header.len() {
            return Err(error("SOURCE_FORMAT", TSV_FORMAT));
        }
        let width = header.len();
        let columns = [
            ("word", "word"),
            ("phonetic", "音标"),
            ("meaning", "释义"),
            ("origin", "来源"),
        ]
        .map(|(key, alias)| {
            header
                .iter()
                .position(|field| field == key)
                .or_else(|| header.iter().position(|field| field == alias))
        });
        let [Some(word), Some(phonetic), Some(meaning), Some(origin)] = columns else {
            return Err(error("SOURCE_FORMAT", TSV_FORMAT));
        };
        let mut words = BTreeSet::new();
        let mut identities = BTreeSet::new();
        let mut count = 0;
        for (index, record) in reader.records().enumerate() {
            let row = record.map_err(|_| error("SOURCE_FORMAT", "malformed TSV row"))?;
            if row.len() > width
                || row.len() <= *[word, phonetic, meaning, origin].iter().max().unwrap()
            {
                return Err(error("SOURCE_FORMAT", "malformed TSV row"));
            }
            let label = &row[word];
            if label.is_empty() || label != label.trim() || !words.insert(label.to_owned()) {
                return Err(error(
                    "DUPLICATE_ENTRY",
                    "blank, untrimmed or repeated source spelling",
                ));
            }
            let entry_id = format!("v-{}", &digest(&json!([id, nfc.normalize(label)]))[..32]);
            if !identities.insert(entry_id.clone()) {
                return Err(error(
                    "DUPLICATE_ENTRY",
                    "normalized source identities collide",
                ));
            }
            count += 1;
            entries.push(
                json!({"entry_id":entry_id,"source_id":id,"source_line":index+2,"word":label,
                "phonetic":&row[phonetic],"meaning":&row[meaning],"origin":&row[origin]}),
            );
        }
        declarations
            .push(json!({"id":id,"path":root.relative(&path),"sha256":sha(&raw),"records":count}));
    }
    Ok((entries, declarations))
}

fn normalized(value: &str) -> String {
    let nfkc = ComposingNormalizer::new_nfkc().normalize(value);
    CaseMapper::new()
        .fold_string(&nfkc)
        .split(|ch: char| ch.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&ch))
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

pub(super) fn query(root: &MaterialRoot, input: &Query) -> Result<Value> {
    if (input.words.is_empty() && input.contains.is_empty() && !input.browse)
        || (input.browse && input.purpose.is_empty())
    {
        return Err(error(
            "QUERY_REQUIRED",
            "specify words, a narrow text filter, or intentional browsing with a finite purpose",
        ));
    }
    if !(1..=60).contains(&input.limit) || !(1000..=32000).contains(&input.max_chars) {
        return Err(error(
            "OUTPUT_BUDGET",
            "limit 1..60 and max_chars 1000..32000",
        ));
    }
    let (entries, sources) = catalog(root, &input.sources)?;
    let words: BTreeSet<_> = input.words.iter().map(|word| normalized(word)).collect();
    let contains = normalized(&input.contains);
    let mut filters = json!({"words":words,"contains":contains,"browse":input.browse,"purpose":input.purpose,"limit":input.limit,"max_chars":input.max_chars});
    let excluded = if let Some(directory) = input
        .exclude_selections_dir
        .as_deref()
        .filter(|s| !s.is_empty())
    {
        let state = selections::selected_state(root, directory, &sources)?;
        filters["selection_fingerprint"] = json!(state.fingerprint);
        filters["selection_directory"] = json!(directory);
        state.ids
    } else {
        BTreeSet::new()
    };
    let scope = digest(&json!([sources, filters]));
    let mut offset = 0;
    if let Some(encoded) = input.cursor.as_deref().filter(|s| !s.is_empty()) {
        let invalid = || error("CURSOR_MISMATCH", "source version or query changed");
        let data = URL_SAFE.decode(encoded).map_err(|_| invalid())?;
        let cursor: Value = serde_json::from_slice(&data).map_err(|_| invalid())?;
        if cursor["scope"] != scope {
            return Err(invalid());
        }
        offset = cursor["offset"]
            .as_u64()
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(invalid)?;
    }
    let mut matches = entries
        .into_iter()
        .filter(|entry| {
            let word = entry["word"].as_str().expect("catalog word");
            let meaning = entry["meaning"].as_str().expect("catalog meaning");
            !excluded.contains(entry["entry_id"].as_str().expect("catalog id"))
                && (words.is_empty() || words.contains(&normalized(word)))
                && (contains.is_empty()
                    || normalized(&format!("{word} {meaning}")).contains(&contains))
        })
        .collect::<Vec<_>>();
    let total = matches.len();
    if offset > total {
        return Err(error("CURSOR_MISMATCH", "invalid offset"));
    }
    let size = |value: &Value| JsonFingerprint::Utf8.serialize(value).chars().count();
    let mut result = json!({"ok":true,"sources":sources,"items":[],"matched_records":total,"next_cursor":"x".repeat(192),"learning_mastery":"not_inferred"});
    for entry in matches.drain(offset..(offset + input.limit).min(total)) {
        result["items"].as_array_mut().unwrap().push(entry);
        if size(&result) > input.max_chars {
            let page = result["items"].as_array_mut().unwrap();
            page.pop();
            if page.is_empty() {
                return Err(error(
                    "OUTPUT_BUDGET",
                    "one entry cannot fit; increase budget, never truncate its definition",
                ));
            }
            break;
        }
    }
    let following = offset + result["items"].as_array().unwrap().len();
    result["next_cursor"] = if following < total {
        json!(URL_SAFE.encode(format!(r#"{{"scope":"{scope}","offset":{following}}}"#)))
    } else {
        Value::Null
    };
    if size(&result) > input.max_chars {
        return Err(error("OUTPUT_BUDGET", "response metadata exceeds budget"));
    }
    Ok(result)
}
