use super::workspace::{build_engine_command, discover_project_root, resolve_workspace};
use serde_json::Value;
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Stdio};
use std::sync::{
    mpsc::{self, Receiver, Sender},
    Mutex,
};
use std::time::Duration;
use tauri::{AppHandle, State};

pub(super) struct EngineClient {
    pub(super) child: Child,
    requests: Sender<String>,
    responses: Receiver<Result<Value, String>>,
}

impl EngineClient {
    pub(super) fn start(app: &AppHandle) -> Result<Self, String> {
        // Only development builds need the source tree for the Python fallback.
        // A packaged release must run from an installed copy with no repository present.
        let source_workspace = if cfg!(debug_assertions) {
            Some(discover_project_root()?.join("packages").join("core"))
        } else {
            None
        };
        let workspace = resolve_workspace(app, source_workspace.as_deref())?;
        fs::create_dir_all(&workspace)
            .map_err(|error| format!("无法创建 StudyFlow 工作区：{error}"))?;
        let mut command = build_engine_command(app, source_workspace.as_deref())?;
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW for the managed Engine.
        }
        // The Engine keeps its database and Markdown paths under the selected
        // workspace. Release builds use that workspace as cwd; development keeps
        // the source package as cwd for `python -m studyflow.engine`.
        let working_directory = source_workspace.as_deref().unwrap_or(workspace.as_path());
        command
            .current_dir(working_directory)
            .env("STUDYFLOW_WORKSPACE", &workspace)
            .env("PYTHONIOENCODING", "utf-8")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());

        // Development keeps the existing checked-in database for compatibility.
        // Packaged builds intentionally use the managed .studyflow path under
        // the selected workspace, never a database from the source tree.
        if env::var_os("STUDYFLOW_WORKSPACE").is_none()
            && env::var_os("STUDYFLOW_DATABASE_PATH").is_none()
            && env::var_os("STUDYFLOW_DATABASE_URL").is_none()
            && cfg!(debug_assertions)
        {
            let source_workspace = source_workspace
                .as_ref()
                .expect("debug builds must have a source workspace");
            command.env(
                "STUDYFLOW_DATABASE_PATH",
                source_workspace.join("studyflow.db"),
            );
        }

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
                let response = match reader.read_line(&mut line) {
                    Ok(0) => Err("ENGINE_EXITED: Engine已退出，写入结果待确认".to_string()),
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
        Ok(Self {
            child,
            requests,
            responses,
        })
    }

    pub(super) fn call(&mut self, request: &Value) -> Result<Value, String> {
        let line =
            serde_json::to_string(request).map_err(|error| format!("请求序列化失败：{error}"))?;
        self.requests
            .send(line)
            .map_err(|_| "ENGINE_UNCONFIRMED: Engine写入管道已关闭".to_string())?;
        let seconds = if matches!(
            request["method"].as_str(),
            Some("workspace.export" | "workspace.restore" | "system.doctor")
        ) {
            120
        } else {
            20
        };
        receive_response(&self.responses, request, Duration::from_secs(seconds))
    }
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

pub(super) fn ensure_engine(state: &State<'_, EngineState>, app: &AppHandle) -> Result<(), String> {
    let mut guard = state
        .client
        .lock()
        .map_err(|_| "Engine 状态锁已损坏".to_string())?;
    let needs_start = match guard.as_mut() {
        Some(client) => client
            .child
            .try_wait()
            .map_err(|error| format!("读取 Engine 状态失败：{error}"))?
            .is_some(),
        None => true,
    };
    if needs_start {
        *guard = Some(EngineClient::start(app)?);
    }
    Ok(())
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
    if response.get("id") != request.get("id") {
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
