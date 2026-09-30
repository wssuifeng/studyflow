# StudyFlow 迁移入口

这里保存 StudyFlow V1 的 Alembic 迁移入口。`0001_mvp_baseline` 是已有 MVP 表结构的基线，`0002_generic_metadata` 为通用计划/内容模型增加字段。当前本地启动仍调用 `create_all()` 并带有只增不删的兼容护栏；正式环境应显式执行迁移。

当数据模型在真实使用反馈后冻结时：

1. 备份目标数据库；设置 `STUDYFLOW_DATABASE_URL` 指向目标 MySQL；
2. 在 `studyflow_app` 根目录执行 `alembic revision --autogenerate -m "initial schema"`；
3. 人工审核生成的 `migrations/versions/*.py`，重点检查外键、索引、唯一约束和字段长度；
4. 在备份后的测试数据库执行 `alembic upgrade head`；
5. 再将 `init_db()` 从正式启动路径移除或限制为开发模式；本地旧 SQLite 可先执行 `python -m studyflow db-upgrade`，该命令只接受完整旧 schema，检测到未知/不完整结构会失败关闭。

在迁移脚本正式生成前，不要把当前 SQLite 文件当作交付数据库，也不要把真实数据库密码写入此目录。
