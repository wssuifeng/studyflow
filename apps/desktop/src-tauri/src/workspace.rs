use std::{
    env,
    path::{Path, PathBuf},
    process::Command,
};
use tauri::{AppHandle, Manager};

const ENGINE: &str = concat!("studyflow-engine", ".exe");

pub(super) fn resolve_workspace(app: &AppHandle) -> Result<PathBuf, String> {
    if let Some(value) = env::var_os("STUDYFLOW_WORKSPACE") {
        return env::current_dir()
            .map(|dir| dir.join(value))
            .map_err(|error| error.to_string());
    }
    if cfg!(debug_assertions) {
        return Ok(project_root()?.join("apps/desktop/test-results/dev-workspace"));
    }
    if let Ok(config) = app.path().app_config_dir() {
        if let Ok(text) = std::fs::read_to_string(config.join("workspace-path.txt")) {
            let path = PathBuf::from(text.trim());
            if path.is_absolute() && path.is_dir() {
                return Ok(path);
            }
        }
    }
    app.path()
        .app_data_dir()
        .map_err(|error| format!("无法确定 StudyFlow 应用数据目录：{error}"))
}

pub(super) fn build_engine_command(app: &AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        if let Some(explicit) = env::var_os("STUDYFLOW_ENGINE_PATH") {
            return engine_at(&PathBuf::from(explicit));
        }
        let project = project_root()?;
        let target = env::var_os("CARGO_TARGET_DIR").map_or_else(
            || project.join("apps/desktop/src-tauri/target"),
            |value| project.join(value),
        );
        let sibling = env::current_exe()
            .ok()
            .and_then(|exe| exe.parent().map(|parent| parent.join(ENGINE)));
        if let Some(path) = sibling.filter(|path| path.is_file()) {
            return engine_at(&path);
        }
        return engine_at(&target.join("debug").join(ENGINE));
    }
    let resources = app
        .path()
        .resource_dir()
        .map_err(|error| error.to_string())?;
    engine_at(&resources.join("binaries").join(ENGINE))
}

fn project_root() -> Result<&'static Path, String> {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .find(|root| root.join("crates/studyflow-runtime/Cargo.toml").is_file())
        .ok_or_else(|| "开发构建目录缺少 Cargo workspace。".to_owned())
}

fn engine_at(path: &Path) -> Result<Command, String> {
    if !path.is_absolute() || !path.is_file() {
        return Err(
            "找不到当前构建的 StudyFlow Engine。请检查桌面安装或运行 build-engine.ps1。".to_owned(),
        );
    }
    Ok(Command::new(path))
}
