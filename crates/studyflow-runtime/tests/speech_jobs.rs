#![cfg(windows)]

use std::{
    fs,
    io::{BufRead, BufReader, Read, Write},
    net::TcpListener,
    path::PathBuf,
    process::Command,
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

use serde_json::{json, Value};

struct Fixture(PathBuf);
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

impl Fixture {
    fn call(&self, method: &str, params: Value) -> Value {
        let file = self.0.join("params.json");
        fs::write(&file, serde_json::to_vec(&params).unwrap()).unwrap();
        let output = Command::new(env!("CARGO_BIN_EXE_studyflow"))
            .env_remove("STUDYFLOW_DATABASE_URL")
            .env_remove("STUDYFLOW_WORKSPACE_ROOT")
            .env_remove("STUDYFLOW_DATABASE_PATH")
            .env("STUDYFLOW_WORKSPACE", &self.0)
            .args(["call", "--method", method, "--file"])
            .arg(file)
            .args(["--format", "json"])
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{method}: {}",
            String::from_utf8_lossy(&output.stdout)
        );
        assert!(output.stderr.is_empty());
        serde_json::from_slice(&output.stdout).unwrap()
    }
}

fn wav() -> Vec<u8> {
    let samples = 1600u32;
    let mut bytes = b"RIFF".to_vec();
    bytes.extend_from_slice(&(36 + samples).to_le_bytes());
    bytes.extend_from_slice(b"WAVEfmt \x10\0\0\0\x01\0\x01\0");
    bytes.extend_from_slice(&8000u32.to_le_bytes());
    bytes.extend_from_slice(&8000u32.to_le_bytes());
    bytes.extend_from_slice(b"\x01\0\x08\0data");
    bytes.extend_from_slice(&samples.to_le_bytes());
    bytes.resize(44 + samples as usize, 128);
    bytes
}

#[test]
fn short_cli_exits_before_provider_replies_and_an_independent_process_polls_job() {
    let root = Fixture(std::env::temp_dir().join(format!(
            "studyflow-worker-{:x}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        )));
    fs::create_dir(&root.0).unwrap();
    let server = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let endpoint = format!("http://{}/audio/speech", server.local_addr().unwrap());
    let (received_tx, received_rx) = mpsc::channel();
    let (respond_tx, respond_rx) = mpsc::channel();
    let supplier = thread::spawn(move || {
        let (mut stream, _) = server.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let mut reader = BufReader::new(&mut stream);
        let mut length = 0;
        loop {
            let mut line = String::new();
            assert!(reader.read_line(&mut line).unwrap() > 0);
            if line == "\r\n" {
                break;
            }
            if let Some((name, value)) = line.split_once(':') {
                if name.eq_ignore_ascii_case("content-length") {
                    length = value.trim().parse().unwrap();
                }
            }
        }
        let mut payload = vec![0; length];
        reader.read_exact(&mut payload).unwrap();
        received_tx
            .send(serde_json::from_slice::<Value>(&payload).unwrap())
            .unwrap();
        respond_rx.recv_timeout(Duration::from_secs(10)).unwrap();
        let wave = wav();
        write!(
            stream,
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            wave.len()
        )
        .unwrap();
        stream.write_all(&wave).unwrap();
    });
    let saved=root.call("speech.profile.save",json!({"provider":"compatible","endpoint":endpoint,"model":"fixture","voice":"speaker","format":"wav","credential":"fixture-worker-key","expected_version":0}));
    assert_eq!(saved["version"], 1);
    let id = "c6d7fd54-0000-4000-8000-330000000001";
    let params =
        json!({"job_id":id,"expected_profile_version":1,"text":"A synthetic listening prompt."});
    let start = root.call("speech.job.start", params.clone());
    assert_eq!(start["status"], "running");
    assert_eq!(
        received_rx.recv_timeout(Duration::from_secs(5)).unwrap()["input"],
        params["text"]
    );
    assert_eq!(
        root.call("speech.job.get", json!({"job_id":id}))["status"],
        "running"
    );
    respond_tx.send(()).unwrap();
    supplier.join().unwrap();
    let deadline = Instant::now() + Duration::from_secs(8);
    let ready = loop {
        let job = root.call("speech.job.get", json!({"job_id":id}));
        if job["status"] == "ready" {
            break job;
        }
        assert_eq!(job["status"], "running", "{job}");
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(50));
    };
    assert_eq!(ready["duration"], 0.2);
    assert_eq!(ready["completed_segments"], 1);
    assert_eq!(root.call("speech.job.start", params), ready);
    let request = fs::read_to_string(
        root.0
            .join(".studyflow/speech")
            .join(format!("{id}.request.json")),
    )
    .unwrap();
    assert!(!request.contains("fixture-worker-key"));
}
