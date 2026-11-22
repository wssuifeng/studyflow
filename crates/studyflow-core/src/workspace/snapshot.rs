use std::{fs, io::Write, path::Path};

use serde_json::{json, Value};
use time::Date;

use crate::{
    application::write_contract::atomic_write,
    infrastructure::{events, file_paths::workspace_path, StorageError},
    planning,
    workspace::Workspace,
};

pub fn generate(workspace: &Workspace, date: Date, scope: &str) -> Result<Value, StorageError> {
    let mut active = workspace.open()?;
    let day = planning::date_text(date);
    let relative = format!("content/snapshots/{day}-snapshot.md");
    let path = workspace_path(&workspace.settings().workspace, Path::new(&relative))?;
    atomic_write(&mut active.connection, |db| {
        let dashboard = planning::dashboard(db, date, None, None)?;
        let pointer = dashboard["primary_task"].as_str();
        let pending: u64 = dashboard["queue_counts"]
            .as_object()
            .unwrap()
            .values()
            .filter_map(Value::as_u64)
            .sum();
        let task = pointer.unwrap_or("暂无");
        let summary = format!("# StudyFlow 上下文快照 · {day}\n\n- 当前范围：{scope}\n- 主任务：{task}\n- 待批改：{pending}\n\n## 下一动作\n打开今日工作台，继续主任务。");
        let id = uuid::Uuid::new_v4().to_string();
        db.execute("INSERT INTO context_snapshots(id,snapshot_date,scope,relative_path,current_pointer,summary) VALUES(?,?,?,?,?,?)",
            rusqlite::params![id, day, scope, relative, pointer.unwrap_or_default(), summary])?;
        events::record(
            db,
            "AGENT_CLI",
            "snapshot",
            &id,
            "GENERATE",
            "生成上下文快照",
        )?;
        let parent = path.parent().expect("snapshot path has a parent");
        fs::create_dir_all(parent)?;
        let stage = parent.join(format!(".studyflow-snapshot-{id}.tmp"));
        let result = (|| -> Result<(), StorageError> {
            let mut file = fs::File::create_new(&stage)?;
            writeln!(file, "{summary}")?;
            file.sync_all()?;
            drop(file);
            fs::rename(&stage, &path)?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&stage);
        }
        result?;
        Ok(json!({"snapshot_id":id,"path":relative}))
    })
}
