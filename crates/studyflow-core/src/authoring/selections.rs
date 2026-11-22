use super::{
    bounded_read, digest, error, nonblank, sha, text, vocabulary::catalog, MaterialRoot, Result,
    Sources,
};
use crate::infrastructure::file_paths::write_if_absent;
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};

const FILES: [&str; 2] = ["words.tsv", "selection.json"];
const FIELDS: [&str; 8] = [
    "entry_id", "word", "phonetic", "meaning", "origin", "role", "sense", "reason",
];

fn artifact(root: &MaterialRoot, folder: &Path) -> Result<(Value, Value)> {
    let manifest = root.json(folder.join("manifest.json"))?;
    let files = manifest["files"].as_object().filter(|files| {
        files.len() == FILES.len() && FILES.iter().all(|name| files.contains_key(*name))
    });
    let Some(files) = files.filter(|_| manifest["format"] == 1) else {
        return Err(error("FORMAT", "invalid selection artifacts"));
    };
    for (file, expected) in files {
        let target = root.path(folder.join(file))?;
        if !target.is_file()
            || sha(&bounded_read(&target, 262144, "split the selected input")?) != *expected
        {
            return Err(error(
                "ARTIFACT_CHANGED",
                "selected resource was edited outside its recipe",
            ));
        }
    }
    let recipe = root.json(folder.join("selection.json"))?;
    if manifest["selection_hash"] != digest(&recipe) {
        return Err(error(
            "ARTIFACT_CHANGED",
            "recipe hash differs from manifest",
        ));
    }
    Ok((manifest, recipe))
}

pub(super) fn create(root: &MaterialRoot, recipe_path: &str, output: &str) -> Result<Value> {
    let recipe = root.json(recipe_path)?;
    let identifier = recipe["selection_id"].as_str().unwrap_or_default();
    if recipe["format"] != 1
        || !recipe["revision"].as_u64().is_some_and(|n| n > 0)
        || !(1..=64).contains(&identifier.len())
        || !identifier
            .bytes()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == b'-')
    {
        return Err(error(
            "FORMAT",
            "selection_id and positive revision required",
        ));
    }
    if !nonblank(&recipe["stage_id"]) || !nonblank(&recipe["objective"]) {
        return Err(error("FORMAT", "finite stage and objective required"));
    }
    let (Some(sources), Some(items)) = (
        recipe["sources"].as_array(),
        recipe["items"]
            .as_array()
            .filter(|items| (1..=60).contains(&items.len())),
    ) else {
        return Err(error(
            "INPUT_BUDGET",
            "explicit sources and 1..60 selected entries required",
        ));
    };
    let declarations = sources
        .iter()
        .map(|entry| {
            Ok((
                text(entry, "id")?.to_owned(),
                text(entry, "path")?.to_owned(),
            ))
        })
        .collect::<Result<_>>()?;
    let (entries, current) = catalog(root, &declarations)?;
    if sources
        .iter()
        .zip(&current)
        .any(|(source, now)| source["sha256"] != now["sha256"])
    {
        return Err(error("SOURCE_CHANGED", "reread sources before selecting"));
    }
    let by_id: BTreeMap<_, _> = entries
        .iter()
        .map(|entry| (entry["entry_id"].as_str().unwrap(), entry))
        .collect();
    let mut seen = BTreeSet::new();
    let mut writer = csv::WriterBuilder::new()
        .delimiter(b'\t')
        .from_writer(Vec::new());
    let write_error = |_| error("FORMAT", "unable to encode selection TSV");
    writer.write_record(FIELDS).map_err(write_error)?;
    for item in items {
        let id = item["entry_id"].as_str().unwrap_or_default();
        if !seen.insert(id) {
            return Err(error("DUPLICATE_SELECTION", "repeated source entry"));
        }
        let entry = by_id
            .get(id)
            .ok_or_else(|| error("ENTRY_NOT_FOUND", "entry no longer exists in named sources"))?;
        if !nonblank(&entry["meaning"]) {
            return Err(error(
                "MEANING_GAP",
                "complete this relevant definition before ready selection",
            ));
        }
        if item["meaning_verified"] != true {
            return Err(error(
                "REVIEW_REQUIRED",
                "explicitly review the selected meaning",
            ));
        }
        let role = item["role"].as_str().unwrap_or_default();
        if !matches!(role, "new" | "prerequisite" | "review" | "family")
            || !nonblank(&item["sense"])
            || !nonblank(&item["reason"])
        {
            return Err(error(
                "FORMAT",
                "entry role, selected sense and reason required",
            ));
        }
        if item.get("evidence_refs").is_some_and(|refs| {
            !refs
                .as_array()
                .is_some_and(|items| items.iter().all(Value::is_string))
        }) {
            return Err(error("FORMAT", "evidence_refs must be a list of locators"));
        }
        if role == "family" && !nonblank(&item["family_source_ref"]) {
            return Err(error(
                "REVIEW_REQUIRED",
                "family relationship requires its source locator",
            ));
        }
        writer
            .write_record(FIELDS.iter().enumerate().map(|(index, key)| {
                let parent = if index < 5 { entry } else { &item };
                parent[*key].as_str().expect("validated selection field")
            }))
            .map_err(write_error)?;
    }
    let words = writer
        .into_inner()
        .map_err(|_| error("FORMAT", "unable to encode selection TSV"))?;
    if super::utf8(&words)?.chars().count() > 12000 {
        return Err(error(
            "OUTPUT_BUDGET",
            "split by meaningful sub-objectives, do not trim definitions",
        ));
    }
    let fingerprint = digest(&recipe);
    let folder = root.path(output)?;
    let replay = || -> Result<bool> {
        if !root.path(folder.join("manifest.json"))?.is_file() {
            return Err(error("OUTPUT_EXISTS", "unrecognized output already exists"));
        }
        if artifact(root, &folder)?.0["selection_hash"] != fingerprint {
            return Err(error(
                "OUTPUT_EXISTS",
                "immutable output belongs to another selection",
            ));
        }
        Ok(false)
    };
    let created = if folder.exists() {
        replay()?
    } else {
        let words = file_text(super::utf8(&words)?);
        let selection = encode(&recipe);
        let manifest = encode(
            &json!({"format":1,"selection_hash":fingerprint,"selection_id":identifier,"revision":recipe["revision"],"sources":current,
            "files":{"words.tsv":sha(&words),"selection.json":sha(&selection)}}),
        );
        let parent = folder.parent().expect("child of author root");
        fs::create_dir_all(parent)?;
        let staged = tempfile::Builder::new()
            .prefix(".authoring-")
            .tempdir_in(root.path(parent)?)?;
        for (name, data) in [
            (FILES[0], words),
            (FILES[1], selection),
            ("manifest.json", manifest),
        ] {
            use std::io::Write;
            let mut file = fs::File::create_new(staged.path().join(name))?;
            file.write_all(&data)?;
            file.sync_all()?;
        }
        let target = root.path(&folder)?;
        match publish_folder(staged.path(), &target) {
            Ok(()) => true,
            Err(_) if target.exists() => replay()?,
            Err(e) => return Err(e),
        }
    };
    Ok(
        json!({"ok":true,"selection_hash":fingerprint,"entries":items.len(),"created":created,"content_review":"author_attested_not_machine_certified","learning_mastery":"not_inferred"}),
    )
}

