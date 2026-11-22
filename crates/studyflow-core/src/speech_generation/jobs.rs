use std::{
    fs::File,
    io::Read,
    path::{Path, PathBuf},
};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use super::{
    dialogue::Dialogue,
    files, profiles,
    providers::{self, Synthesis},
};
use crate::{
    audio::assets::{self, Format, MAX_AUDIO_BYTES},
    infrastructure::{fingerprint::JsonFingerprint::Utf8, leases::Lease, StorageError},
};

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Segment {
    pub(super) text: String,
    voice: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Start {
    job_id: String,
    #[serde(default = "default_profile")]
    profile_id: String,
    expected_profile_version: u64,
    text: Option<String>,
    instruction: Option<String>,
    segments: Option<Vec<Segment>>,
    #[serde(default)]
    retry: bool,
}

fn default_profile() -> String {
    "default".into()
}

#[derive(Deserialize, Serialize)]
struct Request {
    request_hash: String,
    launch_id: String,
    segments: Vec<Segment>,
    instruction: Option<String>,
    in_flight: Option<usize>,
}

#[derive(Deserialize, Serialize)]
struct Job {
    job_id: String,
    request_hash: String,
    profile_id: String,
    profile_version: u64,
    status: State,
    format: Format,
    completed_segments: usize,
    total_segments: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    sha256: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    duration: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    captions: Option<Vec<Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error_code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    message: Option<String>,
}

#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
enum State {
    Running,
    Ready,
    Failed,
    Interrupted,
}

impl Job {
    fn public(&self) -> Value {
        let mut value = json!(self);
        value.as_object_mut().unwrap().remove("request_hash");
        value
    }
    fn fail(&mut self, state: State, code: &str, message: &str) {
        self.status = state;
        self.error_code = Some(code.into());
        self.message = Some(message.into());
    }
}

struct Paths {
    directory: PathBuf,
    id: String,
}

impl Paths {
    fn new(root: &Path, id: &str) -> Result<Self, StorageError> {
        let id = Uuid::parse_str(id)
            .ok()
            .filter(|_| id.len() == 36)
            .ok_or_else(invalid)?
            .to_string();
        Ok(Self {
            directory: files::directory(root)?,
            id,
        })
    }

    fn path(&self, suffix: &str) -> Result<PathBuf, StorageError> {
        files::path(&self.directory, Path::new(&format!("{}.{suffix}", self.id)))
    }

    fn job(&self) -> Result<Option<Job>, StorageError> {
        files::read_json(&self.path("json")?)
    }

    fn require_job(&self) -> Result<Job, StorageError> {
        self.job()?
            .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))
    }

    fn write_job(&self, job: &Job) -> Result<(), StorageError> {
        files::write_json(&self.path("json")?, job)
    }

    fn lock_job(&self) -> Result<Lease, StorageError> {
        files::lock(&self.directory, &format!("{}.lock", self.id))
    }
}

fn invalid() -> StorageError {
    StorageError::new("INVALID_ARGUMENT")
}

impl Start {
    fn prepare(mut self) -> Result<(Self, Request), StorageError> {
        let mut segments = match (self.text.take(), self.segments.take()) {
            (Some(text), None) => vec![Segment { text, voice: None }],
            (None, Some(segments)) if (1..=10).contains(&segments.len()) => segments,
            _ => return Err(invalid()),
        };
        for segment in &mut segments {
            segment.text = segment.text.trim().to_owned();
            segment.voice = segment.voice.as_deref().map(str::trim).map(str::to_owned);
            if segment.text.is_empty()
                || segment.text.chars().count() > 1200
                || segment
                    .voice
                    .as_deref()
                    .is_some_and(|voice| voice.is_empty() || voice.chars().count() > 160)
            {
                return Err(invalid());
            }
        }
        let instruction = self.instruction.take().map(|value| value.trim().to_owned());
        if instruction
            .as_deref()
            .is_some_and(|text| text.chars().count() > 500)
        {
            return Err(invalid());
        }
        let request_hash = Utf8.hash(&json!([
            self.profile_id,
            self.expected_profile_version,
            segments,
            instruction
        ]));
        Ok((
            self,
            Request {
                request_hash,
                launch_id: Uuid::new_v4().to_string(),
                segments,
                instruction,
                in_flight: None,
            },
        ))
    }
}

