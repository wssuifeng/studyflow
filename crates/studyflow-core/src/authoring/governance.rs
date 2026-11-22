use super::{bounded_read, digest, error, nonblank, text, utf8, MaterialRoot, Result};
use serde_json::{json, Value};
use std::{collections::BTreeSet, fs};

pub(super) fn audit(root: &MaterialRoot, config: &str) -> Result<Value> {
    let config = root.json(config)?;
    if config["format"] != 1 || !nonblank(&config["current_stage_id"]) {
        return Err(error(
            "FORMAT",
            "governance format and explicit current stage required",
        ));
    }
    let keys = ["state_file", "stage_file", "index_file"];
    let paths = keys
        .iter()
        .map(|key| root.path(text(&config, key)?))
        .collect::<Result<Vec<_>>>()?;
    if paths.iter().collect::<BTreeSet<_>>().len() != 3 {
        return Err(error(
            "FORMAT",
            "state/stage/index responsibilities must be explicit and distinct",
        ));
    }
    if config.get("max_chars").is_some_and(|budgets| {
        !budgets.as_object().is_some_and(|entries| {
            entries
                .values()
                .all(|value| value.as_u64().is_some_and(|n| n > 0))
        })
    }) {
        return Err(error("FORMAT", "invalid character budgets"));
    }
    let mut issues = Vec::new();
    let mut checked = Vec::new();
    let mut issue = |code: &str, path: &str| issues.push(json!({"code":code,"path":path}));
    let links = regex::Regex::new(r"\[[^\]]*\]\(([^)]+)\)").unwrap();
    let external = regex::Regex::new(r"^[A-Za-z][A-Za-z0-9+.-]*://").unwrap();
    for (key, path) in keys.into_iter().zip(&paths) {
        let relative = root.relative(path);
        checked.push(relative.clone());
        if !path.is_file() {
            issue("MISSING_ENTRY", &relative);
            continue;
        }
        if fs::metadata(path)?.len() > 262144 {
            issue("SIZE_BUDGET", &relative);
            continue;
        }
        let bytes = bounded_read(path, 262144, "split the selected input")?;
        let content = utf8(&bytes)?.replace("\r\n", "\n").replace('\r', "\n");
        let budget = config["max_chars"][&relative]
            .as_u64()
            .unwrap_or(if key == "stage_file" { 64000 } else { 5000 });
        if content.chars().count() as u64 > budget {
            issue("SIZE_BUDGET", &relative);
        }
        if path
            .extension()
            .is_some_and(|extension| extension.eq_ignore_ascii_case("md"))
        {
            for link in links.captures_iter(&content) {
                let target = link[1]
                    .split('#')
                    .next()
                    .unwrap()
                    .trim()
                    .trim_matches(['<', '>']);
                if target.is_empty() || external.is_match(target) {
                    continue;
                }
                if !root.path(path.parent().unwrap().join(target))?.exists() {
                    issue("BROKEN_LINK", &relative);
                }
            }
        }
    }
    let stage = &paths[1];
    if stage.is_file() && fs::metadata(stage)?.len() <= 262144 {
        let stage = root.json(stage)?;
        let stage_file = text(&config, "stage_file")?;
        if stage["stage_id"] != config["current_stage_id"] {
            issue("STAGE_MISMATCH", stage_file);
        }
        if !stage["exit_criteria"]
            .as_array()
            .is_some_and(|items| !items.is_empty())
            || !stage["excluded"].is_array()
            || stage.get("next_stage").is_none()
        {
            issue("FINITE_STAGE_REQUIRED", stage_file);
        }
        if let Some(objectives) = stage["objectives"]
            .as_array()
            .filter(|items| (1..=100).contains(&items.len()))
        {
            let mut ids = BTreeSet::new();
            if !objectives.iter().all(|objective| {
                objective["id"]
                    .as_str()
                    .is_some_and(|id| !id.is_empty() && ids.insert(id))
            }) {
                issue("OBJECTIVE_ID", stage_file);
            }
        } else {
            issue("OBJECTIVE_BUDGET", stage_file);
        }
    }
    Ok(
        json!({"ok":issues.is_empty(),"issues":issues,"checked_paths":checked,"config_hash":digest(&config),"writes":0,"content_quality":"not_evaluated",
        "learning_mastery":"not_inferred","scope":"entry_links_budgets_finite_stage_only","semantic_state_consistency":"requires_agent_review"}),
    )
}
