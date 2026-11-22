mod notebook;
mod notebook_cli;
use std::{
    borrow::Cow,
    io::{self, BufRead, Write},
};

use serde_json::{json, Value};
use studyflow_core::{courses::packages::PackageError, infrastructure::StorageError};

pub mod archive_cli;
mod author;
pub mod authoring_cli;
pub mod cli;
mod course;
mod english;
mod learning;
pub mod learning_cli;
mod maintenance_cli;
mod planning;
pub mod planning_cli;
mod practice;
pub mod registry;
mod review;
pub mod review_cli;
mod speech;
pub use speech::run_worker as run_speech_worker;

use registry::{Method, Params};

const MAX_FRAME: usize = 16 * 1024 * 1024;

#[derive(Debug)]
pub struct ApiError {
    pub code: &'static str,
    pub message: String,
    pub next_action: Cow<'static, str>,
}

impl ApiError {
    pub fn invalid_argument(message: impl Into<String>) -> Self {
        Self {
            code: "INVALID_ARGUMENT",
            message: message.into(),
            next_action: "读取 system.schema 后核对请求参数。".into(),
        }
    }

    pub fn missing_method(name: &str) -> Self {
        Self {
            code: "METHOD_NOT_FOUND",
            message: format!("找不到方法 {name}。"),
            next_action: "先读取 system.capabilities。".into(),
        }
    }

    pub fn payload(&self) -> Value {
        json!({"code":self.code,"error_code":self.code,"message":self.message,"next_action":self.next_action})
    }
}

impl From<PackageError> for ApiError {
    fn from(error: PackageError) -> Self {
        Self {
            code: PackageError::CODE,
            message: error.to_string(),
            next_action: "按 system.schema 与课程包契约修正课程包后重新校验；未写入课程。".into(),
        }
    }
}

impl From<StorageError> for ApiError {
    fn from(error: StorageError) -> Self {
        let (message, next_action) = match error.code {
            "ACTIVE_WORKSPACE_RESTORE_FORBIDDEN" => (
                "当前工作区正在使用。",
                "选择新的恢复目录，恢复后再切换工作区。",
            ),
            "DATABASE_NOT_FOUND" | "WORKSPACE_NOT_INITIALIZED" => {
                ("找不到已有的工作区数据库。", "核对工作区目录与数据库配置。")
            }
            "WORKSPACE_MAINTENANCE_BUSY" => (
                "工作区正在使用或维护。",
                "关闭使用目标工作区的 StudyFlow 进程后重试。",
            ),
            "WORKSPACE_DISK_FULL" => ("恢复空间不足。", "选择有足够空间的磁盘后重试。"),
            "UNSUPPORTED_DATABASE" => (
                "数据库配置需要有效的 SQLite 文件路径。",
                "检查 STUDYFLOW_DATABASE_URL 或 STUDYFLOW_DATABASE_PATH。",
            ),
            "NEWER_SCHEMA_UNSUPPORTED" => {
                ("工作区由更新版本创建。", "使用与工作区匹配的应用版本。")
            }
            "INVALID_TTS_ENDPOINT" => (
                "语音服务地址无效。",
                "输入完整 HTTPS 接口地址。HTTP 仅支持本机回环地址。",
            ),
            "KEY_STORE_UNAVAILABLE" => (
                "无法读取或保存当前用户的语音凭据。",
                "检查 Windows 用户环境，必要时在设置页重新填写密钥。",
            ),
            "SPEECH_BUSY" => (
                "另一语音操作正在进行。",
                "等待操作结束后重新读取配置或任务。",
            ),
            "KEY_REQUIRED" => (
                "此语音配置还没有可用凭据。",
                "在语音设置中保存该提供方的密钥。",
            ),
            "TTS_AUTH" => ("语音提供方拒绝鉴权。", "核对提供方、接口地址和密钥。"),
            "TTS_RATE_LIMIT" => ("语音提供方限制了请求。", "核对用量与频率后显式重试。"),
            "TTS_PROVIDER_ERROR" => ("语音提供方返回错误。", "核对请求地址、模型和音色。"),
            "TTS_UNCONFIRMED" => (
                "无法确认提供方是否已生成音频。",
                "检查提供方记录后再决定是否重试。",
            ),
            "INVALID_AUDIO" => ("语音数据超限或无法解码。", "核对音频格式，或缩短生成文本。"),
            "VERSION_CONFLICT" => (
                "当前版本已变化。",
                "重新读取课程或草稿，保留本机输入后重试。",
            ),
            "NOTEBOOK_FORMAT_UPGRADE_REQUIRED" => (
                "此笔记已升级为结构化格式。",
                "使用 plan.notebook.read 和 plan.notebook.apply 按记录 ID 操作。",
            ),
            "NOTEBOOK_FORMAT_UNSUPPORTED" => (
                "当前版本无法读取此笔记格式。",
                "使用支持此格式的 StudyFlow 读取或导出。",
            ),
            "NOTEBOOK_SOURCE_IMMUTABLE" => (
                "已保存的出处不可修改。",
                "保留现有出处，使用新的出处 ID 注册其他摘录。",
            ),
            "STUDY_CLOSED" => ("该轮次已明确结束，历史笔记只读。", "可继续编辑计划笔记。"),
            "STUDY_ROUND_SUPERSEDED" => {
                ("该学习轮次已经收口。", "保留草稿，重新打开课程以继续学习。")
            }
            "COURSE_STUDY_IN_PROGRESS" => {
                ("当前学习尚未收口，不能切换材料版本。", "请先完成本轮课程。")
            }
            "COURSE_VERSION_UNCHANGED" => {
                ("学习材料没有更新，无需开始新版。", "继续回看当前课程即可。")
            }
            "INCOMPLETE_COURSE_ANSWERS" => ("本课还有题目待作答。", "补齐答案后统一提交。"),
            "INCOMPLETE_PRACTICE_GROUP" => {
                ("本课还有未确认的专项题组。", "先打开专项题组并确认答案。")
            }
            "READING_INCOMPLETE" => (
                "课程阅读尚未完成。",
                "确认所有知识点。有练习的课程应整课提交。",
            ),
            "ENGLISH_ENDPOINT_REQUIRED" => {
                ("当前课程使用英语专项作答。", "打开英语专项训练继续作答。")
            }
            "PRACTICE_ENDPOINT_REQUIRED" => ("当前题目使用专项题组作答。", "打开该题组继续作答。"),
            "RETEST_TASK_REQUIRED" => (
                "当前答案没有可提交的复测题。",
                "等待 Agent 发布复测题后继续。",
            ),
            "IDEMPOTENCY_KEY_CONFLICT" => (
                "幂等键已用于其他请求。",
                "核对原请求，仅对相同载荷重试原键。",
            ),
            code if code.starts_with("BACKUP_") => (
                "无法使用此工作区归档。",
                "核对归档路径与完整性，使用已验证的备份重试。",
            ),
            _ => ("工作区操作未完成。", "核对工作区状态，保留错误代码。"),
        };
        Self {
            code: error.code,
            message: message.into(),
            next_action: next_action.into(),
        }
    }
}