#[cfg(windows)]
fn publish_folder(staged: &Path, target: &Path) -> Result<()> {
    fs::rename(staged, target)?;
    Ok(())
}

#[cfg(not(windows))]
fn publish_folder(staged: &Path, target: &Path) -> Result<()> {
    fs::create_dir(target)?;
    for name in [FILES[0], FILES[1], "manifest.json"] {
        fs::hard_link(staged.join(name), target.join(name))?;
    }
    Ok(())
}

fn file_text(text: &str) -> Vec<u8> {
    if cfg!(windows) {
        text.replace('\n', "\r\n").into_bytes()
    } else {
        text.as_bytes().to_vec()
    }
}

fn encode(value: &Value) -> Vec<u8> {
    file_text(&format!("{value:#}\n"))
}

pub(super) struct State {
    pub ids: BTreeSet<String>,
    pub fingerprint: String,
    stale: usize,
    versions: usize,
    links: usize,
}

pub(super) fn selected_state(
    root: &MaterialRoot,
    directory: &str,
    sources: &[Value],
) -> Result<State> {
    let folder = root.path(directory)?;
    let mut state = State {
        ids: BTreeSet::new(),
        fingerprint: digest(&json!([])),
        stale: 0,
        versions: 0,
        links: 0,
    };
    if !folder.exists() {
        return Ok(state);
    }
    let mut children = fs::read_dir(folder)?
        .take(1001)
        .map(|entry| entry.map(|e| e.path()))
        .collect::<std::io::Result<Vec<_>>>()?;
    if children.len() > 1000 {
        return Err(error(
            "INPUT_BUDGET",
            "narrow the explicit selections directory",
        ));
    }
    children.sort_unstable();
    let hashes: BTreeMap<_, _> = sources
        .iter()
        .map(|entry| (entry["id"].as_str().unwrap(), &entry["sha256"]))
        .collect();
    let mut recipes = Vec::new();
    let mut versions = BTreeMap::new();
    for child in children {
        if child
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with(".authoring-")
        {
            continue;
        }
        let child = root.path(child)?;
        if !child.is_dir() || !root.path(child.join("manifest.json"))?.exists() {
            continue;
        }
        let (manifest, recipe) = artifact(root, &child)?;
        state.versions += 1;
        let key = (
            text(&recipe, "selection_id")?.to_owned(),
            recipe["revision"].to_string(),
        );
        let fingerprint = text(&manifest, "selection_hash")?.to_owned();
        if versions
            .insert(key, fingerprint.clone())
            .is_some_and(|prior| prior != fingerprint)
        {
            return Err(error(
                "SELECTION_VERSION_CONFLICT",
                "same identity/revision has different content",
            ));
        }
        recipes.push(fingerprint);
        for file in fs::read_dir(child)? {
            let file = file?;
            let name = file.file_name();
            let name = name.to_string_lossy();
            if !(name.starts_with("course-link-") && name.ends_with(".json")) {
                continue;
            }
            let link = root.json(file.path())?;
            let receipt = root.path(text(&link, "receipt_path")?)?;
            if link["selection_hash"] != manifest["selection_hash"]
                || !receipt.is_file()
                || sha(&bounded_read(&receipt, 262144, "split the selected input")?)
                    != link["receipt_sha256"]
            {
                return Err(error(
                    "RECEIPT_CHANGED",
                    "linked authoring receipt moved or changed",
                ));
            }
            let actual = root.json(&receipt)?;
            if actual["ok"] != true
                || actual["course"]["id"] != link["course_id"]
                || actual["course"]["content_revision"] != link["content_revision"]
            {
                return Err(error(
                    "RECEIPT_MISMATCH",
                    "linked course identity/version changed",
                ));
            }
            state.links += 1;
        }
        let sources = manifest["sources"]
            .as_array()
            .ok_or_else(|| error("FORMAT", "invalid selection sources"))?;
        if sources.iter().any(|source| {
            source["id"].as_str().and_then(|id| hashes.get(id)).copied() != source.get("sha256")
        }) {
            state.stale += 1;
            continue;
        }
        for item in recipe["items"]
            .as_array()
            .ok_or_else(|| error("FORMAT", "invalid selection items"))?
        {
            state.ids.insert(text(item, "entry_id")?.to_owned());
        }
    }
    recipes.sort_unstable();
    state.fingerprint = digest(&json!(recipes));
    Ok(state)
}

