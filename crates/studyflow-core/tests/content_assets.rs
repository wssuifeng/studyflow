use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Barrier};

use serde_json::{json, Value};
use studyflow_core::{
    audio::{
        assets::{self, AudioRef, Format},
        dictionary::DictionaryProvider,
    },
    documents,
    infrastructure::{config::Settings, StorageError},
    workspace::Workspace,
};

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!("studyflow-content-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        Self(root)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn wav() -> Vec<u8> {
    let mut data = b"RIFF".to_vec();
    data.extend(2036u32.to_le_bytes());
    data.extend(b"WAVEfmt ");
    data.extend(16u32.to_le_bytes());
    data.extend(1u16.to_le_bytes());
    data.extend(1u16.to_le_bytes());
    data.extend(8000u32.to_le_bytes());
    data.extend(16_000u32.to_le_bytes());
    data.extend(2u16.to_le_bytes());
    data.extend(16u16.to_le_bytes());
    data.extend(b"data");
    data.extend(2000u32.to_le_bytes());
    data.extend([0; 2000]);
    data
}

#[test]
fn workspace_assets_are_reused_by_digest_across_publishers() {
    let fixture = Fixture::new();
    let bytes = wav();
    let gate = Arc::new(Barrier::new(2));
    let reference = std::thread::scope(|scope| {
        let run = || {
            gate.wait();
            assets::publish(&fixture.0, Format::Wav, &bytes).unwrap()
        };
        let job = scope.spawn(run);
        let a = run();
        assert_eq!(a, job.join().unwrap());
        a
    });
    let path = reference.path(&fixture.0).unwrap();
    assert_eq!(path.parent().unwrap().read_dir().unwrap().count(), 1);
    let audio = assets::read(&fixture.0, &reference).unwrap();
    assert_eq!(audio.bytes, bytes);
    assert_eq!(audio.duration_seconds, 0.125);
    let pack = |end| json!({"lessons":[{"exercises":[{"type":"LISTENING_GROUP","listening":{"audio":reference,"captions":[{"start":0,"end":end,"text":"Hello"}]}}]}]});
    assert!(assets::validate_package_assets(&fixture.0, &pack(0.125)).is_ok());
    assert!(assets::validate_package_assets(&fixture.0, &pack(0.120)).is_ok());
    assert_eq!(
        assets::validate_package_assets(&fixture.0, &pack(0.2))
            .unwrap_err()
            .code,
        "INVALID_AUDIO"
    );

    fs::write(&path, "corrupt existing file").unwrap();
    assert_eq!(
        assets::publish(&fixture.0, Format::Wav, &bytes)
            .unwrap_err()
            .code,
        "INVALID_AUDIO"
    );
    assert_eq!(fs::read(&path).unwrap(), b"corrupt existing file");
    assert!(
        matches!(assets::read(&fixture.0,&reference),Err(error) if error.code=="INVALID_AUDIO")
    );
}

#[test]
fn invalid_audio_never_creates_or_publishes_an_asset() {
    let fixture = Fixture::new();
    let mut invalid = wav();
    invalid.pop();
    for (kind, data) in [
        (Format::Wav, invalid),
        (Format::Mp3, b"ID3".to_vec()),
        (Format::Wav, vec![0; assets::MAX_AUDIO_BYTES + 1]),
    ] {
        assert_eq!(
            assets::publish(&fixture.0, kind, &data).unwrap_err().code,
            "INVALID_AUDIO"
        );
    }
    assert!(fixture.0.read_dir().unwrap().next().is_none());
    let invalid = AudioRef {
        sha256: "../sample".into(),
        format: Format::Wav,
    };
    assert!(
        matches!(assets::read(&fixture.0,&invalid),Err(error) if error.code=="INVALID_ARGUMENT")
    );
    let invalid: Result<AudioRef, _> =
        serde_json::from_value(json!({"sha256":"0".repeat(64),"format":"wav","size":1}));
    assert!(invalid.is_err());
}

#[test]
fn markdown_preserves_course_metadata_and_scrubs_exec_content() {
    let fixture = Fixture::new();
    let body="---\r\ncourse: ' Course '\r\nlesson: Lesson\r\nplan_line: Plan\r\ncontent_schema: studyflow.course-package/8\r\n---\r\n\r\n# Read me\r\n\r\n# Read me\r\n\r\n[Safe](https://example.invalid) [Bad](javascript:alert%281%29)\r\n\r\n| A | B |\r\n|---|---|\r\n| a | b |\r\n\r\n<script>window.badScript()</script><style>hide</style>\r\n";
    fs::create_dir(fixture.0.join("content")).unwrap();
    let path = fixture.0.join("content/example.MARKDOWN");
    fs::write(&path, body).unwrap();
    let (_, relative) = documents::markdown_import_path(&fixture.0, &path).unwrap();
    assert_eq!(relative, "content/example.MARKDOWN");
    let (metadata, plain) = documents::parse_front_matter(body).unwrap();
    assert!(plain.starts_with("# Read me"));
    assert_eq!(
        documents::validate_import_metadata(&metadata).unwrap()["course"],
        "Course"
    );
    let output = documents::read(&fixture.0, &relative, true).unwrap();
    assert_eq!(output.file_size, body.len() as u64);
    assert!(output.markdown.starts_with("# Read me"));
    assert!(output.html.contains("id=\"read-me\""));
    assert!(output.html.contains("id=\"read-me_1\""));
    assert!(output.html.contains("<table>"));
    assert!(output.html.contains("href=\"https://example.invalid\""));
    assert!(!output.html.contains("javascript:"));
    assert!(!output.html.contains("badScript"));
    assert!(!output.html.contains("<style>"));
    let readonly = documents::read(&fixture.0, &relative, false).unwrap();
    assert!(readonly.html.is_empty());
    assert_eq!(
        readonly.content_hash,
        assets::digest(body.replace("\r\n", "\n").as_bytes())
    );
    assert!(
        matches!(documents::read(&fixture.0,"../outside.md",true),Err(error) if error.code=="PATH_OUTSIDE_WORKSPACE")
    );
    assert!(
        matches!(documents::read(&fixture.0,"content/read.json",true),Err(error) if error.code=="UNSUPPORTED_DOCUMENT_TYPE")
    );
    assert!(documents::parse_front_matter("---\n- invalid list\n---\n").is_err());
    assert!(documents::parse_front_matter("---\ninvalid: [\n---\n").is_err());
}

