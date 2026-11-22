use super::workspace::{build_engine_command, resolve_workspace};
use serde_json::{json, Value};
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::Path;
use std::process::{Child, Stdio};
use std::sync::{
    mpsc::{self, Receiver, Sender},
    Mutex,
};
use std::time::Duration;
use tauri::AppHandle;

const PROTOCOL: &str = "1.2";
const MAX_REPLY: u64 = 16 * 1024 * 1024 + 1;

pub(super) struct EngineClient {
    pub(super) child: Child,
    requests: Sender<String>,
    responses: Receiver<Result<Value, String>>,
}

impl EngineClient {
    pub(super) fn start(app: &AppHandle) -> Result<Self, String> {
        Self::start_in(app, &resolve_workspace(app)?)
    }

    pub(super) fn start_in(app: &AppHandle, workspace: &Path) -> Result<Self, String> {
        fs::create_dir_all(workspace)
            .map_err(|error| format!("无法创建 StudyFlow 工作区：{error}"))?;
        let version = env!("CARGO_PKG_VERSION");
        let mut command = build_engine_command(app)?;
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        command
            .arg("--managed-desktop")
            .arg(version)
            .arg(PROTOCOL)
            .current_dir(workspace)
            .env("STUDYFLOW_WORKSPACE", workspace)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());

        let mut child = command
            .spawn()
            .map_err(|error| format!("无法启动 StudyFlow Engine：{error}"))?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "Engine stdin 初始化失败".to_string())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "Engine stdout 初始化失败".to_string())?;
        let (sender, responses) = mpsc::channel();
        let (requests, outgoing) = mpsc::channel::<String>();
        let write_errors = sender.clone();
        std::thread::spawn(move || {
            let mut input = stdin;
            for line in outgoing {
                if input
                    .write_all(line.as_bytes())
                    .and_then(|_| input.write_all(b"\n"))
                    .and_then(|_| input.flush())
                    .is_err()
                {
                    let _ = write_errors
                        .send(Err("ENGINE_UNCONFIRMED: 管道写入失败，结果待确认".into()));
                    break;
                }
            }
        });
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                let response = match (&mut reader).take(MAX_REPLY).read_line(&mut line) {
                    Ok(0) => Err("ENGINE_EXITED: Engine已退出，写入结果待确认".to_string()),
                    Ok(_) if !line.ends_with('\n') => {
                        Err("INVALID_RESPONSE: Engine响应缺少分隔符或超限".into())
                    }
                    Ok(_) => serde_json::from_str(&line)
                        .map_err(|_| "INVALID_RESPONSE: Engine返回无效JSON".to_string()),
                    Err(_) => Err("ENGINE_IO: Engine读取失败，写入结果待确认".to_string()),
                };
                let terminal = response.is_err();
                if sender.send(response).is_err() || terminal {
                    break;
                }
            }
        });
        let mut client = Self {
            child,
            requests,
            responses,
        };
        let handshake = json!({"id":"desktop-handshake","method":"system.version","params":{}});
        let response = client.exchange(&handshake, Duration::from_secs(120))?;
        validate_handshake(&response, version, workspace)?;
        Ok(client)
    }

    pub(super) fn call(&mut self, request: &Value) -> Result<Value, String> {
        let seconds = if matches!(
            request["method"].as_str(),
            Some("workspace.export" | "workspace.restore" | "system.doctor")
        ) {
            120
        } else {
            20
        };
        self.exchange(request, Duration::from_secs(seconds))
    }

    fn exchange(&mut self, request: &Value, timeout: Duration) -> Result<Value, String> {
        let line =
            serde_json::to_string(request).map_err(|error| format!("请求序列化失败：{error}"))?;
        self.requests
            .send(line)
            .map_err(|_| "ENGINE_NOT_SENT: Engine写入管道已关闭".to_string())?;
        receive_response(&self.responses, request, timeout)
    }
}

