use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::Value;

use super::{config::absolute, file_paths::is_link, StorageError};

const SKILL: &str = "studyflow-agent/SKILL.md";
const POINTER_LIMIT: u64 = 16_384;

#[derive(Serialize)]
pub struct InstallationInfo {
    workspace: PathBuf,
    workspace_exists: bool,
    cli_path: Option<PathBuf>,
    cli_argv: Vec<PathBuf>,
    cli_available: bool,
    skill_path: PathBuf,
    skill_kind: &'static str,
    skill_available: bool,
    agent_workspace_entry_path: Option<PathBuf>,
    agent_workspace_entry_status: &'static str,
    source_cli: bool,
    automatic_path: bool,
    agent_ready: bool,
}

pub fn discover(workspace: &Path) -> Result<InstallationInfo, StorageError> {
    let executable = std::env::current_exe()?;
    let pointer = std::env::home_dir().map(|home| home.join(".studyflow-agent/workspace.json"));
    inspect(&executable, workspace, pointer.as_deref())
}

pub fn inspect(
    executable: &Path,
    workspace: &Path,
    pointer: Option<&Path>,
) -> Result<InstallationInfo, StorageError> {
    let executable = absolute(executable)?;
    let parent = executable
        .parent()
        .ok_or_else(|| StorageError::new("INVALID_INSTALLATION_PATH"))?;
    let bundled_skill = parent.join(SKILL);
    let repository = (!bundled_skill.is_file())
        .then(|| {
            parent.ancestors().find(|ancestor| {
                ancestor
                    .join("crates/studyflow-runtime/Cargo.toml")
                    .is_file()
                    && ancestor.join("skills").is_dir()
            })
        })
        .flatten();
    let cli_name = format!("studyflow{}", std::env::consts::EXE_SUFFIX);
    let cli = parent.join(cli_name);
    let cli_available = cli.is_file();
    let source_cli = repository.is_some();
    let workspace = absolute(workspace)?;
    let workspace_exists = workspace.is_dir();
    let skill = repository.map_or(bundled_skill, |root| root.join("skills").join(SKILL));
    let skill_available = skill.is_file();
    let mut forbidden = vec![workspace.as_path()];
    if let Some(repository) = repository {
        forbidden.push(repository);
    } else {
        forbidden.push(parent.parent().unwrap_or(parent));
    }
    let (entry, status) = pointer.map_or((None, "missing"), |path| agent_entry(path, &forbidden));
    Ok(InstallationInfo {
        workspace,
        workspace_exists,
        cli_path: (!source_cli).then(|| cli.clone()),
        cli_argv: vec![cli],
        cli_available,
        skill_path: skill,
        skill_kind: if source_cli {
            "repository"
        } else {
            "installed"
        },
        skill_available,
        agent_workspace_entry_path: entry,
        agent_workspace_entry_status: status,
        source_cli,
        automatic_path: false,
        agent_ready: cli_available && skill_available && workspace_exists,
    })
}

fn agent_entry(pointer: &Path, forbidden: &[&Path]) -> (Option<PathBuf>, &'static str) {
    let metadata = match fs::symlink_metadata(pointer) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return (None, "missing"),
        Err(_) => return (None, "invalid"),
    };
    if is_link(&metadata) || !metadata.is_file() || metadata.len() > POINTER_LIMIT {
        return (None, "invalid");
    }
    let read_entry = || -> Option<PathBuf> {
        let mut body = Vec::new();
        File::open(pointer)
            .ok()?
            .take(POINTER_LIMIT + 1)
            .read_to_end(&mut body)
            .ok()?;
        if body.len() as u64 > POINTER_LIMIT {
            return None;
        }
        let body = body.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&body);
        let object: Value = serde_json::from_slice(body).ok()?;
        if object.get("format")?.as_i64()? != 1 {
            return None;
        }
        let candidate = Path::new(object.get("agent_workspace")?.as_str()?);
        if !candidate.is_absolute() {
            return None;
        }
        let root = dunce::canonicalize(candidate).ok()?;
        if !root.is_dir()
            || forbidden
                .iter()
                .any(|path| root.starts_with(path) || path.starts_with(&root))
        {
            return None;
        }
        let entry = dunce::canonicalize(root.join("AGENTS.md")).ok()?;
        (entry.parent() == Some(root.as_path()) && entry.is_file()).then_some(entry)
    };
    match read_entry() {
        Some(entry) => (Some(entry), "found"),
        None => (None, "invalid"),
    }
}
