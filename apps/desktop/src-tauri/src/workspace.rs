use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::{AppHandle, Manager};

pub(super) fn resolve_workspace(
    app: &AppHandle,
    source_workspace: Option<&Path>,
) -> Result<PathBuf, String> {
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

pub(super) fn build_engine_command(
    app: &AppHandle,
    source_workspace: Option<&Path>,
) -> Result<Command, String> {
    let packaged_candidates = [
        env::var_os("STUDYFLOW_ENGINE_PATH").map(PathBuf::from),
        app.path()
            .resource_dir()
            .ok()
            .map(|root| root.join("binaries").join("studyflow-engine.exe")),
        app.path()
            .resource_dir()
            .ok()
            .map(|root| root.join("studyflow-engine.exe")),
        std::env::current_exe()
            .ok()
            .and_then(|path| path.parent().map(|root| root.join("studyflow-engine.exe"))),
    ];
    if let Some(engine_path) = packaged_candidates
        .into_iter()
        .flatten()
        .find(|path| path.is_file())
    {
        return Ok(Command::new(engine_path));
    }

    if !cfg!(debug_assertions) {
        return Err("找不到打包的 StudyFlow Engine；正式运行不会回退到系统 Python。请重新构建包含 binaries/studyflow-engine.exe 的桌面包。".to_string());
    }

    let source_workspace =
        source_workspace.ok_or_else(|| "开发模式找不到 StudyFlow 源码工作区".to_string())?;
    let python = env::var_os("STUDYFLOW_PYTHON")
        .map(PathBuf::from)
        .filter(|path| path.exists())
        .unwrap_or_else(|| {
            let candidate = source_workspace
                .join(".venv")
                .join("Scripts")
                .join("python.exe");
            if candidate.exists() {
                candidate
            } else {
                PathBuf::from("python")
            }
        });
    let mut command = Command::new(python);
    command.arg("-m").arg("studyflow.engine");
    Ok(command)
}

fn is_project_root(path: &Path) -> bool {
    path.join("packages/core/pyproject.toml").is_file()
        && path.join("apps/desktop/package.json").is_file()
}

pub(super) fn discover_project_root() -> Result<PathBuf, String> {
    if let Some(value) = env::var_os("STUDYFLOW_PROJECT_ROOT") {
        let root = PathBuf::from(value);
        if is_project_root(&root) {
            return Ok(root);
        }
    }
    let current = env::current_dir().map_err(|error| format!("无法获取当前目录：{error}"))?;
    current
        .ancestors()
        .find(|path| is_project_root(path))
        .map(|path| path.canonicalize().unwrap_or_else(|_| path.to_path_buf()))
        .ok_or_else(|| {
            "找不到包含 packages/core 和 apps/desktop 的项目工作区，请设置 STUDYFLOW_PROJECT_ROOT"
                .to_string()
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn development_layout_is_discoverable_from_the_shell() {
        let shell = Path::new(env!("CARGO_MANIFEST_DIR"));
        assert!(shell.ancestors().any(is_project_root));
    }
}