fn validate_handshake(
    response: &Value,
    version: &str,
    expected_workspace: &Path,
) -> Result<(), String> {
    if response["ok"] != true {
        let error = &response["error"];
        let code = error["code"].as_str().unwrap_or("ENGINE_STARTUP_FAILED");
        let message = error["message"].as_str().unwrap_or("无法打开工作区。");
        return Err(format!("{code}: {message}"));
    }
    let data = &response["data"];
    if data["protocol_version"] != PROTOCOL
        || data["app_version"] != version
        || data["runtime"] != "rust"
    {
        return Err("ENGINE_VERSION_MISMATCH: 桌面与 Rust Engine 构建不匹配。".into());
    }
    let actual = data["workspace"]["root"]
        .as_str()
        .and_then(|root| fs::canonicalize(root).ok());
    if actual.is_none() || actual != fs::canonicalize(expected_workspace).ok() {
        return Err("ENGINE_WORKSPACE_MISMATCH: Engine 返回的工作区与所选目录不一致。".into());
    }
    Ok(())
}

impl Drop for EngineClient {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[derive(Default)]
pub(super) struct EngineState {
    pub(super) client: Mutex<Option<EngineClient>>,
}

pub(super) fn ensure_engine<'a>(
    guard: &'a mut Option<EngineClient>,
    app: &AppHandle,
) -> Result<&'a mut EngineClient, String> {
    let start = match guard.as_mut() {
        Some(client) => client
            .child
            .try_wait()
            .map_err(|_| "Engine 状态读取失败。".to_string())?
            .is_some(),
        None => true,
    };
    if start {
        *guard = Some(EngineClient::start(app)?);
    }
    guard
        .as_mut()
        .ok_or_else(|| "Engine 尚未启动。".to_string())
}

fn receive_response(
    receiver: &Receiver<Result<Value, String>>,
    request: &Value,
    timeout: Duration,
) -> Result<Value, String> {
    let response = receiver
        .recv_timeout(timeout)
        .map_err(|error| match error {
            mpsc::RecvTimeoutError::Timeout => {
                "ENGINE_TIMEOUT: 请求超时，写入结果待确认；保留原幂等键".to_string()
            }
            mpsc::RecvTimeoutError::Disconnected => {
                "ENGINE_UNCONFIRMED: Engine断线，写入结果待确认".to_string()
            }
        })??;
    if response.get("id") != request.get("id") || !response["ok"].is_boolean() {
        return Err("INVALID_RESPONSE: 响应ID不匹配，写入结果待确认".into());
    }
    Ok(response)
}
#[cfg(test)]
mod rpc_tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn hung_response_has_deadline() {
        let (_sender, receiver) = mpsc::channel();
        let started = std::time::Instant::now();
        let result = receive_response(&receiver, &json!({"id":1}), Duration::from_millis(20));
        assert!(result.unwrap_err().starts_with("ENGINE_TIMEOUT"));
        assert!(started.elapsed() < Duration::from_secs(1));
    }
    #[test]
    fn late_or_wrong_response_is_not_consumed_as_success() {
        let (sender, receiver) = mpsc::channel();
        sender.send(Ok(json!({"id":7,"ok":true}))).unwrap();
        assert!(
            receive_response(&receiver, &json!({"id":8}), Duration::from_secs(1))
                .unwrap_err()
                .starts_with("INVALID_RESPONSE")
        );
    }
    #[test]
    fn handshake_rejects_the_previous_engine_even_at_the_same_release_version() {
        let workspace = std::env::temp_dir();
        let mut reply = json!({"ok":true,"data":{"app_version":"1.8.27","protocol_version":"1.2","workspace":{"root":workspace}}});
        assert!(validate_handshake(&reply, "1.8.27", &workspace)
            .unwrap_err()
            .starts_with("ENGINE_VERSION_MISMATCH"));
        reply["data"]["runtime"] = json!("rust");
        assert!(validate_handshake(&reply, "1.8.27", &workspace).is_ok());
        assert!(
            validate_handshake(&reply, "1.8.27", &workspace.join("another-workspace"))
                .unwrap_err()
                .starts_with("ENGINE_WORKSPACE_MISMATCH")
        );
    }

    #[test]
    fn process_exit_is_unconfirmed() {
        let (sender, receiver) = mpsc::channel();
        drop(sender);
        assert!(
            receive_response(&receiver, &json!({"id":1}), Duration::from_secs(1))
                .unwrap_err()
                .starts_with("ENGINE_UNCONFIRMED")
        );
    }
}
