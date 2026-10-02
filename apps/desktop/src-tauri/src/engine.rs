use super::workspace::{build_engine_command, discover_project_root, resolve_workspace};
use serde_json::Value;
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, State};

pub(super) struct EngineClient {
    pub(super) child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
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
        Ok(Self {
            child,
            stdin,
            stdout: BufReader::new(stdout),
        })
    }

    pub(super) fn call(&mut self, request: &Value) -> Result<Value, String> {
        let line =
            serde_json::to_string(request).map_err(|error| format!("请求序列化失败：{error}"))?;
        self.stdin
            .write_all(line.as_bytes())
            .map_err(|error| format!("Engine 写入失败：{error}"))?;
        self.stdin
            .write_all(b"\n")
            .map_err(|error| format!("Engine 写入失败：{error}"))?;
        self.stdin
            .flush()
            .map_err(|error| format!("Engine 刷新失败：{error}"))?;
        let mut response = String::new();
        let read = self
            .stdout
            .read_line(&mut response)
            .map_err(|error| format!("Engine 读取失败：{error}"))?;
        if read == 0 {
            return Err("Engine 已退出，没有返回响应".to_string());
        }
        serde_json::from_str(response.trim())
            .map_err(|error| format!("Engine 返回了无效 JSON：{error}"))
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
