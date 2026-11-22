use std::{
    fs,
    path::{Path, PathBuf},
};

use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    files,
    providers::{validate_endpoint, Provider, STEP_PLAN_ENDPOINT, STEP_PLAN_MODEL},
};
use crate::{
    audio::assets::Format,
    infrastructure::{credentials::dpapi, leases::Lease, StorageError},
};

const DEFAULT_NAME: &str = "阶跃星辰";
const DEFAULT_VOICE: &str = "cixingnansheng";

#[derive(Serialize, Deserialize)]
pub(super) struct Profile {
    pub provider: Provider,
    pub endpoint: String,
    pub model: String,
    pub voice: String,
    pub format: Format,
    pub version: u64,
    pub name: String,
    pub profile_id: String,
}

#[derive(Serialize, Deserialize)]
pub(super) struct StoredProfile {
    #[serde(flatten)]
    pub profile: Profile,
    credential: Option<String>,
}

impl StoredProfile {
    fn default_for(id: &str) -> Self {
        Self {
            profile: Profile {
                provider: Provider::StepPlan,
                endpoint: STEP_PLAN_ENDPOINT.into(),
                model: STEP_PLAN_MODEL.into(),
                voice: DEFAULT_VOICE.into(),
                format: Format::Mp3,
                version: 0,
                name: DEFAULT_NAME.into(),
                profile_id: id.into(),
            },
            credential: None,
        }
    }

    fn public(&self) -> Value {
        let mut value = json!(self.profile);
        value["has_credential"] = json!(self.has_credential());
        value
    }

    pub(super) fn has_credential(&self) -> bool {
        self.credential
            .as_ref()
            .is_some_and(|value| !value.is_empty())
    }

    pub(super) fn secret(&self) -> Result<Vec<u8>, StorageError> {
        let value = self
            .credential
            .as_ref()
            .filter(|value| !value.is_empty())
            .ok_or_else(|| StorageError::new("KEY_REQUIRED"))?;
        let encrypted = STANDARD
            .decode(value)
            .map_err(|_| StorageError::new("KEY_STORE_UNAVAILABLE"))?;
        dpapi(&encrypted, true)
    }
}

fn profile_path(directory: &Path, id: &str) -> Result<PathBuf, StorageError> {
    if id == "default" {
        return files::path(directory, Path::new("profile.json"));
    }
    let id = Uuid::parse_str(id).map_err(|_| StorageError::new("INVALID_ARGUMENT"))?;
    files::path(directory, &Path::new("profiles").join(format!("{id}.json")))
}

pub(super) fn load(directory: &Path, id: &str) -> Result<StoredProfile, StorageError> {
    Ok(files::read_json(&profile_path(directory, id)?)?
        .unwrap_or_else(|| StoredProfile::default_for(id)))
}

pub fn get(root: &Path, id: &str) -> Result<Value, StorageError> {
    let mut profile = load(&files::directory(root)?, id)?;
    profile.profile.profile_id = id.to_owned();
    Ok(profile.public())
}