pub fn start(
    root: &Path,
    params: &Value,
    launch: impl FnOnce(&str, &str) -> Result<(), StorageError>,
) -> Result<Value, StorageError> {
    let input: Start = serde_json::from_value(params.clone()).map_err(|_| invalid())?;
    let (input, request) = input.prepare()?;
    let paths = Paths::new(root, &input.job_id)?;
    let _workspace = Lease::shared(root)?;
    let _jobs = files::lock(&paths.directory, "jobs.lock")?;
    if let Some(prior) = paths.job()? {
        if prior.request_hash != request.request_hash {
            return Err(StorageError::new("IDEMPOTENCY_KEY_CONFLICT"));
        }
        let prior = recover(&paths, prior)?;
        if !input.retry || !matches!(prior.status, State::Failed | State::Interrupted) {
            return Ok(prior.public());
        }
    } else if input.retry {
        return Err(StorageError::new("OBJECT_NOT_FOUND"));
    }
    let profile = profiles::load(&paths.directory, &input.profile_id)?;
    if profile.profile.version != input.expected_profile_version {
        return Err(StorageError::new("VERSION_CONFLICT"));
    }
    if !profile.has_credential() {
        return Err(StorageError::new("KEY_REQUIRED"));
    }
    if request.segments.len() > 1 && profile.profile.format != Format::Wav {
        return Err(invalid());
    }
    let mut job = Job {
        job_id: paths.id.clone(),
        request_hash: request.request_hash.clone(),
        profile_id: input.profile_id,
        profile_version: input.expected_profile_version,
        status: State::Running,
        format: profile.profile.format,
        completed_segments: 0,
        total_segments: request.segments.len(),
        sha256: None,
        duration: None,
        captions: None,
        error_code: None,
        message: None,
    };
    files::write_json(&paths.path("request.json")?, &request)?;
    paths.write_job(&job)?;
    if let Err(error) = launch(&paths.id, &request.launch_id) {
        // If the worker had already completed before the handshake was lost, keep its receipt.
        if let Ok(_lock) = paths.lock_job() {
            job = paths.require_job()?;
            if job.status == State::Running {
                job.fail(
                    State::Interrupted,
                    error.code,
                    "语音进程未能完成启动确认。请先查看任务状态，再决定是否重试。",
                );
                paths.write_job(&job)?;
            }
        }
        return Err(error);
    }
    Ok(job.public())
}

fn recover(paths: &Paths, job: Job) -> Result<Job, StorageError> {
    if job.status != State::Running {
        return Ok(job);
    }
    let _lock = match paths.lock_job() {
        Ok(lock) => lock,
        Err(error) if error.code == "SPEECH_BUSY" => return Ok(paths.job()?.unwrap_or(job)),
        Err(error) => return Err(error),
    };
    let mut job = paths.require_job()?;
    if job.status == State::Running {
        let request: Option<Request> = files::read_json(&paths.path("request.json")?)?;
        let uncertain = match request.filter(|r| r.request_hash == job.request_hash) {
            Some(request) => match request.in_flight {
                Some(index) => !paths.path(&format!("part-{index}"))?.is_file(),
                None => false,
            },
            None => true,
        };
        if uncertain {
            job.fail(
                State::Interrupted,
                "TTS_UNCONFIRMED",
                "应用退出前未收到生成结果。请先检查服务商记录。",
            );
        } else {
            job.fail(
                State::Interrupted,
                "TTS_WORKER_INTERRUPTED",
                "语音进程在可恢复的检查点退出。明确重试后将复用已保存的语音分段。",
            );
        }
        paths.write_job(&job)?;
    }
    Ok(job)
}

pub fn get(root: &Path, id: &str) -> Result<Value, StorageError> {
    let paths = Paths::new(root, id)?;
    let job = paths.require_job()?;
    if job.status != State::Running {
        return Ok(job.public());
    }
    let _workspace = Lease::shared(root)?;
    // A parent can have saved the job while its worker is still acquiring the lease.
    let _jobs = match files::lock(&paths.directory, "jobs.lock") {
        Ok(lock) => lock,
        Err(error) if error.code == "SPEECH_BUSY" => return Ok(paths.require_job()?.public()),
        Err(error) => return Err(error),
    };
    Ok(recover(&paths, job)?.public())
}

pub fn run_worker(
    root: &Path,
    id: &str,
    launch_id: &str,
    acknowledge: impl FnOnce(),
) -> Result<(), StorageError> {
    let paths = Paths::new(root, id)?;
    let _workspace = Lease::shared(root)?;
    let _generation = files::lock(&paths.directory, "generation.lock")?;
    let _job = paths.lock_job()?;
    let mut job = paths.require_job()?;
    let request_file = paths.path("request.json")?;
    let mut request: Request =
        files::read_json(&request_file)?.ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
    if job.status != State::Running
        || request.launch_id != launch_id
        || request.request_hash != job.request_hash
        || Utf8.hash(&json!([
            job.profile_id,
            job.profile_version,
            request.segments,
            request.instruction
        ])) != job.request_hash
    {
        return Err(StorageError::new("INVALID_STATE_TRANSITION"));
    }
    let stored = profiles::load(&paths.directory, &job.profile_id)?;
    if stored.profile.version != job.profile_version || stored.profile.format != job.format {
        return Err(StorageError::new("VERSION_CONFLICT"));
    }
    let secret = stored.secret()?;
    acknowledge();
    if let Err(error) = generate(
        &paths,
        &request_file,
        &mut job,
        &mut request,
        &stored.profile,
        &secret,
    ) {
        let message = match error.code {
            "TTS_AUTH" => "语音提供方拒绝鉴权。请核对密钥和提供方配置。",
            "TTS_RATE_LIMIT" => "语音提供方限制了请求。请核对用量后重试。",
            "TTS_PROVIDER_ERROR" => "语音提供方请求失败。请核对模型、音色和服务状态。",
            "INVALID_AUDIO" => "返回的音频无效、超限或分段采样参数不一致。",
            _ => "任务无法保存或网络结果未确认。请检查后重新发起。",
        };
        job.fail(State::Failed, error.code, message);
        paths.write_job(&job)?;
    }
    Ok(())
}

