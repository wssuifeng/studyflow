use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::infrastructure::{file_paths, StorageError};

use super::duration;

pub const MAX_AUDIO_BYTES: usize = 8 * 1024 * 1024;
pub const ASSET_DIRECTORY: &str = "content/audio-assets";

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq, Ord, PartialOrd)]
#[serde(rename_all = "lowercase")]
pub enum Format {
    Wav,
    Mp3,
}

impl Format {
    pub fn extension(self) -> &'static str {
        match self {
            Self::Wav => "wav",
            Self::Mp3 => "mp3",
        }
    }

    pub fn mime(self) -> &'static str {
        match self {
            Self::Wav => "audio/wav",
            Self::Mp3 => "audio/mpeg",
        }
    }

    pub fn duration(self, bytes: &[u8]) -> Result<f64, StorageError> {
        if bytes.is_empty() || bytes.len() > MAX_AUDIO_BYTES {
            return Err(StorageError::new("INVALID_AUDIO"));
        }
        match self {
            Self::Wav => duration::wav(bytes),
            Self::Mp3 => duration::mp3(bytes),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq, Ord, PartialOrd)]
#[serde(deny_unknown_fields)]
pub struct AudioRef {
    pub sha256: String,
    pub format: Format,
}

pub struct AudioAsset {
    pub bytes: Vec<u8>,
    pub duration_seconds: f64,
}

impl AudioRef {
    pub fn relative_path(&self) -> Result<String, StorageError> {
        if !file_paths::is_sha256(&self.sha256) {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        Ok(format!(
            "{ASSET_DIRECTORY}/{}.{}",
            self.sha256,
            self.format.extension()
        ))
    }

    pub fn path(&self, root: &Path) -> Result<PathBuf, StorageError> {
        file_paths::workspace_path(root, Path::new(&self.relative_path()?))
    }
}

pub fn read(root: &Path, reference: &AudioRef) -> Result<AudioAsset, StorageError> {
    let path = reference.path(root)?;
    let missing = |error| StorageError::caused_by("AUDIO_MISSING", error);
    let file = File::open(path).map_err(missing)?;
    let mut bytes = Vec::new();
    file.take(MAX_AUDIO_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(missing)?;
    if bytes.len() > MAX_AUDIO_BYTES || digest(&bytes) != reference.sha256 {
        return Err(StorageError::new("INVALID_AUDIO"));
    }
    let duration_seconds = reference.format.duration(&bytes)?;
    Ok(AudioAsset {
        bytes,
        duration_seconds,
    })
}

pub fn publish(root: &Path, format: Format, bytes: &[u8]) -> Result<AudioRef, StorageError> {
    format.duration(bytes)?;
    let reference = AudioRef {
        sha256: digest(bytes),
        format,
    };
    let path = reference.path(root)?;
    let directory = path
        .parent()
        .ok_or_else(|| StorageError::new("INVALID_WORKSPACE_PATH"))?;
    fs::create_dir_all(directory)?;
    let path = reference.path(root)?;
    if !path.exists() && file_paths::write_if_absent(&path, bytes)? {
        return Ok(reference);
    }
    // A concurrent publisher may have won. Verify the bytes already at the
    // address before returning a reference that can be recorded in a course.
    read(root, &reference)?;
    Ok(reference)
}

pub fn validate_package_assets(root: &Path, package: &Value) -> Result<(), StorageError> {
    let mut assets: BTreeMap<AudioRef, f64> = BTreeMap::new();
    for lesson in package["lessons"].as_array().into_iter().flatten() {
        for exercise in lesson["exercises"].as_array().into_iter().flatten() {
            if exercise["type"] != "LISTENING_GROUP" {
                continue;
            }
            let listening = &exercise["listening"];
            let reference: AudioRef = serde_json::from_value(listening["audio"].clone())
                .map_err(|error| StorageError::caused_by("INVALID_ARGUMENT", error))?;
            let end = listening["captions"]
                .as_array()
                .and_then(|cues| cues.last())
                .and_then(|cue| cue["end"].as_f64())
                .unwrap_or(0.0);
            assets
                .entry(reference)
                .and_modify(|current| *current = current.max(end))
                .or_insert(end);
        }
    }
    for (reference, end) in assets {
        let asset = read(root, &reference)?;
        if end > asset.duration_seconds + 0.001 {
            return Err(StorageError::new("INVALID_AUDIO"));
        }
    }
    Ok(())
}

pub fn digest(data: &[u8]) -> String {
    format!("{:x}", Sha256::digest(data))
}
