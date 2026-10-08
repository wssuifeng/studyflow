# StudyFlow

**本地优先的个人学习工作台：学习者使用桌面界面，任意外部 Agent 使用同一套 CLI。**

学习计划 → 顺序课程 → 多知识点 → 作答 → 批改 → 修正/复测 → 下一步。软件不内置在线 AI API，不绑定特定模型供应商；外部 Agent 或人工通过 CLI 编写课程和反馈。

应用/Core **1.7.0**，Engine 协议 **1.2**，仓库/安装资源 Skill **2.0.0**（公共安装副本仍为1.9.0，本轮未改写）。当前是持续迭代的验收候选，内部工程测试不等于用户体验验收或生产就绪承诺。

## 主要能力

- 按学习计划聚合课程，兼容当天安排和顺序推进。
- 一门课程包含多个知识点，紧凑导航保留阅读进度；整课保存和提交作答。
- Agent输入结构化课程包，Vue渲染概念、对比、步骤、案例、提醒、小结和练习组件；不要求学习者阅读或编辑Markdown原文。
- 批改逐题追溯，保留原答案、修正版、复测、反馈和下一动作。
- 中立 CLI 提供能力发现、课程导入、待批改队列、反馈及上下文操作。
- Tauri 桌面自动管理 Python Engine 和 SQLite，不要求学习者手动开服务。
- Markdown 内容和数据工作区可受控备份、校验和迁移。
- 同一套界面的可切换主题：两套正式内置主题（序光、白紫轻学）、受控JSON导入/导出，覆盖教学、练习、笔记和工具区；外观切换不重载学习内容。1.7.0安装包已重新编译，工程验收记录见[原生窗口与视觉验收记录](docs/40_开发实施/2026-10-06-原生窗口与视觉验收记录.md)。用户真实安装和最终视觉舒适度仍需本人验收。

## 项目结构

```text
StudyFlow/
├─ apps/desktop/                 唯一 Vue UI + Tauri 桌面薄壳
│  ├─ src/app/                   应用装配、导航与窗口布局
│  ├─ src/features/              console / plans / courses / learning / reviews / workspace
│  ├─ src/shared/                API 契约、Engine 传输、反馈、themes与公共样式
│  ├─ src-tauri/src/             Engine 进程、工作区发现、命令注册
│  └─ scripts/                   桌面构建与冻结 Engine 烟测
├─ packages/core/
│  ├─ src/studyflow/application/ Facade 装配、聚合查询与演示初始化
│  ├─ src/studyflow/modules/     planning / courses / learning / reviews / documents / workspace
│  ├─ src/studyflow/interfaces/  CLI / Engine / 兼容 Web 适配器
│  ├─ src/studyflow/infrastructure/ 事务、配置、持久化、资源与诊断
│  ├─ src/studyflow/shared/      共用领域约束与工具
│  ├─ src/studyflow/resources/   历史迁移、兼容 Web 资源、合成示例
│  └─ tests/                    业务与架构契约回归
├─ skills/studyflow-agent/       外部 Agent 操作 Skill
├─ docs/                        软件工程生命周期文档
├─ scripts/                     发布边界检查
└─ .github/                     CI、CODEOWNERS、PR 模板
```

仓库不包含个人课程记录、真实答案、数据库、旧学习主控、安装包或原私人 Git 历史。公开示例与测试素材是合成的产品验证内容。

## 开发快速开始（Windows / PowerShell）

需要 Python 3.12+、Node.js 22、Rust 与 Tauri Windows 构建依赖，完整说明见 [构建与开发](docs/40_开发实施/构建与开发.md)。

```powershell
# 仓库根目录
py -3 -m venv packages/core/.venv
$python = Join-Path $PWD 'packages/core/.venv/Scripts/python.exe'
& $python -m pip install -e './packages/core[dev]' 'pyinstaller>=6.10,<7'
& $python -m pytest packages/core/tests
& $python scripts/check_publish_boundary.py --worktree
npm --prefix apps/desktop ci
npm --prefix apps/desktop run build
& ./apps/desktop/scripts/build-engine.ps1
npm --prefix apps/desktop run tauri -- dev
```

## CLI 和外部 Agent

```powershell
# 明确选择数据工作区；安装目录不等于数据工作区
$env:STUDYFLOW_WORKSPACE = Join-Path $env:LOCALAPPDATA 'StudyFlow-demo'
& $python -X utf8 -m studyflow version --format json
& $python -X utf8 -m studyflow capabilities --format json
& $python -X utf8 -m studyflow doctor --format json
& $python -X utf8 -m studyflow assignment queue --format json
```

