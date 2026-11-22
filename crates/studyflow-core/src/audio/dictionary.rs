use std::collections::{HashMap, HashSet, VecDeque};
use std::io::Read;
use std::sync::{mpsc, Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use percent_encoding::{utf8_percent_encode, NON_ALPHANUMERIC};
use serde::Serialize;
use serde_json::Value;

use crate::infrastructure::StorageError;

const MAX_PENDING: usize = 16;
const MAX_CACHE: usize = 256;
const MAX_RESPONSE: u64 = 256 * 1024;

type Lookup = dyn Fn(&str) -> Result<Value, StorageError> + Send + Sync;

#[derive(Clone, Default, Serialize)]
struct Definition {
    part_of_speech: String,
    definition: String,
}

#[derive(Clone, Serialize)]
struct Metadata {
    phonetic: String,
    definitions: Vec<Definition>,
    definition_available: bool,
    metadata_status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    notice: Option<&'static str>,
}

impl Metadata {
    fn empty(status: &'static str, notice: Option<&'static str>) -> Self {
        Self {
            phonetic: String::new(),
            definitions: Vec::new(),
            definition_available: false,
            metadata_status: status,
            notice,
        }
    }
}

#[derive(Serialize)]
pub struct Entry {
    pub target: String,
    pub pronunciation_url: String,
    pub pronunciation_provider: &'static str,
    pub requested_accent: String,
    pub accent_verified: bool,
    pub definition_provider: &'static str,
    pub from_cache: bool,
    #[serde(flatten)]
    metadata: Metadata,
}

impl Entry {
    pub(crate) fn use_course_phonetic(&mut self, phonetic: &str) {
        if self.metadata.phonetic.is_empty() {
            self.metadata.phonetic = phonetic.to_owned();
        }
    }
}

#[derive(Default)]
struct State {
    closed: bool,
    cached: HashMap<String, (Instant, Metadata)>,
    order: VecDeque<String>,
    pending: HashSet<String>,
}

pub struct DictionaryProvider {
    state: Arc<Mutex<State>>,
    fetch: Arc<Lookup>,
    sender: OnceLock<mpsc::SyncSender<String>>,
}

impl Default for DictionaryProvider {
    fn default() -> Self {
        Self::with_fetch(fetch_metadata)
    }
}

impl DictionaryProvider {
    pub fn with_fetch(
        fetch: impl Fn(&str) -> Result<Value, StorageError> + Send + Sync + 'static,
    ) -> Self {
        Self {
            state: Arc::default(),
            fetch: Arc::new(fetch),
            sender: OnceLock::new(),
        }
    }

    pub fn lookup(
        &self,
        target: &str,
        accent: &str,
        word: Option<&str>,
    ) -> Result<Entry, StorageError> {
        let voice = match accent {
            "en-US" => "2",
            "en-GB" => "1",
            _ => return Err(StorageError::new("INVALID_ARGUMENT")),
        };
        let query = url::form_urlencoded::Serializer::new(String::new())
            .append_pair("type", voice)
            .append_pair("audio", target)
            .finish();
        let (metadata, from_cache) = word.filter(|word| !word.is_empty()).map_or_else(
            || (Metadata::empty("not_requested", None), false),
            |word| self.queue(word),
        );
        Ok(Entry {
            target: target.into(),
            pronunciation_url: format!("https://dict.youdao.com/dictvoice?{query}"),
            pronunciation_provider: "youdao-dictionary",
            requested_accent: accent.into(),
            accent_verified: false,
            definition_provider: "dictionaryapi.dev",
            from_cache,
            metadata,
        })
    }

    fn queue(&self, word: &str) -> (Metadata, bool) {
        let word = icu_casemap::CaseMapper::new()
            .fold_string(word)
            .into_owned();
        let mut state = self.state.lock().expect("dictionary state");
        if let Some((expires, metadata)) = state.cached.get(&word) {
            if Instant::now() < *expires {
                return (metadata.clone(), true);
            }
        }
        if state.pending.len() < MAX_PENDING && !state.pending.contains(&word) {
            let sender = self.sender.get_or_init(|| self.workers());
            if sender.try_send(word.clone()).is_ok() {
                state.pending.insert(word.clone());
            }
        }
        let cached = state.cached.get(&word);
        let mut metadata = cached
            .map(|(_, entry)| entry.clone())
            .unwrap_or_else(|| Metadata::empty("loading", None));
        (metadata.metadata_status, metadata.notice) = if state.pending.contains(&word) {
            ("loading", Some("释义/音标后台读取中，发音与答题可继续。"))
        } else {
            ("deferred", Some("辅助查询已排满，本项仍可发音和作答。"))
        };
        (metadata, cached.is_some())
    }
    fn workers(&self) -> mpsc::SyncSender<String> {
        let (sender, receiver) = mpsc::sync_channel::<String>(MAX_PENDING);
        let receiver = Arc::new(Mutex::new(receiver));
        for index in 0..2 {
            let receiver = Arc::clone(&receiver);
            let fetch = Arc::clone(&self.fetch);
            let state = Arc::clone(&self.state);
            let _ = std::thread::Builder::new()
                .name(format!("studyflow-dictionary-{index}"))
                .spawn(move || loop {
                    let word = receiver.lock().expect("dictionary receiver").recv();
                    let Ok(word) = word else {
                        return;
                    };
                    if state.lock().expect("dictionary state").closed {
                        return;
                    }
                    let mut metadata = match fetch(&word) {
                        Ok(payload) => parse(&payload),
                        Err(_) => Metadata::empty(
                            "unavailable",
                            Some("释义/音标暂不可用；发音可独立尝试，失败不阻塞学习。"),
                        ),
                    };
                    let ttl = if metadata.definition_available {
                        3600
                    } else {
                        30
                    };
                    let mut state = state.lock().expect("dictionary state");
                    if state.closed {
                        return;
                    }
                    if !metadata.definition_available {
                        if let Some((_, previous)) = state
                            .cached
                            .get(&word)
                            .filter(|(_, entry)| entry.definition_available)
                        {
                            metadata = previous.clone();
                            metadata.metadata_status = "unavailable";
                            metadata.notice =
                                Some("网络词典不可用，使用本次运行已缓存的辅助信息。");
                        }
                    }
                    if !state.cached.contains_key(&word) {
                        if state.cached.len() >= MAX_CACHE {
                            if let Some(old) = state.order.pop_front() {
                                state.cached.remove(&old);
                            }
                        }
                        state.order.push_back(word.clone());
                    }
                    state.pending.remove(&word);
                    state
                        .cached
                        .insert(word, (Instant::now() + Duration::from_secs(ttl), metadata));
                });
        }
        sender
    }
}

impl Drop for DictionaryProvider {
    fn drop(&mut self) {
        self.state.lock().expect("dictionary state").closed = true;
        // Dropping the sender lets waiting workers exit. A late network result
        // stays out of the cache after the owning runtime has closed.
    }
}

fn parse(payload: &Value) -> Metadata {
    let entry = &payload[0];
    let phonetic = entry["phonetic"]
        .as_str()
        .filter(|text| !text.is_empty())
        .or_else(|| {
            entry["phonetics"]
                .as_array()?
                .iter()
                .find_map(|entry| entry["text"].as_str().filter(|text| !text.is_empty()))
        })
        .unwrap_or_default();
    let definitions: Vec<_> = entry["meanings"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|value| value.is_object())
        .flat_map(|meaning| {
            meaning["definitions"]
                .as_array()
                .into_iter()
                .flatten()
                .filter(|value| value.is_object())
                .map(|def| Definition {
                    part_of_speech: meaning["partOfSpeech"]
                        .as_str()
                        .unwrap_or_default()
                        .chars()
                        .take(80)
                        .collect(),
                    definition: def["definition"]
                        .as_str()
                        .unwrap_or_default()
                        .chars()
                        .take(2000)
                        .collect(),
                })
        })
        .take(8)
        .collect();
    let available = !phonetic.is_empty() || !definitions.is_empty();
    Metadata {
        phonetic: phonetic.chars().take(200).collect(),
        definitions,
        definition_available: available,
        metadata_status: if available { "ready" } else { "unavailable" },
        notice: (!available).then_some("词典辅助信息暂不可用；发音和文字训练可继续。"),
    }
}

fn fetch_metadata(word: &str) -> Result<Value, StorageError> {
    let error = |error| StorageError::caused_by("DICTIONARY_UNAVAILABLE", error);
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(4))
        .user_agent("StudyFlow-local/1.8")
        .build()
        .map_err(error)?;
    let url = format!(
        "https://api.dictionaryapi.dev/api/v2/entries/en/{}",
        utf8_percent_encode(word, NON_ALPHANUMERIC)
    );
    let response = client
        .get(url)
        .send()
        .and_then(reqwest::blocking::Response::error_for_status)
        .map_err(error)?;
    let mut data = Vec::new();
    response
        .take(MAX_RESPONSE + 1)
        .read_to_end(&mut data)
        .map_err(|error| StorageError::caused_by("DICTIONARY_UNAVAILABLE", error))?;
    if data.len() as u64 > MAX_RESPONSE {
        return Err(StorageError::new("DICTIONARY_UNAVAILABLE"));
    }
    serde_json::from_slice(&data)
        .map_err(|error| StorageError::caused_by("DICTIONARY_UNAVAILABLE", error))
}
