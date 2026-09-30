use serde_json::{json, Value};
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};

struct EngineClient {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

impl EngineClient {
    fn start(app: &AppHandle) -> Result<Self, String> {
        // Only development builds need the source tree for the Python fallback.
        // A packaged release must run from an installed copy with no repository present.
        let source_workspace = if cfg!(debug_assertions) {
            Some(discover_project_root()?.join("studyflow_app"))
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
            command.env("STUDYFLOW_DATABASE_PATH", source_workspace.join("studyflow.db"));
        }

        let mut child = command
            .spawn()
            .map_err(|error| format!("无法启动 StudyFlow Engine：{error}"))?;
        let stdin = child.stdin.take().ok_or_else(|| "Engine stdin 初始化失败".to_string())?;
        let stdout = child.stdout.take().ok_or_else(|| "Engine stdout 初始化失败".to_string())?;
        Ok(Self { child, stdin, stdout: BufReader::new(stdout) })
    }

    fn call(&mut self, request: &Value) -> Result<Value, String> {
        let line = serde_json::to_string(request).map_err(|error| format!("请求序列化失败：{error}"))?;
        self.stdin.write_all(line.as_bytes()).map_err(|error| format!("Engine 写入失败：{error}"))?;
        self.stdin.write_all(b"\n").map_err(|error| format!("Engine 写入失败：{error}"))?;
        self.stdin.flush().map_err(|error| format!("Engine 刷新失败：{error}"))?;
        let mut response = String::new();
        let read = self.stdout.read_line(&mut response).map_err(|error| format!("Engine 读取失败：{error}"))?;
        if read == 0 { return Err("Engine 已退出，没有返回响应".to_string()); }
        serde_json::from_str(response.trim()).map_err(|error| format!("Engine 返回了无效 JSON：{error}"))
    }
}

impl Drop for EngineClient {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[derive(Default)]
struct EngineState {
    client: Mutex<Option<EngineClient>>,
}

fn resolve_workspace(app: &AppHandle, source_workspace: Option<&Path>) -> Result<PathBuf, String> {
    if let Some(value) = env::var_os("STUDYFLOW_WORKSPACE") {
        return Ok(PathBuf::from(value));
    }
    if cfg!(debug_assertions) {
        return source_workspace
            .map(Path::to_path_buf)
            .ok_or_else(|| "开发模式找不到 StudyFlow 源码工作区".to_string());
    }
    app.path()
        .app_data_dir()
        .map_err(|error| format!("无法确定 StudyFlow 应用数据目录：{error}"))
}

fn build_engine_command(app: &AppHandle, source_workspace: Option<&Path>) -> Result<Command, String> {
    let packaged_candidates = [
        env::var_os("STUDYFLOW_ENGINE_PATH").map(PathBuf::from),
        app.path().resource_dir().ok().map(|root| root.join("binaries").join("studyflow-engine.exe")),
        app.path().resource_dir().ok().map(|root| root.join("studyflow-engine.exe")),
        std::env::current_exe().ok().and_then(|path| path.parent().map(|root| root.join("studyflow-engine.exe"))),
    ];
    if let Some(engine_path) = packaged_candidates.into_iter().flatten().find(|path| path.is_file()) {
        return Ok(Command::new(engine_path));
    }

    if !cfg!(debug_assertions) {
        return Err("找不到打包的 StudyFlow Engine；正式运行不会回退到系统 Python。请重新构建包含 binaries/studyflow-engine.exe 的桌面包。".to_string());
    }

    let source_workspace = source_workspace
        .ok_or_else(|| "开发模式找不到 StudyFlow 源码工作区".to_string())?;
    let python = env::var_os("STUDYFLOW_PYTHON")
        .map(PathBuf::from)
        .filter(|path| path.exists())
        .unwrap_or_else(|| {
            let candidate = source_workspace.join(".venv").join("Scripts").join("python.exe");
            if candidate.exists() { candidate } else { PathBuf::from("python") }
        });
    let mut command = Command::new(python);
    command.arg("-m").arg("studyflow.engine");
    Ok(command)
}

fn discover_project_root() -> Result<PathBuf, String> {
    if let Some(value) = env::var_os("STUDYFLOW_PROJECT_ROOT") {
        let root = PathBuf::from(value);
        if root.join("studyflow_app").is_dir() { return Ok(root); }
    }
    let current = env::current_dir().map_err(|error| format!("无法获取当前目录：{error}"))?;
    let candidates = [current.clone(), current.join(".."), current.join("../..")];
    candidates.into_iter().map(|path| path.canonicalize().unwrap_or(path)).find(|path| path.join("studyflow_app").is_dir()).ok_or_else(|| "找不到包含 studyflow_app 的项目工作区，请设置 STUDYFLOW_PROJECT_ROOT".to_string())
}

fn ensure_engine(state: &State<'_, EngineState>, app: &AppHandle) -> Result<(), String> {
    let mut guard = state.client.lock().map_err(|_| "Engine 状态锁已损坏".to_string())?;
    let needs_start = match guard.as_mut() {
        Some(client) => client.child.try_wait().map_err(|error| format!("读取 Engine 状态失败：{error}"))?.is_some(),
        None => true,
    };
    if needs_start {
        *guard = Some(EngineClient::start(app)?);
    }
    Ok(())
}

#[tauri::command]
fn engine_call(app: AppHandle, state: State<'_, EngineState>, request: Value) -> Result<Value, String> {
    ensure_engine(&state, &app)?;
    let mut guard = state.client.lock().map_err(|_| "Engine 状态锁已损坏".to_string())?;
    let client = guard.as_mut().ok_or_else(|| "Engine 尚未启动".to_string())?;
    client.call(&request)
}

#[tauri::command]
fn engine_status(app: AppHandle, state: State<'_, EngineState>) -> Result<Value, String> {
    ensure_engine(&state, &app)?;
    let mut guard = state.client.lock().map_err(|_| "Engine 状态锁已损坏".to_string())?;
    let running = guard.as_mut()
        .ok_or_else(|| "Engine 尚未启动".to_string())?
        .child
        .try_wait()
        .map_err(|error| format!("读取 Engine 状态失败：{error}"))?
        .is_none();
    Ok(json!({ "running": running, "managed": true }))
}

pub fn run() {
    tauri::Builder::default()
        .manage(EngineState::default())
        .setup(|app| {
            let state = app.state::<EngineState>();
            ensure_engine(&state, &app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![engine_call, engine_status])
        .run(tauri::generate_context!())
        .expect("启动 StudyFlow Desktop 失败");
}