只对新建的演示工作区使用 `init`，不能拿初始化修复已有数据。课程生成不表示学习者完成或掌握。

模块职责、事务边界与兼容入口见 [模块化结构设计](docs/30_系统设计/模块化结构重构设计.md)。源码迁移不迁移安装目录或学习数据；旧本地开发环境不应直接移动复用。

安装 Skill：把 [skills/studyflow-agent](skills/studyflow-agent/SKILL.md) 完整复制到你的 Agent 支持的 Skill 目录。不限 Codex；1.7.0 MSI 包含同Core构建的 `binaries/studyflow.exe` 和Skill资源，不修改系统PATH；使用绝对路径即可，不要求学习者有Python/源码。公共Skill副本需要显式复制到Agent支持的目录。

## 文档

[工程总控](docs/00_总控.md) · [定义](docs/10_系统定义/系统定义.md) · [需求](docs/20_需求分析/需求规格说明.md) · [架构](docs/30_系统设计/系统架构设计.md) · [数据模型](docs/30_系统设计/数据模型与持久化设计.md) · [CLI](docs/30_系统设计/接口与CLI契约.md) · [发布范围](docs/40_开发实施/公开发布与项目迁移.md)

贡献与合并由仓库所有者决定，见 [CONTRIBUTING](CONTRIBUTING.md) 和 [SECURITY](SECURITY.md)。目前未指定项目级开源许可证；公开不等于已授权所有使用方式，不要替所有者添加许可证。第三方依赖仍遵守各自许可证。

## 1.7.0 完整优化候选

- 稳定幂等回执与唯一答案版本链；反馈页只读并精准返回本轮题目。超时保持原请求，不把结果未确认当成失败重发。
- 引用原句的结构化批改、独立冻结复测题、修正与复习轮次；不根据提交/读完推断掌握。
- 小体积分页队列、按需去重上下文、CLI `call` 中立入口与JSON Schema；其他Agent无需本聊天历史。
- 原位课程修订预检与发布，保持课程身份和历史；正在学习的快照不热替换。
- 桌面备份/校验/新目录恢复、计划管理、笔记搜索/阅读/导出/冻结来源、阅读偏好。

详见[完整实施计划](docs/40_开发实施/实施计划.md)与[交付记录](docs/40_开发实施/2026-10-03-SF-01-12实施交付记录.md)。候选构建不是用户验收；真实学习数据、安装包和测试运行资料不进入公开Git。

安装CLI示例（不要假设在PATH）：

```powershell
$cli = '<install-directory>\binaries\studyflow.exe'
$env:STUDYFLOW_WORKSPACE = '<confirmed-data-workspace>'
& $cli version --format json
& $cli capabilities --format json
& $cli doctor --format json
& $cli assignment queue --format json
# 新接口由capabilities发现；请求JSON放在明确工作区内
& $cli call --method assignment.context --file '<data-workspace>\context.json' --format json
```

旧1.6.0用户仅确认覆盖安装与课程保留，1.7.0仍需实际安装/学习体验验收。运行目录以工作区页面为准，不把安装位置当作课程数据位置。

## 主题配置与设计扩展

