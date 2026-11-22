mod commands;
mod diagnostics;
mod engine;
mod tools;
mod workspace;

use engine::EngineState;
use tauri::Manager;

pub fn run() {
    tauri::Builder::default()
        .manage(EngineState::default())
        .manage(tools::ToolWindows::default())
        .invoke_handler(tauri::generate_handler![
            commands::engine_call,
            commands::engine_status,
            diagnostics::record_ui_diagnostic,
            commands::switch_workspace,
            tools::open_tool_window,
            tools::tool_windows,
            tools::set_tool_context,
            tools::close_tool_windows
        ])
        .on_window_event(|window, event| {
            if window.label() == "main" && matches!(event, tauri::WindowEvent::Destroyed) {
                let engine = window.state::<EngineState>();
                if let Ok(mut client) = engine.client.try_lock() {
                    client.take();
                }
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