pub fn serve_managed_engine(
    input: impl BufRead,
    output: impl Write,
    expected_version: &str,
    expected_protocol: &str,
) -> io::Result<()> {
    let prepare = || {
        use studyflow_core::{infrastructure::config::Settings, workspace::Workspace, APP_VERSION};
        if expected_version != APP_VERSION || expected_protocol != registry::PROTOCOL_VERSION {
            return Err(ApiError {
                code: "ENGINE_VERSION_MISMATCH",
                message: "桌面程序与 Engine 版本不匹配。".into(),
                next_action: "使用同一构建的桌面程序和 Engine。".into(),
            });
        }
        Workspace::new(Settings::from_env()?).ensure_ready()?;
        Ok(())
    };
    serve(input, output, Some(prepare()))
}

pub fn serve_engine(input: impl BufRead, output: impl Write) -> io::Result<()> {
    serve(input, output, None)
}

fn serve(
    mut input: impl BufRead,
    mut output: impl Write,
    mut startup: Option<Result<(), ApiError>>,
) -> io::Result<()> {
    let mut frame = Vec::new();
    while let Some(fits) = read_frame(&mut input, &mut frame)? {
        let reply = if !fits {
            invalid_request(Value::Null, "JSONL 请求超过 16 MiB。")
        } else if frame.iter().all(u8::is_ascii_whitespace) {
            continue;
        } else {
            match serde_json::from_slice(&frame) {
                Ok(request) => {
                    if let Some(Err(error)) = startup.take() {
                        let request: Value = request;
                        let reply =
                            json!({"id":request.get("id"),"ok":false,"error":error.payload()});
                        serde_json::to_writer(&mut output, &reply)?;
                        output.write_all(b"\n")?;
                        return output.flush();
                    }
                    dispatch(request)
                }
                Err(_) => invalid_request(Value::Null, "请求必须是有效的 UTF-8 JSON。"),
            }
        };
        serde_json::to_writer(&mut output, &reply)?;
        output.write_all(b"\n")?;
        output.flush()?;
    }
    Ok(())
}

fn read_frame(input: &mut impl BufRead, buffer: &mut Vec<u8>) -> io::Result<Option<bool>> {
    buffer.clear();
    let mut exceeded = false;
    loop {
        let chunk = input.fill_buf()?;
        if chunk.is_empty() {
            return Ok((exceeded || !buffer.is_empty()).then_some(!exceeded));
        }
        let newline = chunk.iter().position(|&byte| byte == b'\n');
        let len = newline.unwrap_or(chunk.len());
        if !exceeded && buffer.len() + len <= MAX_FRAME {
            buffer.extend_from_slice(&chunk[..len]);
        } else {
            exceeded = true;
            buffer.clear();
        }
        input.consume(len + usize::from(newline.is_some()));
        if newline.is_some() {
            return Ok(Some(!exceeded));
        }
    }
}

fn dispatch(request: Value) -> Value {
    let id = request.get("id").cloned().unwrap_or(Value::Null);
    if !request.is_object() {
        return invalid_request(id, "请求必须是 JSON 对象。");
    }
    let Some(name) = request
        .get("method")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|name| !name.is_empty())
    else {
        return invalid_request(id, "请求缺少 method。");
    };
    let empty = Params::new();
    let params = match request.get("params") {
        None => &empty,
        Some(Value::Object(params)) => params,
        _ => return invalid_request(id, "params 必须是 JSON 对象。"),
    };
    let result = Method::from_name(name)
        .ok_or_else(|| ApiError::missing_method(name))
        .and_then(|method| {
            method.validate(params)?;
            method.execute(params)
        });
    match result {
        Ok(data) => json!({"id": id, "ok": true, "data": data}),
        Err(error) => json!({"id":id,"ok":false,"error":error.payload()}),
    }
}

fn invalid_request(id: Value, message: &str) -> Value {
    let error = ApiError {
        code: "INVALID_REQUEST",
        message: message.into(),
        next_action: "使用 {id, method, params} 对象。".into(),
    };
    json!({"id":id,"ok":false,"error":error.payload()})
}

pub mod cli_help;
pub mod completion;
