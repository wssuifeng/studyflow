# 工作区配置与Agent接入（app1.3.0 / Skill1.6.0）

直接上游：[桌面架构](../30_系统设计/系统架构设计.md)、[CLI契约](../30_系统设计/接口与CLI契约.md)。这份说明描述已经实现的行为，不宣称新增目录选择功能或用户体验验收。

## 1. 三种目录不能混用

- **安装目录**：桌面程序与Engine，安装到哪里不代表学习数据也在那里。
- **数据工作区**：课程Markdown、应用管理的SQLite、学习记录、批改历史与备份。
- **源码仓库**：软件、工程文档、Skill源；公开仓库不保存真实学习材料与答案。

Release默认使用`$env:APPDATA\local.studyflow.desktop`。应用侧边栏“工作区”展示`doctor.workspace.root`。当前只有路径/连接展示，**没有图形化工作区选择按钮**；默认使用无需手动配置数据库或启动后端。

## 2. 外部Agent接入同一工作区

安装包不附独立`studyflow.exe`，不写PATH。现有源码环境提供CLI，外部Agent必须显式选中数据工作区：

```powershell
$python = Join-Path '<source-checkout>' 'packages/core/.venv/Scripts/python.exe'
$env:STUDYFLOW_WORKSPACE = Join-Path $env:APPDATA 'local.studyflow.desktop'
& $python -B -X utf8 -m studyflow version --format json
& $python -B -X utf8 -m studyflow capabilities --format json
& $python -B -X utf8 -m studyflow doctor --format json
```

核对返回根目录与应用一致；写操作前还要核对`workspace.writable=true`。`healthy=true`仅表示当前诊断中的存在/数据库可达，并不能保证写入权限。若返回只读数据库错误，停止写入，不改ACL、不绕过Agent沙箱、不静默改工作区。进程级环境设置不会永久修改系统，也不会切换已经启动的桌面进程。不得通过SQL写库、覆盖答案或把导入视为已学习。CLI已存在源码依赖时不需要为安装用户重新安装Python。

## 3. 需要自定义目录时

本轮没有迁移用户工作区。若之后确需更换：先退出应用并用CLI导出，再导入**新目录**、诊断通过，最后在同一PowerShell进程设置`STUDYFLOW_WORKSPACE`并启动桌面程序。不要空选目录后误以为旧数据已迁移；不要复制运行中的SQLite。

```powershell
# 导出时仍指向原数据工作区
& $python -B -X utf8 -m studyflow workspace export --output '<private-backup.zip>' --format json
$env:STUDYFLOW_WORKSPACE = 'D:\StudyFlowData'
& $python -B -X utf8 -m studyflow workspace import --file '<private-backup.zip>' --target $env:STUDYFLOW_WORKSPACE --format json
& $python -B -X utf8 -m studyflow doctor --format json
Start-Process -FilePath '<install-directory>\studyflow-desktop.exe'
```

最后一行是用户主动启动桌面界面，不是后台服务。此进程环境不会自动传给其他Agent或下次由桌面快捷方式启动的程序；持久快捷方式/图形化选择器尚未实现，不能说已经有。

## 4. 公共Skill

仓库源：`skills/studyflow-agent/`。公共安装位置通常为`~/.agents/skills/studyflow-agent/`，不是项目的`AGENTS.md`；不同Agent使用其支持的Skill目录。复制整个目录，包括`agents/`和`references/`。同步前备份，之后比较文件哈希并验证Skill格式。已开启会话可能仍缓存旧内容，后续任务需要重新读取新Skill。

2026-10-02用户授权同步，公共副本与仓库源1.6.0一致；源码main发布仍不表示私人的课程文件可以上传。