#[test]
fn document_check_updates_existing_row_within_callers_transaction() {
    let fixture = Fixture::new();
    let work =
        Workspace::new(Settings::resolve(&fixture.0, Path::new("workspace"), None, None).unwrap());
    work.upgrade().unwrap();
    let mut active = work.open().unwrap();
    let db = &mut active.connection;
    let relative = "lesson.md";
    let id = documents::check(&work.settings().workspace, db, relative)
        .unwrap()
        .id;
    fs::write(work.settings().workspace.join(relative), "# New body").unwrap();
    let transaction = db.transaction().unwrap();
    assert_eq!(
        documents::check(&work.settings().workspace, &transaction, relative)
            .unwrap()
            .id,
        id
    );
    transaction.rollback().unwrap();
    let state: String = db
        .query_row("SELECT status FROM documents WHERE id=?", [&id], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(state, "MISSING");
    assert_eq!(
        documents::check(&work.settings().workspace, db, relative)
            .unwrap()
            .id,
        id
    );
    let status: String = db
        .query_row("SELECT status FROM documents WHERE id=?", [id], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(status, "PRESENT");
}

#[test]
fn dictionary_returns_voice_before_background_lookup_and_reuses_metadata() {
    let provider = {
        let (started_tx, started) = std::sync::mpsc::sync_channel(1);
        let (stop, stop_rx) = std::sync::mpsc::sync_channel(1);
        let stop_rx = std::sync::Mutex::new(stop_rx);
        let provider = DictionaryProvider::with_fetch(move |word| {
            assert_eq!(word, "hello");
            started_tx.send(()).unwrap();
            stop_rx.lock().unwrap().recv().unwrap();
            Ok(
                json!([{"phonetics":[{"text":"həˈləʊ"}],"meanings":[{"partOfSpeech":"interjection","definitions":[{"definition":"A greeting."}]}]}]),
            )
        });
        let value = serde_json::to_value(provider.lookup("Hello", "en-GB", Some("Hello")).unwrap())
            .unwrap();
        assert_eq!(value["metadata_status"], "loading");
        assert_eq!(
            value["pronunciation_url"],
            "https://dict.youdao.com/dictvoice?type=1&audio=Hello"
        );
        started
            .recv_timeout(std::time::Duration::from_secs(5))
            .unwrap();
        stop.send(()).unwrap();
        provider
    };
    let start = std::time::Instant::now();
    loop {
        let value = serde_json::to_value(provider.lookup("hello", "en-GB", Some("hello")).unwrap())
            .unwrap();
        if value["metadata_status"] == "ready" {
            assert_eq!(value["from_cache"], true);
            assert_eq!(value["phonetic"], "həˈləʊ");
            assert_eq!(value["definitions"][0]["definition"], "A greeting.");
            break;
        }
        assert!(start.elapsed() < std::time::Duration::from_secs(5));
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
    let provider = DictionaryProvider::with_fetch(|_| Err(StorageError::new("FIXTURE_OFFLINE")));
    let sentence =
        serde_json::to_value(provider.lookup("Hello there", "en-US", None).unwrap()).unwrap();
    assert_eq!(sentence["metadata_status"], "not_requested");
    assert!(sentence["pronunciation_url"]
        .as_str()
        .unwrap()
        .ends_with("type=2&audio=Hello+there"));
}

#[test]
#[ignore = "Requires a restored W0.3 F4 audio fixture under STUDYFLOW_F4_WORKSPACE"]
fn reads_both_audio_formats_from_an_original_course_archive() {
    let workspace = PathBuf::from(std::env::var_os("STUDYFLOW_F4_WORKSPACE").unwrap());
    let entries = fs::read_dir(workspace.join(assets::ASSET_DIRECTORY))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(entries.len(), 2);
    let mut formats = Vec::new();
    for entry in entries {
        let path = entry.path();
        let format: Format = serde_json::from_value(Value::String(
            path.extension().unwrap().to_string_lossy().into_owned(),
        ))
        .unwrap();
        let reference = AudioRef {
            sha256: path.file_stem().unwrap().to_string_lossy().into_owned(),
            format,
        };
        let audio = assets::read(&workspace, &reference).unwrap();
        assert!(audio.duration_seconds > 0.0);
        assert_eq!(audio.bytes, fs::read(path).unwrap());
        assert_eq!(
            assets::publish(&workspace, format, &audio.bytes).unwrap(),
            reference
        );
        formats.push(format);
    }
    formats.sort();
    assert_eq!(formats, vec![Format::Wav, Format::Mp3]);
    let work = Workspace::new(Settings::resolve(&workspace, &workspace, None, None).unwrap());
    let db = work.inspect().unwrap();
    let mut statement = db
        .prepare("SELECT package_json FROM course_revisions ORDER BY course_id")
        .unwrap();
    let packages: Vec<String> = statement
        .query_map([], |row| row.get(0))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(packages.len(), 2);
    for package in packages {
        assets::validate_package_assets(&workspace, &serde_json::from_str(&package).unwrap())
            .unwrap();
    }
}
