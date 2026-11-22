use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpListener,
    thread,
    time::Duration,
};

use serde_json::Value;
use studyflow_core::{
    audio::assets::Format,
    speech_generation::providers::{self, Provider, Synthesis},
};

fn response(status: &str, extra: &str, body: &[u8]) -> Vec<u8> {
    let mut data = format!(
        "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n{extra}\r\n",
        body.len()
    )
    .into_bytes();
    data.extend_from_slice(body);
    data
}

fn synthesize(
    wire: Vec<u8>,
) -> (
    Result<(Vec<u8>, f64), studyflow_core::infrastructure::StorageError>,
    Value,
) {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let endpoint = format!("http://{}/v1/audio/speech", listener.local_addr().unwrap());
    let worker = thread::spawn(move || {
        let (mut socket, _) = listener.accept().unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let mut reader = BufReader::new(&mut socket);
        let mut line = String::new();
        reader.read_line(&mut line).unwrap();
        assert_eq!(line, "POST /v1/audio/speech HTTP/1.1\r\n");
        let mut length = 0;
        let mut auth = false;
        loop {
            line.clear();
            assert_ne!(reader.read_line(&mut line).unwrap(), 0);
            if line == "\r\n" {
                break;
            }
            let (name, value) = line.split_once(':').unwrap();
            match name.to_ascii_lowercase().as_str() {
                "content-length" => length = value.trim().parse().unwrap(),
                "authorization" => auth = value.trim() == "Bearer fixture-only-http-key",
                _ => {}
            }
        }
        assert!(auth);
        let mut body = vec![0; length];
        reader.read_exact(&mut body).unwrap();
        socket.write_all(&wire).unwrap();
        serde_json::from_slice(&body).unwrap()
    });
    let result = providers::synthesize(
        Synthesis {
            provider: Provider::Compatible,
            endpoint: &endpoint,
            model: "fixture-tts",
            voice: "synthetic",
            format: Format::Wav,
            text: "This is a test.",
            instruction: Some("Speak slowly."),
        },
        b"fixture-only-http-key",
    );
    (result, worker.join().unwrap())
}

#[test]
fn provider_limits_and_errors_do_not_leak_response_bodies() {
    let cases = [
        ("401 Unauthorized", "", "TTS_AUTH"),
        ("403 Forbidden", "", "TTS_AUTH"),
        ("429 Too Many Requests", "", "TTS_RATE_LIMIT"),
        (
            "302 Found",
            "Location: http://127.0.0.1:1/other\r\n",
            "TTS_PROVIDER_ERROR",
        ),
        ("200 OK", "", "INVALID_AUDIO"),
    ];
    for (status, extra, code) in cases {
        let (result, payload) = synthesize(response(status, extra, b"fixture upstream details"));
        assert_eq!(payload["instructions"], "Speak slowly.");
        assert!(payload.get("instruction").is_none());
        let error = result.unwrap_err();
        assert_eq!(error.code, code);
        assert!(!format!("{error:?}").contains("fixture"));
    }
    let (large, _) = synthesize(
        b"HTTP/1.1 200 OK\r\nContent-Length: 8388609\r\nConnection: close\r\n\r\n".to_vec(),
    );
    assert_eq!(large.unwrap_err().code, "INVALID_AUDIO");
}

#[test]
fn compatible_endpoint_requires_tls_except_loopback_and_a_complete_path() {
    for endpoint in [
        "http://localhost:8000/audio",
        "http://[::1]:9012/speech",
        "https://voice.example.com/v1/audio/speech",
    ] {
        assert!(providers::validate_endpoint(endpoint).is_ok(), "{endpoint}");
    }
    for endpoint in [
        "http://voice.example.com/speech",
        "https://voice.example.com/",
        "https://@voice.example.com/speech",
        "https://user:secret@voice.example.com/speech",
        "https://voice.example.com/speech#x",
        "https://voice.example.com/speech?token=x",
    ] {
        assert_eq!(
            providers::validate_endpoint(endpoint).unwrap_err().code,
            "INVALID_TTS_ENDPOINT"
        );
    }
}
