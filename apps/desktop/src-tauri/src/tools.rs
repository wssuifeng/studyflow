//! Native tool windows only. Learning and notebook rules remain in Python Core.
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, sync::Mutex};
use tauri::{
    AppHandle, Emitter, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent,
};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct ToolContext {
    course_id: String,
    study_id: String,
    plan_id: String,
    plan_title: String,
    lesson_id: Option<String>,
}
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
struct Geometry {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}
#[derive(Default)]
pub(super) struct ToolWindows {
    contexts: Mutex<HashMap<String, ToolContext>>,
    geometry: Mutex<HashMap<String, Geometry>>,
}
fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.chars().all(|c| c.is_ascii_alphanumeric() || c == '-')
}
fn valid_tool(tool: &str) -> bool {
    matches!(tool, "notes" | "exercises" | "outline")
}
fn validate(tool: &str, context: &ToolContext) -> Result<(), String> {
    if !valid_tool(tool)
        || !valid_id(&context.course_id)
        || !valid_id(&context.study_id)
        || !valid_id(&context.plan_id)
        || context.lesson_id.as_ref().is_some_and(|s| !valid_id(s))
        || context.plan_title.len() > 2000
    {
        return Err("工具窗口上下文无效".into());
    }
    Ok(())
}
fn main_only(window: &WebviewWindow) -> Result<(), String> {
    if window.label() != "main" {
        Err("只有主窗口可以打开或切换工具窗口".into())
    } else {
        Ok(())
    }
}
// Physical monitor coordinates keep restored titlebars reachable with negative/mixed-DPI displays.
fn visible_geometry(g: Geometry, monitors: &[(f64, f64, f64, f64, f64)]) -> Geometry {
    let Some(&(x, y, w, h, scale)) = monitors
        .iter()
        .find(|&&(x, y, w, h, _)| g.x >= x && g.x < x + w && g.y >= y && g.y < y + h)
        .or_else(|| monitors.first())
    else {
        return g;
    };
    let width = g.width.clamp(340.0, (w / scale).max(340.0));
    let height = g.height.clamp(320.0, (h / scale).max(320.0));
    Geometry {
        x: g.x.clamp(x, (x + w - width * scale).max(x)),
        y: g.y.clamp(y, (y + h - height * scale).max(y)),
        width,
        height,
    }
}
fn layout_path(app: &AppHandle) -> Option<std::path::PathBuf> {
    // Native smoke tests can isolate their layout alongside their synthetic workspace.
    let root = std::env::var_os("STUDYFLOW_WINDOW_STATE_DIR")
        .map(std::path::PathBuf::from)
        .or_else(|| app.path().app_config_dir().ok())?;
    Some(root.join("tool-window-layout.json"))
}
fn restore_layout(app: &AppHandle) {
    let state = app.state::<ToolWindows>();
    let Ok(mut geometry) = state.geometry.lock() else {
        return;
    };
    if !geometry.is_empty() {
        return;
    }
    if let Some(path) = layout_path(app) {
        if let Ok(bytes) = std::fs::read(path) {
            if let Ok(values) = serde_json::from_slice::<HashMap<String, Geometry>>(&bytes) {
                geometry.extend(values.into_iter().filter(|(key, g)| {
                    valid_tool(key) && [g.x, g.y, g.width, g.height].iter().all(|v| v.is_finite())
                }));
            }
        }
    }
}
fn persist_layout(app: &AppHandle) {
    let Some(path) = layout_path(app) else { return };
    let state = app.state::<ToolWindows>();
    let Ok(geometry) = state.geometry.lock() else {
        return;
    };
    if let (Some(parent), Ok(bytes)) = (path.parent(), serde_json::to_vec(&*geometry)) {
        if std::fs::create_dir_all(parent).is_ok() {
            let _ = std::fs::write(path, bytes);
        }
    }
}
#[tauri::command]
pub(super) fn tool_windows(app: AppHandle) -> Vec<serde_json::Value> {
    let state = app.state::<ToolWindows>();
    let Ok(contexts) = state.contexts.lock() else {
        return vec![];
    };
    contexts
        .iter()
        .map(|(tool, context)| serde_json::json!({"tool":tool,"context":context}))
        .collect()
}
#[tauri::command]
pub(super) fn set_tool_context(
    app: AppHandle,
    window: WebviewWindow,
    context: ToolContext,
) -> Result<(), String> {
    main_only(&window)?;
    let state = app.state::<ToolWindows>();
    let mut contexts = state.contexts.lock().map_err(|_| "工具上下文锁异常")?;
    for (tool, old) in contexts.iter_mut() {
        validate(tool, &context)?;
        *old = context.clone();
        app.emit_to(
            format!("tool-{tool}"),
            "studyflow-tool-context",
            serde_json::json!({"tool":tool,"context":context}),
        )
        .map_err(|e| e.to_string())?;
    }
    Ok(())
}
#[tauri::command]
pub(super) async fn open_tool_window(
    app: AppHandle,
    window: WebviewWindow,
    tool: String,
    context: ToolContext,
) -> Result<(), String> {
    main_only(&window)?;
    validate(&tool, &context)?;
    // Never build WebviewWindow inside a synchronous Windows command handler.
    tauri::async_runtime::spawn_blocking(move || {
        let label = format!("tool-{tool}");
        if let Some(existing) = app.get_webview_window(&label) {
            existing.unminimize().map_err(|e| e.to_string())?;
            existing.show().map_err(|e| e.to_string())?;
            return existing.set_focus().map_err(|e| e.to_string());
        }
        restore_layout(&app);
        let state = app.state::<ToolWindows>();
        let saved = state
            .geometry
            .lock()
            .ok()
            .and_then(|g| g.get(&tool).copied())
            .unwrap_or(Geometry {
                x: 140.0,
                y: 100.0,
                width: 540.0,
                height: 760.0,
            });
        let monitors = app
            .available_monitors()
            .map_err(|e| e.to_string())?
            .iter()
            .map(|m| {
                let p = m.position();
                let s = m.size();
                (
                    p.x as f64,
                    p.y as f64,
                    s.width as f64,
                    s.height as f64,
                    m.scale_factor(),
                )
            })
            .collect::<Vec<_>>();
        let restored = visible_geometry(saved, &monitors);
        let route = format!(
            "index.html#/tool/{tool}?study={}&course={}&plan={}",
            context.study_id, context.course_id, context.plan_id
        );
        state
            .contexts
            .lock()
            .map_err(|_| "工具上下文锁异常")?
            .insert(tool.clone(), context.clone());
        let built = WebviewWindowBuilder::new(&app, &label, WebviewUrl::App(route.into()))
            .title(format!(
                "StudyFlow · {}",
                match tool.as_str() {
                    "notes" => "计划笔记",
                    "exercises" => "课程练习",
                    _ => "知识大纲",
                }
            ))
            .inner_size(restored.width, restored.height)
            .min_inner_size(340.0, 320.0)
            .disable_drag_drop_handler()
            .decorations(false)
            .shadow(true)
            .resizable(true)
            .build();
        let child = match built {
            Ok(w) => w,
            Err(e) => {
                state
                    .contexts
                    .lock()
                    .map_err(|_| "工具上下文锁异常")?
                    .remove(&tool);
                return Err(format!("无法打开工具窗口：{e}"));
            }
        };
        let _ = child.set_position(tauri::PhysicalPosition::new(
            restored.x as i32,
            restored.y as i32,
        ));
        let app_events = app.clone();
        let label_events = label.clone();
        let tool_events = tool.clone();
        child.on_window_event(move |event| {
            if matches!(event, WindowEvent::Moved(_) | WindowEvent::Resized(_)) {
                if let Some(w) = app_events.get_webview_window(&label_events) {
                    if w.is_maximized().unwrap_or(false) {
                        return;
                    }
                    if let (Ok(p), Ok(s), Ok(scale)) =
                        (w.outer_position(), w.inner_size(), w.scale_factor())
                    {
                        if let Ok(mut values) = app_events.state::<ToolWindows>().geometry.lock() {
                            values.insert(
                                tool_events.clone(),
                                Geometry {
                                    x: p.x as f64,
                                    y: p.y as f64,
                                    width: s.width as f64 / scale,
                                    height: s.height as f64 / scale,
                                },
                            );
                        }
                    }
                }
            }
            if matches!(event, WindowEvent::Destroyed) {
                if let Ok(mut contexts) = app_events.state::<ToolWindows>().contexts.lock() {
                    contexts.remove(&tool_events);
                }
                persist_layout(&app_events);
                let _ = app_events.emit(
                    "studyflow-tool-closed",
                    serde_json::json!({"tool":tool_events}),
                );
            }
        });
        Ok(())
    })
    .await
    .map_err(|e| format!("工具窗口任务未完成：{e}"))?
}
#[tauri::command]
pub(super) fn close_tool_windows(app: AppHandle, window: WebviewWindow) -> Result<(), String> {
    main_only(&window)?;
    for tool in ["notes", "exercises", "outline"] {
        if let Some(child) = app.get_webview_window(&format!("tool-{tool}")) {
            child.destroy().map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tool_routes_are_local_only() {
        for id in ["", "../private", "https://x", "id?x=1", "id#x", "x/y"] {
            assert!(!valid_id(id))
        }
        assert!(valid_id("abc-123"));
        assert!(!valid_tool("terminal"));
    }
    #[test]
    fn removed_display_and_negative_coordinates_are_clamped() {
        let g = Geometry {
            x: 9999.0,
            y: 4000.0,
            width: 540.0,
            height: 760.0,
        };
        let result = visible_geometry(g, &[(-1920.0, 0.0, 1920.0, 1080.0, 1.0)]);
        assert!(result.x >= -1920.0 && result.x <= -540.0);
        assert!(result.y <= 320.0);
    }
    #[test]
    fn resized_monitor_keeps_entire_window_visible() {
        let result = visible_geometry(
            Geometry {
                x: 800.0,
                y: 600.0,
                width: 1600.0,
                height: 1200.0,
            },
            &[(0.0, 0.0, 1280.0, 720.0, 1.0)],
        );
        assert_eq!(result.width, 1280.0);
        assert_eq!(result.x, 0.0);
        assert_eq!(result.y, 0.0);
    }
}
