use super::engine::{ensure_engine, EngineClient, EngineState};
use serde_json::{json, Value};
use std::{
    sync::{Mutex, MutexGuard, TryLockError},
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Manager};

fn wait_for_client<T>(
    mutex: &Mutex<T>,
    timeout: Duration,
) -> Result<Option<MutexGuard<'_, T>>, String> {
    let started = Instant::now();
    loop {
        match mutex.try_lock() {
            Ok(guard) => return Ok(Some(guard)),
            Err(TryLockError::Poisoned(_)) => return Err("Engine 状态锁损坏。".into()),
            Err(TryLockError::WouldBlock) if started.elapsed() >= timeout => return Ok(None),
            Err(TryLockError::WouldBlock) => thread::sleep(Duration::from_millis(10)),
        }
    }
}

fn failed(request: &Value, code: &str, message: &str, action: &str) -> Value {
    json!({"id":request.get("id"),"ok":false,"error":{"code":code,"message":message,"next_action":action}})
}

#[tauri::command]
pub(super) async fn engine_call(app: AppHandle, request: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<EngineState>();
        let Some(mut guard) = wait_for_client(&state.client, Duration::from_secs(5))? else {
            return Ok(failed(
                &request,
                "ENGINE_BUSY",
                "Engine 正在处理请求，本请求尚未发送。",
                "保留输入和原幂等键，稍后重试。",
            ));
        };
        let client = match ensure_engine(&mut guard, &app) {
            Ok(client) => client,
            Err(message) => {
                let code = startup_error_code(&message);
                return Ok(failed(
                    &request,
                    code,
                    &message,
                    "本请求尚未发送。确认 Engine 与工作区状态后重试。",
                ));
            }
        };
        match client.call(&request) {
            Ok(response) => Ok(response),
            Err(message) => {
                // Disconnect the timed-out channel before another request can reuse it.
                *guard = None;
                let (code, action) = match message.split(':').next() {
                    Some("ENGINE_NOT_SENT") => {
                        ("ENGINE_NOT_SENT", "保留输入和原幂等键，重新连接后重试。")
                    }
                    Some("ENGINE_TIMEOUT") => {
                        ("ENGINE_TIMEOUT", "结果待确认。回读后按原幂等键重试。")
                    }
                    Some("INVALID_RESPONSE") => {
                        ("INVALID_RESPONSE", "结果待确认。回读后按原幂等键重试。")
                    }
                    _ => ("ENGINE_UNCONFIRMED", "结果待确认。回读后按原幂等键重试。"),
                };
                Ok(failed(&request, code, &message, action))
            }
        }
    })
    .await
    .map_err(|error| format!("Engine 请求任务未正常返回：{error}"))?
}

fn startup_error_code(message: &str) -> &str {
    message
        .split_once(':')
        .map(|(code, _)| code)
        .filter(|code| {
            !code.is_empty() && code.bytes().all(|ch| ch.is_ascii_uppercase() || ch == b'_')
        })
        .unwrap_or("ENGINE_STARTUP_FAILED")
}

#[tauri::command]
pub(super) async fn engine_status(app: AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<EngineState>();
        let Some(mut guard) = wait_for_client(&state.client, Duration::ZERO)? else {
            return Ok(json!({"running":true,"managed":true,"busy":true}));
        };
        match ensure_engine(&mut guard, &app) {
            Ok(_) => Ok(json!({"running":true,"managed":true,"busy":false})),
            Err(message) => Ok(json!({"running":false,"managed":true,"busy":false,"error":{"code":startup_error_code(&message),"message":message}})),
        }
    }).await.map_err(|error| format!("Engine 状态任务未正常返回：{error}"))?
}

#[tauri::command]
pub(super) async fn switch_workspace(app: AppHandle, path: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        if [
            "STUDYFLOW_WORKSPACE",
            "STUDYFLOW_DATABASE_PATH",
            "STUDYFLOW_DATABASE_URL",
        ]
        .into_iter()
        .any(|name| std::env::var_os(name).is_some())
        {
            return Err("当前工作区由环境变量固定；修改环境后重启。".into());
        }
        let target = std::path::PathBuf::from(path);
        if !target.is_absolute()
            || !target.is_dir()
            || !target.join(".studyflow/studyflow.db").is_file()
        {
            return Err("选择已验证恢复的新工作区目录。".into());
        }
        let state = app.state::<EngineState>();
        let Some(mut guard) = wait_for_client(&state.client, Duration::ZERO)? else {
            return Err("Engine 正在请求，未切换。".into());
        };
        let candidate = EngineClient::start_in(&app, &target)?;
        let config = app
            .path()
            .app_config_dir()
            .map_err(|error| error.to_string())?;
        std::fs::create_dir_all(&config).map_err(|error| error.to_string())?;
        let temporary = config.join("workspace-path.next");
        std::fs::write(&temporary, target.to_string_lossy().as_bytes())
            .map_err(|error| error.to_string())?;
        let destination = config.join("workspace-path.txt");
        if destination.exists() {
            std::fs::copy(&destination, config.join("workspace-path.previous"))
                .map_err(|error| error.to_string())?;
        }
        replace_config(&temporary, &destination)?;
        *guard = Some(candidate);
        Ok(json!({"ok":true,"workspace":target,"restart_required":false}))
    })
    .await
    .map_err(|error| format!("工作区切换未正常返回：{error}"))?
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn busy_transport_does_not_grant_access_to_the_waiting_request() {
        let client = Mutex::new(());
        let running = client.lock().unwrap();
        assert!(wait_for_client(&client, Duration::ZERO).unwrap().is_none());
        assert!(wait_for_client(&client, Duration::from_millis(20))
            .unwrap()
            .is_none());
        drop(running);
        assert!(wait_for_client(&client, Duration::ZERO).unwrap().is_some());
    }
}
