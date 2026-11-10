# 2026-11-01 · StudyFlow Agent入口与协作工作区修订记录

## 1. 背景与范围

用户反馈外部Agent读取安装内Skill后的开场过于抽象：一次加载很多规则，随后默认追问是否制课。期望改为先核验工作区、缺少AGENTS协作区时初始化，用于跨会话状态、执行记录和课程作者归档，再展示本机当前可做的事项。此工作区用于跨会话恢复状态、保存工作/执行记录和课程作者草稿/归档；不是CLI数据库，也不是仅为改变`doctor.governance_ready`而补治理文件。

本轮仅修订仓库`studyflow-agent` Skill并初始化明确材料根下的专用协作目录；未实施产品源码变更、未打包安装、未修改CLI数据或课程。

## 2. Skill改动

- 仓库Skill版本标为2.9.12。
- 启动阶段只运行实际CLI `version`、`capabilities`、`doctor`，核对返回数据根及健康/可写；`today`、`system.schema`、课程列表与具体规则延后到任务确定后。
- 明确区分StudyFlow AppData数据根与外部Agent协作根。`doctor.workspace.governance_root`不自动作为资料根；不在AppData、安装目录、源码仓库或混合用途父目录初始化AGENTS文件。
- 首次启动在已指定材料根下建独立`StudyFlow-Agent-Workspace`；如果没有既定路径，Skill规定使用用户主目录下的稳定默认目录并对用户报告路径。
- 增加入口菜单，按实际capabilities呈现状态/课程/批改/英语/笔记/维护/作者归档等类别；安装版不支持的事项显式标出。用户已提出具体任务时不再泛问。
- 新增[entry-workflow.md](../../skills/studyflow-agent/references/entry-workflow.md)并为制课流程增加归档/会话恢复约束；详细规则按选择的任务加载。

## 3. 协作工作区初始化

初始化前只读核对`D:\XiaoGongJu-data`现有顶层内容及目标子目录不存在，未更改既有同级文件。新工作区：

`D:\XiaoGongJu-data\StudyFlow-Agent-Workspace`

含`AGENTS.md`、`INDEX.md`、`state/current.md`、`state/decisions.md`、`records/`、`course-archive/drafts/`、`course-archive/published/`。记录说明跨会话恢复顺序、数据根/资料根边界、CLI写入约束、课程版本归档方式和隐私禁区。

为使没有收到D盘路径的后续会话也能定位该工作区，另建用户级指针`%USERPROFILE%\.studyflow-agent\workspace.json`，只含format、资料根绝对路径和日期；Skill按该固定路径读取，不扫描用户目录。

初始化回执注明：CLI app 1.8.15/protocol 1.2，指定AppData根匹配，doctor `healthy=true`、`workspace.writable=true`、数据库`ready`。capabilities实测37项CLI能力、81项Engine能力。本轮未读课程正文/答案/笔记、未写业务数据。此前外部执行者报告曾执行`system.schema`和只读`course list`；清单未留存且本轮未重新核验，故不把它当当前状态。

## 4. 验证与部署边界

- `python -X utf8 .../quick_validate.py skills/studyflow-agent`：通过。
- Skill内部相对Markdown链接：21份文件扫描，未发现缺失目标。
- 用户级JSON指针可解析，format=1且目标协作区包含入口说明文件。
- `git diff --check`：通过（最终复核）。
- 实测副本版本：仓库源与安装内Skill均2.9.12；用户公共目录仍2.9.11。安装目录更新前47个文件备份已逐一哈希核对，之后仅同步本轮相关的仓库文件：[SKILL.md](../../skills/studyflow-agent/SKILL.md)、[course-authoring.md](../../skills/studyflow-agent/references/course-authoring.md)、[entry-workflow.md](../../skills/studyflow-agent/references/entry-workflow.md)；源/安装有效文件各41份、哈希零差异，安装副本quick_validate通过。未同步公共副本；该Skill修订批次当时未重建MSI，后续建包见第5节。
- 未操作真实课程/学习数据、未直接SQL、未提交或推送Git。工作区初始化是用户要求的协作资料创建，不等于课程制作授权。

## 5. 后续状态

本记录的Skill修订与安装目录文件同步先于MSI重建：当时App/CLI为1.8.15、安装目录Skill已为2.9.12，MSI尚未重编译。用户随后授权重建，已生成包含Skill2.9.12的1.8.16未签名MSI；版本、哈希、测试和边界见[后续构建记录](2026-11-01-1.8.16-Skill入口更新安装包构建记录.md)。该MSI尚未安装，现有App仍1.8.15；公共Skill仍2.9.11。

外部会话需将工作目录设为`D:/XiaoGongJu-data/StudyFlow-Agent-Workspace`或在任务中明确提供该路径，才能读取协作区`AGENTS.md`；若只给CLI/AppData路径，Skill按配置或稳定默认资料根恢复。当前无课程任务，下一次按用户目标读取相关参考与CLI上下文。