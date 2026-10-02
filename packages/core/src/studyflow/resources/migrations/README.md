# StudyFlow Alembic migrations

0001—0005 是已存在的 schema 演进链，不再生成第二个 initial schema。历史版本编号和逻辑保持不变；当前对应17张表。

从仓库根安装 `packages/core` 的 editable 环境后，可对明确选择的工作区执行：

```powershell
$python = Join-Path $PWD 'packages/core/.venv/Scripts/python.exe'
$env:STUDYFLOW_WORKSPACE = '<explicit-workspace>'
& $python -m studyflow db-upgrade --format json
```

`db-upgrade` 对未知或不完整结构安全失败；已有SQLite升级前创建一致性备份。不要使用`init`替代迁移、覆盖数据库或修复真实学习数据。

迁移源位于本目录；程序化适配器从只读包资源定位配置，并传入明确的数据库URL。Wheel与冻结Engine都包含此目录。开发者新增版本需要同时更新模型、迁移回归与工程文档，不能修改0001—0005的既有逻辑。
