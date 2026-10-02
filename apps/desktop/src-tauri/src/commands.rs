use super::engine::{ensure_engine, EngineState};
use serde_json::{json, Value};
use tauri::{AppHandle, State};

#[tauri::command]
pub(super) fn engine_call(
    app: AppHandle,
    state: State<'_, EngineState>,
    request: Value,
) -> Result<Value, String> {
    ensure_engine(&state, &app)?;
    let mut guard = state
        .client
        .lock()
        .map_err(|_| "Engine 状态锁已损坏".to_string())?;
    let client = guard
        .as_mut()
        .ok_or_else(|| "Engine 尚未启动".to_string())?;
    client.call(&request)
}

#[tauri::command]
pub(super) fn engine_status(
    app: AppHandle,
    state: State<'_, EngineState>,
) -> Result<Value, String> {
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
}
