mod commands;
mod engine;
mod workspace;

use engine::{ensure_engine, EngineState};
use tauri::Manager;

pub fn run() {
    tauri::Builder::default()
        .manage(EngineState::default())
        .setup(|app| {
            let state = app.state::<EngineState>();
            ensure_engine(&state, &app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::engine_call,
            commands::engine_status
        ])
        .run(tauri::generate_context!())
        .expect("启动 StudyFlow Desktop 失败");
}
