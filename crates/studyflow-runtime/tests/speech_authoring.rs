use std::{
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

use serde_json::json;
use studyflow_core::{audio::assets, speech_generation::adoption};

struct Fixture(PathBuf);

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn adoption_requires_verified_bytes_preserves_existing_asset_and_replays_without_staging() {
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let fixture = Fixture(std::env::temp_dir().join(format!("studyflow-adoption-{suffix:x}")));
    let speech = fixture.0.join(".studyflow/speech");
    fs::create_dir_all(&speech).unwrap();
    let waveform=b"RIFF\x28\0\0\0WAVEfmt \x10\0\0\0\x01\0\x01\0\x04\0\0\0\x04\0\0\0\x01\0\x08\0data\x04\0\0\0\x80\x80\x80\x80";
    let id = "2f339f00-1111-4000-aaa0-abcdef123456";
    let digest = assets::digest(waveform);
    let job = json!({"job_id":id,"request_hash":"old-hash","profile_id":"default","profile_version":1,"status":"ready","format":"wav","completed_segments":1,"total_segments":1,"sha256":digest,"duration":1.0});
    fs::write(speech.join(format!("{id}.json")), job.to_string()).unwrap();
    let staging = speech.join(format!("{id}.audio"));
    fs::write(&staging, b"truncated before adoption").unwrap();
    assert_eq!(
        adoption::adopt(&fixture.0, id).unwrap_err().code,
        "INVALID_AUDIO"
    );
    let asset_dir = fixture.0.join(assets::ASSET_DIRECTORY);
    assert!(!asset_dir.exists());
    fs::write(&staging, waveform).unwrap();
    fs::create_dir_all(&asset_dir).unwrap();
    let existing = asset_dir.join(format!("{digest}.wav"));
    fs::write(&existing, b"unmatched content").unwrap();
    assert_eq!(
        adoption::adopt(&fixture.0, id).unwrap_err().code,
        "INVALID_AUDIO"
    );
    assert_eq!(fs::read(&existing).unwrap(), b"unmatched content");
    fs::remove_file(&existing).unwrap();
    let adopted = adoption::adopt(&fixture.0, id).unwrap();
    assert_eq!(adopted["audio"], json!({"sha256":digest,"format":"wav"}));
    fs::remove_file(&staging).unwrap();
    assert_eq!(adoption::adopt(&fixture.0, id).unwrap(), adopted);
    assert_eq!(fs::read(&existing).unwrap(), waveform);
}
