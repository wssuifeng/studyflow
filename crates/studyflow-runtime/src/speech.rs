use std::sync::LazyLock;

use serde_json::Value;
use studyflow_core::speech_generation::profiles;

use crate::{planning::workspace, registry::Params, ApiError};

static SCHEMAS: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("speech-schema.json")).expect("valid speech contracts")
});

pub(crate) fn schema(method: &str) -> Option<Value> {
    SCHEMAS.get(method).cloned()
}

pub(crate) fn get_profile(params: &Params) -> Result<Value, ApiError> {
    let id = params
        .get("profile_id")
        .map_or(Some("default"), Value::as_str)
        .ok_or_else(|| ApiError::invalid_argument("profile_id 必须是 default 或 UUID。"))?;
    Ok(profiles::get(&workspace()?.settings().workspace, id)?)
}

pub(crate) fn list_profiles(_: &Params) -> Result<Value, ApiError> {
    Ok(profiles::list(&workspace()?.settings().workspace)?)
}

pub(crate) fn save_profile(params: &Params) -> Result<Value, ApiError> {
    Ok(profiles::save(
        &workspace()?.settings().workspace,
        &Value::Object(params.clone()),
    )?)
}

pub(crate) fn start_job(params: &Params) -> Result<Value, ApiError> {
    Ok(studyflow_core::speech_generation::jobs::start(
        &workspace()?.settings().workspace,
        &Value::Object(params.clone()),
        launch_worker,
    )?)
}

pub(crate) fn get_job(params: &Params) -> Result<Value, ApiError> {
    let id = params
        .get("job_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ApiError::invalid_argument("job_id 必须是 UUID。"))?;
    Ok(studyflow_core::speech_generation::jobs::get(
        &workspace()?.settings().workspace,
        id,
    )?)
}

fn launch_worker(
    id: &str,
    launch_id: &str,
) -> Result<(), studyflow_core::infrastructure::StorageError> {
    use std::{
        io::{BufRead, BufReader, Read},
        process::{Command, Stdio},
        sync::mpsc,
        thread,
        time::Duration,
    };
    use studyflow_core::infrastructure::StorageError;

    let failed = || StorageError::new("TTS_WORKER_START_FAILED");
    let self_path = std::env::current_exe().map_err(|_| failed())?;
    let engine_name = if cfg!(windows) {
        "studyflow-engine.exe"
    } else {
        "studyflow-engine"
    };
    let engine = self_path.with_file_name(engine_name);
    let mut command = Command::new(engine);
    command
        .args(["--speech-worker", id, launch_id])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        block_parent_pipe_inheritance()?;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    let mut child = command.spawn().map_err(|_| failed())?;
    let output = child.stdout.take().ok_or_else(failed)?;
    let (sender, receiver) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let mut line = String::new();
        if BufReader::new(output.take(128))
            .read_line(&mut line)
            .is_ok()
        {
            let _ = sender.send(line);
        }
    });
    let handshake = receiver.recv_timeout(Duration::from_secs(8)).ok();
    if handshake
        .as_deref()
        .is_some_and(|line| line.trim_end() == "ready")
    {
        thread::spawn(move || {
            let _ = child.wait();
        });
        return Ok(());
    }
    let _ = child.kill();
    let _ = child.wait();
    Err(match handshake.as_deref().map(str::trim_end) {
        Some("SPEECH_BUSY") => StorageError::new("SPEECH_BUSY"),
        Some("VERSION_CONFLICT") => StorageError::new("VERSION_CONFLICT"),
        Some("KEY_STORE_UNAVAILABLE") => StorageError::new("KEY_STORE_UNAVAILABLE"),
        Some("KEY_REQUIRED") => StorageError::new("KEY_REQUIRED"),
        Some("WORKSPACE_MAINTENANCE_BUSY") => StorageError::new("WORKSPACE_MAINTENANCE_BUSY"),
        _ => failed(),
    })
}

#[cfg(windows)]
fn block_parent_pipe_inheritance() -> Result<(), studyflow_core::infrastructure::StorageError> {
    use std::{io, os::windows::io::AsRawHandle};
    use windows_sys::Win32::{
        Foundation::{SetHandleInformation, HANDLE_FLAG_INHERIT},
        Storage::FileSystem::{GetFileType, FILE_TYPE_PIPE},
    };
    // CreateProcess can inherit the CLI's upstream pipes in addition to the
    // child's explicitly redirected standard streams. The consumer must see EOF
    // when the CLI exits, including while the worker is waiting for a provider.
    for handle in [
        io::stdin().as_raw_handle(),
        io::stdout().as_raw_handle(),
        io::stderr().as_raw_handle(),
    ] {
        if unsafe {
            GetFileType(handle) == FILE_TYPE_PIPE
                && SetHandleInformation(handle, HANDLE_FLAG_INHERIT, 0) == 0
        } {
            return Err(studyflow_core::infrastructure::StorageError::new(
                "TTS_WORKER_START_FAILED",
            ));
        }
    }
    Ok(())
}

pub fn run_worker(id: &str, launch_id: &str) -> std::process::ExitCode {
    use std::io::{self, Write};
    use std::process::ExitCode;
    use studyflow_core::infrastructure::config::Settings;

    let result = Settings::from_env().and_then(|settings| {
        studyflow_core::speech_generation::jobs::run_worker(
            &settings.workspace,
            id,
            launch_id,
            || {
                let mut output = io::stdout().lock();
                let _ = writeln!(output, "ready").and_then(|_| output.flush());
            },
        )
    });
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            let _ = writeln!(io::stdout().lock(), "{}", error.code);
            ExitCode::FAILURE
        }
    }
}

pub(crate) fn preview_job(params: &Params) -> Result<Value, ApiError> {
    let job = params
        .get("job_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ApiError::invalid_argument("job_id 必须是 UUID。"))?;
    Ok(studyflow_core::speech_generation::adoption::preview(
        &workspace()?.settings().workspace,
        job,
    )?)
}

pub(crate) fn adopt_asset(params: &Params) -> Result<Value, ApiError> {
    let job = params
        .get("job_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ApiError::invalid_argument("job_id 必须是 UUID。"))?;
    Ok(studyflow_core::speech_generation::adoption::adopt(
        &workspace()?.settings().workspace,
        job,
    )?)
}