fn generate(
    paths: &Paths,
    request_file: &Path,
    job: &mut Job,
    request: &mut Request,
    profile: &profiles::Profile,
    secret: &[u8],
) -> Result<(), StorageError> {
    let multi = request.segments.len() > 1;
    let mut dialogue = Dialogue::new();
    let mut single = Vec::new();
    for position in 0..request.segments.len() {
        let index = position + 1;
        let path = paths.path(&format!("part-{index}"))?;
        let bytes = if path.is_file() {
            let bytes = read_audio(&path)?;
            profile.format.duration(&bytes)?;
            bytes
        } else {
            request.in_flight = Some(index);
            files::write_json(request_file, request)?;
            let segment = &request.segments[position];
            let (bytes, _) = providers::synthesize(
                Synthesis {
                    provider: profile.provider,
                    endpoint: &profile.endpoint,
                    model: &profile.model,
                    voice: segment.voice.as_deref().unwrap_or(&profile.voice),
                    text: &segment.text,
                    instruction: request.instruction.as_deref(),
                    format: profile.format,
                },
                secret,
            )?;
            files::write(&path, &bytes)?;
            request.in_flight = None;
            files::write_json(request_file, request)?;
            bytes
        };
        if multi {
            dialogue.append(&bytes, &request.segments[position])?;
        } else {
            single = bytes;
        }
        job.completed_segments = index;
        paths.write_job(job)?;
    }
    let (data, duration, captions) = if multi {
        let (data, duration, captions) = dialogue.finish()?;
        (data, duration, Some(captions))
    } else {
        let duration = job.format.duration(&single)?;
        (single, duration, None)
    };
    files::write(&paths.path("audio")?, &data)?;
    job.status = State::Ready;
    job.captions = captions;
    job.duration = Some(duration);
    job.sha256 = Some(assets::digest(&data));
    paths.write_job(job)
}

pub(super) fn read_audio(path: &Path) -> Result<Vec<u8>, StorageError> {
    let file = File::open(path).map_err(|_| StorageError::new("AUDIO_MISSING"))?;
    let mut bytes = Vec::new();
    file.take(MAX_AUDIO_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| StorageError::new("AUDIO_MISSING"))?;
    if bytes.len() > MAX_AUDIO_BYTES {
        return Err(StorageError::new("INVALID_AUDIO"));
    }
    Ok(bytes)
}

pub(super) struct ReadyAudio {
    pub(super) reference: assets::AudioRef,
    pub(super) bytes: Vec<u8>,
    pub(super) duration: f64,
    pub(super) captions: Option<Vec<Value>>,
}

pub(super) fn ready_audio(root: &Path, id: &str) -> Result<ReadyAudio, StorageError> {
    let paths = Paths::new(root, id)?;
    let job = paths.require_job()?;
    if job.status != State::Ready {
        return Err(StorageError::new("INVALID_STATE_TRANSITION"));
    }
    let incomplete = || StorageError::new("INVALID_SPEECH_STORE");
    let reference = assets::AudioRef {
        sha256: job.sha256.ok_or_else(incomplete)?,
        format: job.format,
    };
    let staged = paths.path("audio")?;
    let bytes = match read_audio(&staged) {
        Ok(bytes) => {
            if assets::digest(&bytes) != reference.sha256 {
                return Err(StorageError::new("INVALID_AUDIO"));
            }
            reference.format.duration(&bytes)?;
            bytes
        }
        Err(error) if error.code == "AUDIO_MISSING" => assets::read(root, &reference)?.bytes,
        Err(error) => return Err(error),
    };
    let duration = job
        .duration
        .filter(|duration| duration.is_finite() && *duration > 0.0)
        .ok_or_else(incomplete)?;
    Ok(ReadyAudio {
        reference,
        bytes,
        duration,
        captions: job.captions,
    })
}
