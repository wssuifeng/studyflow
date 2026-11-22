use super::{config::Settings, sqlite};
use rusqlite::OpenFlags;
use serde_json::{json, Value};
use std::{
    fs,
    io::{self, Write},
    path::Path,
};

pub fn inspect(settings: &Settings) -> Value {
    let root = &settings.workspace;
    let governance_root = if root.join("docs/00_总控.md").is_file() {
        root
    } else {
        root.parent().unwrap_or(root)
    };
    let governance_files = [
        "00-AI主控提示词.md",
        "02-当前阶段执行看板.md",
        "03-文档索引库.md",
        "04-AI上下文快照.md",
        "docs/00_总控.md",
    ];
    let present: serde_json::Map<_, _> = governance_files
        .into_iter()
        .map(|file| (file.to_owned(), json!(governance_root.join(file).is_file())))
        .collect();
    let access = directory_probe(root);
    let database = database(settings);
    let writable = access["writable"] == true && database["writable"] == true;
    let healthy = writable
        && matches!(
            database["status"].as_str(),
            Some("ready" | "not_initialized")
        );
    let next = if !writable {
        "当前进程不可写，请检查工作区和数据库的写入权限。"
    } else {
        database["next_action"]
            .as_str()
            .filter(|action| !action.is_empty())
            .unwrap_or("运行 studyflow today --format json 查看今日学习。")
    };
    json!({"workspace":{"root":root,"exists":root.is_dir(),"writable":access["writable"],"write_access":access,
        "governance_root":governance_root,"governance_ready":present.values().all(|value| value == true),"governance_files":present,"content_root":root.join("content")},
        "database":database,"healthy":healthy,"next_action":next})
}

fn directory_probe(path: &Path) -> Value {
    if !path.is_dir() {
        return json!({"writable":false,"reason":"directory_missing","phase":"create"});
    }
    let mut file = match tempfile::Builder::new()
        .prefix(".studyflow-write-check-")
        .tempfile_in(path)
    {
        Ok(file) => file,
        Err(error) => return access_error(&error, "create"),
    };
    if let Err(error) = file
        .write_all(b"StudyFlow write check\n")
        .and_then(|()| file.as_file().sync_all())
    {
        return access_error(&error, "write");
    }
    if let Err(error) = file.close() {
        return access_error(&error, "cleanup");
    }
    json!({"writable":true,"reason":"verified","phase":"complete"})
}

fn access_error(error: &io::Error, phase: &str) -> Value {
    let code = error.raw_os_error();
    let disk_full = if cfg!(windows) {
        matches!(code, Some(39 | 112))
    } else {
        code == Some(28)
    };
    let reason = if disk_full {
        "disk_full"
    } else if error.kind() == io::ErrorKind::PermissionDenied {
        "permission_denied"
    } else {
        "filesystem_error"
    };
    json!({"writable":false,"reason":reason,"phase":phase,"errno":if cfg!(windows) && reason == "permission_denied" {Some(13)} else {code},"winerror":if cfg!(windows) {code} else {None}})
}

fn database_directory_probe(path: &Path) -> Value {
    for ancestor in path.ancestors() {
        match fs::symlink_metadata(ancestor) {
            Ok(_) => return directory_probe(ancestor),
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => return access_error(&error, "inspect"),
        }
    }
    directory_probe(path)
}

fn database(settings: &Settings) -> Value {
    let path = &settings.database;
    let mut access = database_directory_probe(path.parent().expect("database parent"));
    if access["writable"] != true {
        access["scope"] = json!("database_directory");
    } else {
        access = if !path.exists() {
            json!({"writable":true,"reason":"not_initialized"})
        } else {
            match fs::OpenOptions::new().read(true).write(true).open(path) {
                Ok(_) => json!({"writable":true,"reason":"file_access_verified"}),
                Err(error) => access_error(&error, "open"),
            }
        };
        access["scope"] = json!("database");
    }
    let mut result = json!({"driver":"sqlite","managed_by_app":true,"url":format!("sqlite:///{}",path.to_string_lossy().replace('\\',"/")),"path":path,"required_tables":{},
        "reachable":false,"writable":access["writable"],"write_access":access});
    if !path.exists() {
        result["status"] = json!("not_initialized");
        result["next_action"] = json!("运行 studyflow init 初始化本地数据库。");
        return result;
    }
    let tables = sqlite::connect(path, OpenFlags::SQLITE_OPEN_READ_ONLY).and_then(|db| {
        let mut tables = serde_json::Map::new();
        for name in ["plan_lines", "courses", "exercises", "submissions"] {
            let found: bool = db.query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name=?)",
                [name],
                |row| row.get(0),
            )?;
            tables.insert(name.to_owned(), json!(found));
        }
        Ok(tables)
    });
    if let Ok(tables) = tables {
        let ready = tables.values().all(|present| present == true);
        result["required_tables"] = json!(tables);
        result["reachable"] = json!(true);
        result["status"] = json!(if ready { "ready" } else { "incomplete" });
        result["next_action"] = json!(if ready {
            ""
        } else {
            "运行 studyflow db-upgrade 或 studyflow init。"
        });
    } else {
        result["status"] = json!("unavailable");
        result["next_action"] = json!("检查数据库配置后运行 studyflow doctor --format json。");
    }
    result
}
