use std::{io::Read, time::Duration};

use reqwest::{
    header::{HeaderValue, AUTHORIZATION, CONTENT_TYPE},
    redirect::Policy,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use url::{Host, Url};

use crate::{
    audio::assets::{Format, MAX_AUDIO_BYTES},
    infrastructure::StorageError,
};

pub const STEP_PLAN_ENDPOINT: &str = "https://api.stepfun.com/step_plan/v1/audio/speech";
pub const STEP_PLAN_MODEL: &str = "stepaudio-2.5-tts";

#[derive(Clone, Copy, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Provider {
    StepPlan,
    Compatible,
}

fn insecure_loopback(url: &Url) -> bool {
    url.scheme() == "http"
        && match url.host() {
            Some(Host::Domain("localhost")) => true,
            Some(Host::Ipv4(ip)) => ip.octets() == [127, 0, 0, 1],
            Some(Host::Ipv6(ip)) => ip.is_loopback(),
            _ => false,
        }
}

pub fn validate_endpoint(endpoint: &str) -> Result<Url, StorageError> {
    let invalid = || StorageError::new("INVALID_TTS_ENDPOINT");
    let url = Url::parse(endpoint).map_err(|_| invalid())?;
    let authority = endpoint
        .split_once("://")
        .map(|(_, rest)| rest.split('/').next().unwrap_or_default());
    if !(url.scheme() == "https" || insecure_loopback(&url))
        || url.host().is_none()
        || authority.is_none_or(|authority| authority.contains('@'))
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || matches!(url.path(), "" | "/")
        || endpoint.contains(['\\', '\r', '\n', '\t'])
    {
        return Err(invalid());
    }
    Ok(url)
}

pub struct Synthesis<'a> {
    pub provider: Provider,
    pub endpoint: &'a str,
    pub model: &'a str,
    pub voice: &'a str,
    pub text: &'a str,
    pub instruction: Option<&'a str>,
    pub format: Format,
}

fn payload(spec: &Synthesis<'_>) -> serde_json::Value {
    let mut payload = json!({"model":spec.model,"voice":spec.voice,"input":spec.text,"response_format":spec.format});
    if let Some(instruction) = spec.instruction.filter(|text| !text.is_empty()) {
        let key = match spec.provider {
            Provider::StepPlan => "instruction",
            Provider::Compatible => "instructions",
        };
        payload[key] = json!(instruction);
    }
    payload
}

pub fn synthesize(spec: Synthesis<'_>, secret: &[u8]) -> Result<(Vec<u8>, f64), StorageError> {
    let url = validate_endpoint(match spec.provider {
        Provider::StepPlan => STEP_PLAN_ENDPOINT,
        Provider::Compatible => spec.endpoint,
    })?;
    let request_failed = || StorageError::new("TTS_UNCONFIRMED");
    let mut builder = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(35))
        .redirect(Policy::none())
        .retry(reqwest::retry::never());
    if insecure_loopback(&url) {
        builder = builder.no_proxy();
    }
    let client = builder
        .build()
        .map_err(|_| StorageError::new("TTS_PROVIDER_ERROR"))?;
    let mut token = b"Bearer ".to_vec();
    token.extend_from_slice(secret);
    let mut auth = HeaderValue::from_bytes(&token).map_err(|_| StorageError::new("TTS_AUTH"))?;
    auth.set_sensitive(true);
    let response = client
        .post(url)
        .header(AUTHORIZATION, auth)
        .header(CONTENT_TYPE, "application/json")
        .body(payload(&spec).to_string())
        .send()
        .map_err(|_| request_failed())?;
    if !response.status().is_success() {
        let code = match response.status().as_u16() {
            401 | 403 => "TTS_AUTH",
            429 => "TTS_RATE_LIMIT",
            _ => "TTS_PROVIDER_ERROR",
        };
        return Err(StorageError::new(code));
    }
    if response
        .content_length()
        .is_some_and(|length| length > MAX_AUDIO_BYTES as u64)
    {
        return Err(StorageError::new("INVALID_AUDIO"));
    }
    let mut bytes = Vec::new();
    response
        .take(MAX_AUDIO_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| request_failed())?;
    let duration = spec.format.duration(&bytes)?;
    Ok((bytes, duration))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn step_plan_and_compatible_adapt_the_instruction_field() {
        let spec = Synthesis {
            provider: Provider::StepPlan,
            endpoint: STEP_PLAN_ENDPOINT,
            model: STEP_PLAN_MODEL,
            voice: "voice",
            text: "Synthetic course.",
            instruction: Some("Speak clearly."),
            format: Format::Mp3,
        };
        assert_eq!(
            payload(&spec),
            json!({"model":STEP_PLAN_MODEL,"voice":"voice","input":"Synthetic course.","instruction":"Speak clearly.","response_format":"mp3"})
        );
        let compatible = Synthesis {
            provider: Provider::Compatible,
            ..spec
        };
        assert_eq!(
            payload(&compatible),
            json!({"model":STEP_PLAN_MODEL,"voice":"voice","input":"Synthetic course.","instructions":"Speak clearly.","response_format":"mp3"})
        );
    }
}
