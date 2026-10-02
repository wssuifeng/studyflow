# AGENTS.md · StudyFlow

<!-- project-docs-governance:start -->

本目录是独立软件源码仓库，不是学习者数据工作区。

## 一、文档体系纪律（本节不可删除或弱化）

1. **会话开始**：先读 `docs/00_总控.md` 和当前阶段 `_中控.md`，再按任务选读直接上游产物，不递归读取源码或学习数据。
2. **任务合法性**：执行总控当前指针和用户明确授权动作；新想法放 `docs/90_全局/非开发计划内灵感留存处.md`，不自动实施。
3. **冻结保护**：`docs/10_系统定义/系统定义.md` 沿用已确认边界；目标、核心功能、非目标或完成阶段的语义修改先走决策和用户确认。
4. **状态回写**：写入后更新对应中控、产物与总控工作台；工具成功不能代替用户验收。只读 audit 不回写。
5. **决策留痕**：架构、数据源、CLI/Skill边界、技术选型、发布和阶段切换写 `docs/90_全局/决策日志.md`。
6. **状态唯一来源**：阶段三态只出现于总控阶段表与中控状态行；任务用复选框或文字，不冒充阶段状态。
7. **归档纪律**：软件历史进入 `docs/archive/`；个人学习资料不迁入仓库。已有文件移动须有清单，未经确认不得删除。
8. **信息来源纪律**：规范保留官方来源，验证保留真实命令和日期；学习记录、文档生成与工程测试不可混淆。
9. **术语纪律**：先查 `docs/90_全局/术语表.md`，软件治理、学习计划、源码和数据工作区不能混用。

## 二、依赖纪律与冲突裁决（本节不可删除或弱化）

系统定义 → 需求分析 → 系统设计 → 开发实施 → 系统测试 → 评估验收 → 部署运行。任务有直接上游依据，不能只在代码增加无定义支持的新需求。确认的定义和用户最新明确决定优先；总控是状态权威，中控为镜像。冲突先核对证据，不自行升级阶段。

治理恢复与审计使用 `project-docs-governance`，软件发布与实施必须有独立授权。结构脚本不证明业务正确性。

<!-- project-docs-governance:end -->

## 三、项目信息

- Vue/TypeScript 唯一正式 UI 在 `apps/desktop/src/`；Tauri/Rust只承载窗口和Engine。旧FastAPI/Jinja2是兼容开发层，不新建第二套前端。
- Python Core/CLI/Engine和测试在 `packages/core/`；默认SQLite自动管理，可选MySQL只读环境变量。
- 工程文档在 `docs/`；公共Skill源在 `skills/studyflow-agent/`，外部Agent按Skill和CLI返回值操作，不依赖聊天记忆。
- 源码、安装目录、数据工作区独立；模拟作答需要明确授权，不直接SQL，不复制活SQLite，不提交私人内容。
- 当前app1.3.0用户体验仍待复验；公开源码不代表正式阶段验收。
- 构建见 `docs/40_开发实施/构建与开发.md`。新分支默认 `codex/`，Conventional Commit，精准staging，不强推main，不擅改仓库权限。
- 使用简体中文；代码、命令、路径、API保持原文。

## 四、模块化维护纪律

- 后端六个业务模块：planning、courses、learning、reviews、documents、workspace。模型、服务和必要DTO/查询辅助按业务归属，不机械复制Java空层次。
- AppService仅装配和委派；跨模块只读聚合属于application，不把新业务SQL堆回Facade或CLI/Engine适配器。
- 各模块共用一个Runtime；整课保存/提交必须沿用同一Session、单事务与幂等凭据，禁止按模块各自commit。
- 持久化Base和模型注册只有一套；旧Python导入入口仅做兼容，不新增第二份模型、规则或命令实现。
- Vue按app/features/shared维护；shared不能反向依赖features。组件按功能归位，公共API契约不依赖页面组件。
- 样式拆分保持既有层叠顺序；结构重构不顺带改UI需求。Tauri仅承载窗口、Engine进程和协议桥，不写业务规则。
- 包内resources只读并随wheel/Engine打包；学习工作区、安装目录、源码分离，不把site-packages或冻结解压目录当作数据目录。
- 公开检查只允许apps/desktop与packages/core两个明确子项目；源码目录迁移后先跑worktree检查，不把旧本地环境/运行数据纳入提交。
