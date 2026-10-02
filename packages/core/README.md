# StudyFlow Core

本目录是可安装的 Python Core 发行包，不是学习数据工作区。

- `src/studyflow/modules/`：六个业务模块，模型、服务、必要DTO/查询辅助。
- `src/studyflow/application/`：AppService装配与聚合读取。
- `src/studyflow/interfaces/`：CLI、Engine、兼容Web。
- `src/studyflow/infrastructure/`：事务、持久化、资源和诊断。
- `src/studyflow/resources/`：只读迁移/兼容UI资源/合成示例。
- `tests/`：合成业务回归、结构和发布边界测试。

从仓库根执行 `python -m pip install -e './packages/core[dev]'`，再使用 `python -m studyflow`。CLI/Engine必须显式确认数据工作区；不要把site-packages或冻结包解压目录作为学习数据。

工程入口见[仓库README](../../README.md)，构建说明见[构建与开发](../../docs/40_开发实施/构建与开发.md)。