pub(super) fn coverage(root: &MaterialRoot, sources: &Sources, directory: &str) -> Result<Value> {
    let (entries, mut sources) = catalog(root, sources)?;
    let state = selected_state(root, directory, &sources)?;
    let ids: BTreeSet<_> = entries
        .iter()
        .map(|entry| entry["entry_id"].as_str().unwrap().to_owned())
        .collect();
    if !state.ids.is_subset(&ids) {
        return Err(error("ENTRY_NOT_FOUND", "invalid selection reference"));
    }
    for source in &mut sources {
        let selected = entries
            .iter()
            .filter(|entry| {
                entry["source_id"] == source["id"]
                    && state.ids.contains(entry["entry_id"].as_str().unwrap())
            })
            .count();
        source["selected"] = json!(selected);
        source["remaining"] = json!(source["records"].as_u64().unwrap() - selected as u64);
    }
    let spellings = entries
        .iter()
        .map(|entry| entry["word"].as_str().unwrap())
        .collect::<BTreeSet<_>>()
        .len();
    let gaps = entries
        .iter()
        .filter(|entry| !nonblank(&entry["meaning"]))
        .count();
    Ok(
        json!({"ok":true,"sources":sources,"total_source_records":entries.len(),"unique_spellings":spellings,"selection_versions":state.versions,
        "linked_course_versions":state.links,"stale_versions_excluded":state.stale,"meaning_gaps":gaps,"learning_mastery":"not_inferred","coverage_kind":"current-source-resource-selection_not_learning"}),
    )
}

pub(super) fn link(
    root: &MaterialRoot,
    selection: &str,
    receipt: &str,
    course: &str,
    revision: i64,
) -> Result<Value> {
    let folder = root.path(selection)?;
    let (manifest, _) = artifact(root, &folder)?;
    let receipt_path = root.path(receipt)?;
    let actual = root.json(&receipt_path)?;
    if actual["ok"] != true
        || actual["course"]["id"] != course
        || actual["course"]["content_revision"].as_i64() != Some(revision)
    {
        return Err(error(
            "RECEIPT_MISMATCH",
            "use actual successful course detail with matching id/content_revision",
        ));
    }
    let mut payload = json!({"format":1,"selection_hash":manifest["selection_hash"],"course_id":course,"content_revision":revision,
        "receipt_path":root.relative(&receipt_path),"receipt_sha256":sha(&bounded_read(&receipt_path, 262144, "split the selected input")?),
        "learning_evidence":false,"verification":"matching_receipt_shape_not_authenticated_cli_origin"});
    let target = root.path(folder.join(format!(
        "course-link-{}.json",
        &digest(&json!([course, revision]))[..24]
    )))?;
    let created = write_if_absent(&target, &encode(&payload))
        .map_err(|_| error("OSError", "unable to publish receipt link"))?;
    if !created && root.json(&target)? != payload {
        return Err(error("OUTPUT_EXISTS", "conflicting receipt link"));
    }
    payload["ok"] = json!(true);
    payload["replayed"] = json!(!created);
    Ok(payload)
}
