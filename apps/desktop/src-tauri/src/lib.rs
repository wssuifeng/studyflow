mod commands;
mod engine;
mod tools;
mod workspace;

use engine::{ensure_engine, EngineState};
use tauri::Manager;

pub fn run() {
    tauri::Builder::default()
        .manage(EngineState::default())
        .manage(tools::ToolWindows::default())
        .setup(|app| {
            let state = app.state::<EngineState>();
            ensure_engine(&state, &app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::engine_call,
            commands::engine_status,
            commands::switch_workspace,
            tools::open_tool_window,
            tools::tool_windows,
            tools::set_tool_context,
            tools::close_tool_windows
        ])
        .on_window_event(|window, event| {
            if window.label() == "main" && matches!(event, tauri::WindowEvent::Destroyed) {
                for tool in ["notes", "exercises", "outline"] {
                    if let Some(child) = window
                        .app_handle()
                        .get_webview_window(&format!("tool-{tool}"))
                    {
                        let _ = child.destroy();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("启动 StudyFlow Desktop 失败");
}