当前正式内置主题仅有“序光”（`sequence-light`）与“白紫轻学”（`white-violet`），其中白紫仍是默认主题；也可以导入本地JSON作为自定义主题。格式和扩展约束见[主题契约](docs/30_系统设计/前端主题与交互契约.md#8-theme-base已实现的配置与接口2026-10-03)。可从`apps/desktop/src/shared/themes/builtin/`复制完整配置，修改ID/色板，再于`apps/desktop`运行`npm run theme:check -- <theme.json>`只读校验。主题不是任意CSS/JS插件，不需要网络缓存服务。候选比较入口见[主代理提示词](docs/40_开发实施/前端主题样式专项-主代理提示词.md)。

## 当前维护说明（2026-10-06）

当前 UI 以统一学习工作区为基线：左侧课程导航、中央阅读区、可选右侧练习/笔记工具。练习题不再给每题渲染生命周期时间线；笔记以计划级连续文档处理；操作音效支持 0—100 音量并跨窗口同步。外部 Agent 应使用仓库 `skills/studyflow-agent` 与 CLI，不直接操作数据库。课程清理必须先导出并验证备份，再执行受控 `workspace purge-courses`；未完成用户视觉验收前，不将自动化验证写成最终体验通过。

## 2026-10-07 收尾状态

本轮已修复 Windows/SQLite 长事务写入的临时存储问题：SQLite 连接使用 `PRAGMA temp_store=MEMORY`，500/2000规模回归与 Core 全量测试通过；课程清理增加共享 Markdown/Document 保护；公共 Skill 历史备份已移出 Skill 发现根目录。当前 1.7.0 MSI/NSIS 已重新构建，冻结 CLI/Engine 合成烟测通过。

真实学习工作区课程清理仍需在正常 StudyFlow 安装/桌面进程中取得工作区租约后执行。安装包未自动安装，原生窗口、DPI、多屏、置顶工具窗、主题和最终视觉舒适度仍需用户验收。详见 [收尾与发布就绪实施记录](docs/40_开发实施/2026-10-07-收尾与发布就绪实施记录.md) 与 [实施计划](docs/superpowers/plans/2026-10-07-release-readiness-and-data-cleanup.md)。
## 2026-10-07 · 白紫与独立工具窗口修复

白紫主题打开练习/笔记的主窗口白屏与独立工具窗口右侧大面积空白已修复：两套主题复用同一工具结构，`panel-open` 使用三栏网格，独立 `focus-shell` 使用单列满宽布局。`test:learning` 67/67、`test:themes` 40/40、Core 全量测试、原生 Tauri/WebView2 烟测及最终 1.7.0 MSI/NSIS 已通过/重建。安装包和 SHA-256 见[修复记录](docs/40_开发实施/2026-10-07-白屏工具窗口与CLI只读路径修复记录.md)。
## 2026-10-07 · 主题切换与课程侧栏修复

已修复设置页滚到底切换序光后的底部空白、白紫课程左栏不固定、白紫缺失课程/本节大纲，以及 fixed 侧栏导致正文被压到第一列的问题。白紫与序光现在共享课程大纲组件；`test:learning` 67/67、`test:themes` 43/43、Core 全量测试、原生烟测通过，1.7.0 MSI/NSIS 已重建。详见[修复记录](docs/40_开发实施/2026-10-07-主题切换滚动与课程侧栏修复记录.md)。
## 2026-10-07 · 普通工作区壳层统一修复

已将 `/today`、`/plans`、计划详情、`/queue`、`/settings` 纳入与课程阅读页一致的主窗口壳层：左侧主导航固定，主内容独立滚动；课程阅读与独立工具窗口保持各自专用布局。前端学习链 67/67、主题 43/43、Vite 构建通过。用户仍需在安装包中进行最终视觉验收。详见 [实施记录](docs/40_开发实施/2026-10-07-普通工作区壳层统一修复记录.md)。
## 2026-10-08 · 前端审计修复与发布候选收口

补审后重新核对了完整源码：`assignment.summary` 已由 Engine extensions 路由注册，原“未注册”意见是假阳性；工具窗口 flush、计划编辑锁、工作区切换异常路径、dock 边界、筛选空态、超时清理、音量默认值和空态语义问题已修复。

验证结果：`test:learning` 71/71、`test:themes` 49/49、Vite 构建通过；Core `tests/test_engine.py` 为 25 passed、1 skipped。审计修复记录见[2026-10-07-前端壳层审计修复记录](docs/40_开发实施/2026-10-07-前端壳层审计修复记录.md)。`business_acceptance` 仍为 `not_evaluated`，安装包需要用户实际安装验收。2026-10-08 已重新构建 MSI/NSIS：MSI SHA-256 为 `83E1DC36FEDEE8CF96FF441041A40150F5FBC67063DA16EA64EFBA280E673EC3`，NSIS SHA-256 为 `163DFB9A34180D6D1C5797574DFC2161C78E90082DEEBD0D7C9A6CC2D71CD0B7`。

### 工作区边界

- `StudyFlow`：公开软件源码、公开 Skill、工程文档和合成测试，不放个人学习资料、真实答案、数据库或安装包。
- `学习资料与记录`：个人学习计划、课程记录、答案和复盘，保持在根目录的私有数据工作区，不纳入公开仓库。
- `本地维护`：候选设计、审计临时产物、会话交接和本机发布记录，建议作为独立的私有维护工作区；只有经过筛选的长期规则或工程结论才复制到 `StudyFlow/docs`，不把整个目录迁入仓库。