pub fn list(root: &Path) -> Result<Value, StorageError> {
    let directory = files::directory(root)?;
    let profiles = files::path(&directory, Path::new("profiles"))?;
    let mut ids = vec!["default".to_owned()];
    match fs::read_dir(profiles) {
        Ok(entries) => {
            for entry in entries {
                let f = entry?.path();
                if f.extension().is_some_and(|ext| ext == "json") {
                    if let Some(id) = f
                        .file_stem()
                        .and_then(|value| value.to_str())
                        .filter(|id| Uuid::parse_str(id).is_ok())
                    {
                        ids.push(id.to_owned());
                    }
                }
            }
            ids[1..].sort_unstable();
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let items = ids
        .iter()
        .map(|id| load(&directory, id).map(|profile| profile.public()))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(json!({"profiles":items}))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Save {
    #[serde(default = "default_id")]
    profile_id: String,
    #[serde(default = "default_name")]
    name: String,
    provider: Provider,
    #[serde(default)]
    endpoint: String,
    model: String,
    voice: String,
    #[serde(default = "default_format")]
    format: Format,
    credential: Option<String>,
    #[serde(default)]
    clear_credential: bool,
    expected_version: u64,
}

fn default_id() -> String {
    "default".into()
}
fn default_name() -> String {
    DEFAULT_NAME.into()
}
fn default_format() -> Format {
    Format::Mp3
}

pub fn save(root: &Path, request: &Value) -> Result<Value, StorageError> {
    let invalid = || StorageError::new("INVALID_ARGUMENT");
    let input: Save = serde_json::from_value(request.clone()).map_err(|_| invalid())?;
    let name = input.name.trim();
    let model = input.model.trim();
    let voice = input.voice.trim();
    let supplied = input.credential.as_deref().map(str::trim);
    if [name, model, voice]
        .iter()
        .any(|value| value.is_empty() || value.chars().count() > 160)
        || input.endpoint.trim().chars().count() > 500
        || supplied.is_some_and(|key| {
            key.is_empty() || key.len() > 500 || !key.bytes().all(|b| (b'!'..=b'~').contains(&b))
        })
    {
        return Err(invalid());
    }
    let endpoint = match input.provider {
        Provider::StepPlan => STEP_PLAN_ENDPOINT,
        Provider::Compatible => {
            validate_endpoint(input.endpoint.trim())?;
            input.endpoint.trim()
        }
    };
    let directory = files::directory(root)?;
    let path = profile_path(&directory, &input.profile_id)?;
    let _workspace = Lease::shared(root)?;
    let _lock = files::lock(&directory, "profile.lock")?;
    let prior = load(&directory, &input.profile_id)?;
    if prior.profile.version != input.expected_version {
        return Err(StorageError::new("VERSION_CONFLICT"));
    }
    let credential = if let Some(secret) = supplied {
        Some(STANDARD.encode(dpapi(secret.as_bytes(), false)?))
    } else if !input.clear_credential
        && prior.profile.provider == input.provider
        && prior.profile.endpoint == endpoint
    {
        prior.credential
    } else {
        None
    };
    let profile = StoredProfile {
        profile: Profile {
            provider: input.provider,
            endpoint: endpoint.into(),
            model: model.into(),
            voice: voice.into(),
            format: input.format,
            version: input.expected_version.checked_add(1).ok_or_else(invalid)?,
            name: name.into(),
            profile_id: input.profile_id,
        },
        credential,
    };
    files::write_json(&path, &profile)?;
    Ok(profile.public())
}

pub fn provider_defaults() -> Value {
    json!({"step_plan":StoredProfile::default_for("default").public(),"compatible":{"endpoint":"","format":"mp3"}})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(windows)]
    #[test]
    fn encrypted_credential_is_only_exposed_to_the_worker() {
        let plain = b"fixture-only-dpapi-secret";
        let mut profile = StoredProfile::default_for("default");
        profile.credential = Some(STANDARD.encode(dpapi(plain, false).unwrap()));
        assert_eq!(profile.secret().unwrap(), plain);
        assert!(!profile
            .public()
            .to_string()
            .contains("fixture-only-dpapi-secret"));
        assert!(profile.public().get("credential").is_none());
    }
    #[cfg(windows)]
    #[test]
    #[ignore = "requires a same-user synthetic profile produced by the recovered 1.8.27 baseline"]
    fn decrypts_python_dpapi_profile_from_the_same_windows_user() {
        let root = std::path::PathBuf::from(
            std::env::var_os("STUDYFLOW_F5_PROFILE_WORKSPACE")
                .expect("synthetic profile workspace"),
        );
        let profile = load(&files::directory(&root).unwrap(), "default").unwrap();
        assert!(profile.has_credential());
        assert!(profile.secret().unwrap() == b"fixture-only-legacy-profile-key");
        assert!(profile.public().get("credential").is_none());
    }
}
