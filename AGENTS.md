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
- 当前app/Core1.7.0（Engine协议1.2）：SF-01—12与主题底座已实施；2026-10-06已完成序光主主题的真实Tauri/WebView2原生窗口、DPI/显示器枚举、离屏坐标回收、置顶工具窗、保存失败不保存退出和1.7.0安装包构建验证。工程验收记录见docs/40_开发实施/2026-10-06-原生窗口与视觉验收记录.md；`business_acceptance`仍为`not_evaluated`，不把自动化通过写成用户视觉验收。正式内置主题只保留序光与白紫；不擅自操作真实学习数据、公共Skill目录或发布。此前用户只确认1.6.0覆盖安装及课程保留；不推导1.7.0或全部体验验收。THEME-BASE共享主题底座已实现并经前端/隔离Vue验证，旧wave矩阵40项submitted，不表示视觉验收；最新THEME-VISUAL-B允许主代理修改纯展示壳/容器/template/CSS/本地资产，冻结的是Core/API/共享学习状态和可靠保存/退出链，不是所有前端DOM。B01/B02按专项回报未实施，私有overlay/三个试点部分交付但不等于源码重复构建或视觉通过。桌面方向卡为原十方向的详细单一来源；T11/T12否决、T13暂留，不统一锁成工程风。先地基再最多三方向30%可操作骨架给用户看，认可后扩展；v1色板兼容并复用shared/themes。候选只写自己的新visual-v2，主代理独占共享展示源码，旧40产物/矩阵/基线保留；渠道/Skill须在实际宿主核实，不把旧HTTP/格式验证当渲染。新任务按总控当前指针领取。
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

## 五、缓存与本机服务安全纪律

- 当前StudyFlow没有Redis接入需求；主题/反馈/CLI批改不以引入网络缓存服务作为修复方案，复用应用管理SQLite及本机偏好。
- 缓存、构建和测试只用明确的StudyFlow专属目录；应用偏好使用命名空间，不为本软件放开全局缓存/目录ACL、沙箱、防火墙或模型配置。
- 不启动/放开未知归属的Redis/Memurai，不使用全网bind、关闭protected mode、删除认证或全命令全键/全频道权限作为排障捷径。
- 被拦截的操作先定位目标和最小必要权限，不换一种命令表达绕过。只有确认属于本软件且确有依赖，才按审批设计应用专用身份、键/频道前缀和命令白名单；DB编号不能替代授权隔离。
- 只读发现不等于运行配置已修复；服务归属/被拦截命令缺失时保留证据并索取脱敏信息，不擅改其他项目系统服务。核查见[缓存与Redis安全记录](docs/40_开发实施/2026-10-03-缓存与Redis安全核查.md)。

## 2026-10-06 本轮维护状态

- 练习与笔记 UI 已按 `docs/30_系统设计/UI标准化与主题契约-v2.md` 收敛；右侧工具固定为练习/笔记，主题壳通过 `themeShellContract=v2` 保持统一区域职责。
- 公共 `studyflow-agent` 已由仓库源同步，12 个文件 SHA-256 一致；同步前备份保留在用户公共 Skill 目录旁。
- 课程清理只允许通过 `workspace purge-courses --dry-run` / `--confirm --backup`；禁止直接 SQL、SQLite 或递归删除。真实工作区因当前执行身份无法创建租约而未清理。

## 2026-10-07 收尾实施状态

- SQLite 长事务 `SQLITE_CANTOPEN` 根因已定位为默认文件临时存储路径在 Windows ORM `RETURNING` 写入中的临时文件打开失败；SQLite 连接已配置 `PRAGMA temp_store=MEMORY`，Core 全量测试、500/2000规模回归通过。
- 课程清理增加共享 Markdown/Document 引用保护；专项测试为5/5。
- 公共 Skill 历史备份已移至 `<public-skill-backup-root>\studyflow-agent\`，正式 Skill 根目录不再暴露备份副本；仓库源/公共正式副本12文件SHA-256一致。
- 2026-10-07 已重建 MSI/NSIS 和 Core/Engine；产物哈希、冻结 CLI/Engine 烟测和真实工作区清理阻塞见 `docs/40_开发实施/2026-10-07-收尾与发布就绪实施记录.md`。
- 真实工作区清理仍须正常安装/桌面进程取得租约后执行；不修改 ACL、不提权、不绕过租约。用户视觉验收仍不由自动化测试代替。
## 2026-10-07 工具窗口回归约束

- 白紫与序光必须复用同一套练习/笔记工具业务结构；主题 CSS 不得覆盖 `panel-open` 的三栏几何。
- 独立工具窗口根节点是 `app-shell focus-shell`，必须单列满宽；不能只修 `learning-shell.focus-shell`。
- 新增或修改工具布局后，至少运行 `npm --prefix apps/desktop run test:learning`、`npm --prefix apps/desktop run test:themes`、`npm --prefix apps/desktop run build` 与原生 Tauri/WebView2 烟测。
- 自动化烟测和隔离合成数据不等于用户视觉验收；最终安装包仍须由用户实际检查。
## 2026-10-07 主题与课程壳回归约束

- 普通设置/计划/反馈页面必须保持文档滚动；`body` 不得因主题切换被强制 `overflow:hidden`。
- 课程工作区左栏由共享运行时契约统一为 fixed，主阅读区必须明确处于 Grid 第2列；不能只在单个主题文件中覆盖。
- 白紫与序光必须挂载同一 `CourseOutline`，主题只提供视觉样式，不决定大纲业务是否存在。
- 修改主题壳或课程栏位后，需运行学习链、主题测试、Vite 构建和原生 Tauri/WebView2 烟测。


## 2026-10-08 发布候选收口

- 前端壳层审计修复已完成；`test:learning=71/71`、`test:themes=49/49`、Core 全量测试通过、Tauri Rust release tests 7/7。
- 文档治理审计与公开发布边界检查均通过；当前 `business_acceptance=not_evaluated`。
- 1.7.0 MSI/NSIS 已重建，安装包和 `src-tauri/binaries/` 均为本地生成物，不提交 Git。
- 个人学习资料与记录、候选设计和本机审计/发布临时产物属于仓库外私有工作区；公开仓库只保留筛选后的工程文档。
