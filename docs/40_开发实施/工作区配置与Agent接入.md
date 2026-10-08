# 工作区配置与Agent接入（app1.7.0 / Skill2.0.0）

直接上游：[桌面架构](../30_系统设计/系统架构设计.md)、[CLI契约](../30_系统设计/接口与CLI契约.md)。这份说明描述已经实现的行为；工程验证与正式数据/用户体验验收分开。

## 1. 三种目录不能混用

- **安装目录**：桌面程序与Engine，安装到哪里不代表学习数据也在那里。
- **数据工作区**：课程Markdown、应用管理的SQLite、学习记录、批改历史与备份。
- **源码仓库**：软件、工程文档、Skill源；公开仓库不保存真实学习材料与答案。

Release首次默认使用`$env:APPDATA\local.studyflow.desktop`；以后使用显式环境工作区或已保存的工作区选择。应用“工作区与阅读设置”展示实际`doctor.workspace.root`及安装CLI路径，并提供备份、校验、恢复到新目录、切换到已恢复工作区。它不是空目录初始化器；默认使用无需手动配置数据库或启动后端。

## 2. 外部Agent接入同一工作区

1.7.0安装包附独立`binaries/studyflow.exe`及Skill资源，不写PATH。外部Agent先从应用复制接入说明，再显式选中同一个数据工作区：

```powershell
$cli = '<install-directory>\binaries\studyflow.exe'
$env:STUDYFLOW_WORKSPACE = '<confirmed-data-workspace>'
& $cli version --format json
& $cli capabilities --format json
& $cli doctor --format json
& $cli assignment queue --format json
# 可发现的新方法使用call，UTF-8请求JSON在明确工作区内
& $cli call --method system.schema --format json
```

核对返回根目录与应用一致；写操作前还要核对`workspace.writable=true`。`healthy=true`仅表示当前诊断中的存在/数据库可达，并不能保证写入权限。若返回只读数据库错误，停止写入，不改ACL、不绕过Agent沙箱、不静默改工作区。进程级环境设置不会永久修改系统，也不会切换已经启动的桌面进程。不得通过SQL写库、覆盖答案或把导入视为已学习。安装CLI与Engine复用同一冻结Core，不依赖源码/系统Python；旧安装或开发时仍可使用已配置源码CLI。

### 2.1 Windows源码解释器的遗留Low标签

2026-10-02定位到一种环境差异：源码venv的`python.exe`继承`Low Mandatory Level`，其进程完整性RID=4096；即使当前普通Shell已获正常本地访问授权，Python仍可能不能写正常AppData。对同一工作区，显式选用该venv对应的正常安装版、主次版本匹配的Python，加载同一CLI源码/依赖后，进程RID=8192，`workspace.writable=true`且受支持CLI写入/回读成功。没有提权、改ACL、变更数据库或工作区。

这里只是已获授权情况下的运行时选择，不是绕过活动沙箱。若当前Agent授权仍排除目标目录，必须停止。细化检查与命令见[Skill运行时诊断](../../skills/studyflow-agent/references/windows-cli-runtime.md)。外部Agent负责执行CLI，不因可修正的解释器选择问题将日常导入转交学习者。

**1.4.0诊断状态**：`doctor`现执行实际写入、flush、fsync探针，并将`workspace.writable`纳入可写结论；Core/Engine对只读、锁定、约束和磁盘满分别返回稳定安全错误码。旧app1.3.0的`INTERNAL_ERROR`记录仅作为历史证据保留，不代表当前源码行为。

## 3. 恢复与切换

优先在桌面“工作区与阅读设置”操作：导出一致性备份 → 验证备份 → 确认新目录 → 恢复 → 显式切换。恢复使用跨进程维护租约，正在运行的工作区拒绝覆盖；切换先协调工具窗口保存，失败保留原窗口与输入。Windows工作区配置原子替换，后续快捷方式启动沿用已保存选择。

进程级`STUDYFLOW_WORKSPACE`优先于持久选择；环境变量固定启动时UI不会静默改写它，须显式调整环境并重启。恢复新目录不删除旧目录，跨机器时用完整备份，不复制运行中的SQLite。

CLI示例（不自动改变桌面选择）：

```powershell
& $cli workspace export --output '<private-backup.zip>' --format json
& $cli workspace import --file '<private-backup.zip>' --target '<new-data-workspace>' --format json
# 将进程环境指向新目录后，再运行doctor核对；不会切换已启动的旧进程
$env:STUDYFLOW_WORKSPACE = '<new-data-workspace>'
& $cli doctor --format json
```

## 4. Skill资源与公共安装

仓库源为`skills/studyflow-agent/`；安装目录附`binaries/studyflow-agent/`，两者本轮为2.0.0。公共安装位置通常为`~/.agents/skills/studyflow-agent/`，不是项目的`AGENTS.md`；其他Agent使用其支持的Skill目录。应复制整个目录，保留`agents/`、`references/`与`examples/`。

安装程序不覆盖Agent公共目录或修改PATH。公共副本本轮只读核对为1.9.0，未同步到2.0.0；如需同步，先授权目标目录、备份现有自定义内容、复制并校验哈希/格式。安装资源可直接交给其他Agent读取。具体闭环见[Skill2.0契约](../../skills/studyflow-agent/references/closed-loop-contract.md)。
