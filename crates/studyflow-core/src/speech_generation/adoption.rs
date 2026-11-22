use std::path::Path;

use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{json, Value};

use crate::{
    audio::assets,
    infrastructure::{leases::Lease, StorageError},
};

use super::{files, jobs};

pub fn preview(root: &Path, job: &str) -> Result<Value, StorageError> {
    let data = jobs::ready_audio(root, job)?;
    Ok(json!({"data":STANDARD.encode(data.bytes),"mime":data.reference.format.mime()}))
}

pub fn adopt(root: &Path, job: &str) -> Result<Value, StorageError> {
    let _workspace = Lease::shared(root)?;
    let _adopt = files::lock(&files::directory(root)?, "adopt.lock")?;
    let data = jobs::ready_audio(root, job)?;
    let asset = assets::publish(root, data.reference.format, &data.bytes)?;
    let mut result =
        json!({"audio":asset,"duration":data.duration,"relative_path":asset.relative_path()?});
    if let Some(captions) = data.captions {
        result["captions"] = json!(captions);
    }
    Ok(result)
}
