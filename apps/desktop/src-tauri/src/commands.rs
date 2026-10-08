use super::engine::{ensure_engine, EngineState};
use serde_json::{json, Value};
use tauri::{AppHandle, Manager};

#[tauri::command]
pub(super) async fn engine_call(app: AppHandle, request: Value) -> Result<Value, String> {
    // A slow database/stdio request must not freeze window close, pin or drag events.
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<EngineState>();
        let started=std::time::Instant::now();
        let mut guard=loop {
            match state.client.try_lock() {
                Ok(guard)=>break guard,
                Err(std::sync::TryLockError::Poisoned(_))=>return Err("Engine状态锁损坏".into()),
                Err(_) if started.elapsed()>std::time::Duration::from_secs(5)=>return Ok(json!({"id":request.get("id"),"ok":false,"error":{"code":"ENGINE_BUSY","message":"Engine正在处理较长请求，本请求尚未发送","next_action":"保留输入，稍后使用原幂等键重试。"}})),
                Err(_)=>std::thread::sleep(std::time::Duration::from_millis(10)),
            }
        };
        let start = guard.as_mut().map(|c| c.child.try_wait().map(|v|v.is_some())).transpose().map_err(|_| "Engine状态读取失败".to_string())?.unwrap_or(true);
        if start { *guard = Some(super::engine::EngineClient::start(&app)?); }
        let client = guard
            .as_mut()
            .ok_or_else(|| "Engine 尚未启动".to_string())?;
        match client.call(&request) {
            Ok(response) => Ok(response),
            Err(message) => {
                // Dropping the uncertain transport prevents a late response from being consumed by another request.
                *guard = None;
                let code = if message.starts_with("ENGINE_TIMEOUT") { "ENGINE_TIMEOUT" } else { "ENGINE_UNCONFIRMED" };
                Ok(json!({"id":request.get("id"),"ok":false,"error":{"code":code,"message":message,"next_action":"写入结果未确认；回读工作区或按原幂等键重试，不要生成新键。"}}))
            }
        }
    })
    .await
    .map_err(|error| format!("Engine 请求任务未正常返回：{error}"))?
}

#[tauri::command]
pub(super) async fn engine_status(app: AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<EngineState>();
        if state.client.try_lock().is_err() {
            return Ok(json!({"running":true,"managed":true,"busy":true}));
        }
        ensure_engine(&state, &app)?;
        let mut guard = state
            .client
            .lock()
            .map_err(|_| "Engine 状态锁已损坏".to_string())?;
        let running = guard
            .as_mut()
            .ok_or_else(|| "Engine 尚未启动".to_string())?
            .child
            .try_wait()
            .map_err(|error| format!("读取 Engine 状态失败：{error}"))?
            .is_none();
        Ok(json!({ "running": running, "managed": true }))
    })
    .await
    .map_err(|error| format!("Engine 状态任务未正常返回：{error}"))?
}

#[tauri::command]
pub(super) async fn switch_workspace(app: AppHandle, path: String) -> Result<Value, String> {
    if std::env::var_os("STUDYFLOW_WORKSPACE").is_some() {
        return Err("当前工作区由环境变量固定；请显式修改环境后重启".into());
    }
    let target = std::path::PathBuf::from(path);
    if !target.is_absolute()
        || !target.is_dir()
        || !target.join(".studyflow").join("studyflow.db").is_file()
    {
        return Err("选择已验证恢复的新工作区目录".into());
    }
    let state = app.state::<EngineState>();
    let mut guard = state
        .client
        .try_lock()
        .map_err(|_| "Engine正在请求，未切换")?;
    let config = app.path().app_config_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&config).map_err(|e| e.to_string())?;
    let temporary = config.join("workspace-path.next");
    std::fs::write(&temporary, target.to_string_lossy().as_bytes()).map_err(|e| e.to_string())?;
    let destination = config.join("workspace-path.txt");
    if destination.exists() {
        std::fs::copy(&destination, config.join("workspace-path.previous"))
            .map_err(|e| e.to_string())?;
    }
    replace_config(&temporary, &destination)?;
    *guard = None;
    Ok(json!({"ok":true,"workspace":target,"restart_required":false}))
}

fn replace_config(source: &std::path::Path, target: &std::path::Path) -> Result<(), String> {
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "kernel32")]
        extern "system" {
            fn MoveFileExW(source: *const u16, target: *const u16, flags: u32) -> i32;
        }
        let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
        let target: Vec<u16> = target.as_os_str().encode_wide().chain(Some(0)).collect();
        if unsafe { MoveFileExW(source.as_ptr(), target.as_ptr(), 1 | 8) } == 0 {
            return Err(std::io::Error::last_os_error().to_string());
        }
        Ok(())
    }
    #[cfg(not(windows))]
    {
        std::fs::rename(source, target).map_err(|e| e.to_string())
    }
}
