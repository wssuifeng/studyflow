# 白屏、工具窗口与 CLI 只读路径修复实施计划

> **For agentic workers:** 本计划在当前会话内按小步执行；每步先验证再修改，不覆盖其他 Agent 的未提交工作。

**Goal:** 修复白紫/序光课程工具侧栏打开白屏、独立工具窗口布局异常与工具结构分叉，并让课程清理 dry-run 在工作区不可写时仍可只读运行。

**Architecture:** 课程阅读器、主窗口工具面板和独立工具窗口共用同一套工具内容组件与布局契约；主题只提供视觉变量，不再通过两套业务模板决定工具渲染。CLI 将只读运行时与写入运行时分开：只读查询不创建租约、不改目录、不迁移数据库；写命令继续使用独占租约。

**Tech Stack:** Vue 3 + TypeScript + Vite；Tauri 2/Rust；Python Core + SQLAlchemy；Node test；Playwright/现有 smoke 脚本。

## Global Constraints

- 不读取、修改或删除真实学习资料、答案、数据库和用户工作区课程。
- 不使用 `git reset`、`git clean`、`git add .`，不自动 commit/push。
- 不引入 Redis/Memurai，不绕过 Windows 权限，不删除租约文件。
- 练习与笔记仍是唯一两个工具；答案和笔记状态必须继续共享且可恢复。
- `business_acceptance` 保持 `not_evaluated`，自动化测试不代替用户视觉验收。

---

### Task 1: 固定工具侧栏的白屏最小回归

**Files:**
- Modify: `../../../apps/desktop/scripts/test-dock.cjs`
- Modify: `../../../apps/desktop/scripts/test-white-violet.cjs`
- Modify: `../../../apps/desktop/src/features/courses/components/CourseToolContent.vue`

**Interfaces:**
- `CourseToolContent` 对 `exercises` 和 `notes` 使用显式分支；未知工具值显示安全空状态，不落入笔记分支。

- [ ] **Step 1: 写失败测试**

为 `test-dock.cjs` 增加静态契约：工具内容必须包含 `tool === 'exercises'` 与 `tool === 'notes'` 的显式分支，且不允许使用无条件 `v-else` 渲染笔记。

- [ ] **Step 2: 运行测试确认失败**

运行：`npm --prefix apps/desktop run test:learning`

预期：新增静态契约在当前 `v-else` 实现下失败。

- [ ] **Step 3: 最小实现**

把 `CourseToolContent.vue` 改为显式 `v-if`/`v-else-if`，未知值渲染“工具暂不可用”并保留返回/重开入口，不让异常工具状态把整个 Teleport 子树变成空白。

- [ ] **Step 4: 运行学习链测试**

运行：`npm --prefix apps/desktop run test:learning`

预期：全部通过。

---

### Task 2: 合并白紫与序光工具侧栏结构

**Files:**
- Modify: `../../../apps/desktop/src/features/courses/components/CourseToolsSidebar.vue`
- Modify: `../../../apps/desktop/src/features/courses/components/CourseReader.vue`
- Modify: `../../../apps/desktop/src/features/courses/styles/dock.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/white-violet.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/sequence-light.css`
- Modify: `../../../apps/desktop/scripts/test-white-violet.cjs`
- Modify: `../../../apps/desktop/scripts/test-sequence-light.cjs`

**Interfaces:**
- `CourseToolsSidebar` 保持现有事件接口：`activate/close/select/section/collapse/width/full/unsplit/split/ratio/detach/dock/reorder`。
- `CourseReader` 只传业务数据和 `sequence` 视觉标志；两个主题都必须渲染同一工具内容结构。

- [ ] **Step 1: 写失败测试**

增加主题回归断言：白紫和序光都必须使用 `sequence-tools-panel` 或同一个共享根结构、都包含“练习/笔记”标签、都支持 `#workspace-tool-panel`；白紫不得再依赖独立的旧 `dock-surface` 模板。

- [ ] **Step 2: 运行主题测试确认失败**

运行：`npm --prefix apps/desktop run test:themes`

预期：当前白紫分支仍使用旧 `dock-surface`，新增断言失败。

- [ ] **Step 3: 最小结构实现**

删除 `CourseToolsSidebar.vue` 的主题业务模板分叉，保留一套共享 DOM；把序光差异收敛为根节点 data 属性/主题 class 与 CSS 变量。白紫不得再通过 `sequence=false` 选择另一套行为结构。

- [ ] **Step 4: 修正布局契约**

保证 `workspace-tool-panel` 在面板开启时始终是 AppShell 的第三列；工具面板根元素 `min-width:0; min-height:0; height:100%; overflow:hidden`，内部滚动区承担滚动，不把工具内容撑出主窗口。白紫不再用主题 CSS 把课程学习区强制改成与工具面板重复的第二套栏位。

- [ ] **Step 5: 运行主题与构建测试**

运行：`npm --prefix apps/desktop run test:themes` 与 `npm --prefix apps/desktop run build`。

预期：主题测试全部通过，TypeScript/Vite 构建成功。

---

### Task 3: 修正独立工具窗口的单列桌面布局

**Files:**
- Modify: `../../../apps/desktop/src/app/layout/AppShell.vue`
- Modify: `../../../apps/desktop/src/app/styles/workspace.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/dock.css`
- Modify: `../../../apps/desktop/src/features/courses/components/ToolWindow.vue`
- Modify: `../../../apps/desktop/scripts/test-workspace-panel.cjs`

**Interfaces:**
- 独立窗口仍使用 `#/tool/<tool>` 和 `ToolWindow`，不创建新的课程轮次。
- `focus-shell` 下隐藏主导航，但工具内容必须占据整个窗口，不允许出现左窄栏+右大空白。

- [ ] **Step 1: 写失败测试**

增加静态/几何契约：`focus-shell` 的工具窗口必须使用 `width:100%; min-width:0; height:100%`，`.native-tool-window` 的内容列必须为单列；独立工具窗口不能依赖主窗口的 `workspace-tool-panel`。

- [ ] **Step 2: 运行测试确认失败**

运行：`npm --prefix apps/desktop run test:learning`

预期：当前独立窗口布局约束不足，新增断言失败。

- [ ] **Step 3: 实现单列布局与安全状态**

让 `AppShell` 在 `focus-shell` 下把主内容设为完整窗口；让 `ToolWindow` 的 `ToolSession` 占满剩余高度；对加载失败显示可操作错误态，不渲染空白右侧区域。

- [ ] **Step 4: 构建与原生烟测**

运行前端构建，并在可用环境运行 `smoke-native-tools.py`；若环境缺少 Python 依赖，记录未验证，不伪造通过。

---

### Task 4: 拆分 Core CLI 只读/写运行时

**Files:**
- Modify: `../../../packages/core/src/studyflow/interfaces/cli/runtime.py`
- Modify: `../../../packages/core/src/studyflow/infrastructure/runtime.py`
- Modify: `../../../packages/core/src/studyflow/infrastructure/leases.py`（仅在必要时补充明确错误，不改变锁协议）
- Modify: `../../../packages/core/src/studyflow/interfaces/cli/commands/workspace.py`
- Create: `../../../packages/core/tests/test_cli_read_only_runtime.py`

**Interfaces:**
- `service(*, read_only: bool = False)`：只读模式不创建租约、不 `ensure_layout()`、不迁移。
- `Runtime.session(*, read_only: bool = False)`：只读会话不获取写租约、不提交变更。
- `Service.session(read_only=False)` 向下转发。
- `workspace purge-courses --dry-run` 使用只读服务；`--confirm` 保持写租约和备份前置检查。

- [ ] **Step 1: 写失败测试**

构造只读父目录/只读工作区测试，验证 `preview_course_purge()` 可在无法创建租约文件时读取已有数据库；确认写入命令仍返回 `WORKSPACE_READ_ONLY`。

- [ ] **Step 2: 运行测试确认失败**

运行：`pytest packages/core/tests/test_cli_read_only_runtime.py -q`。

预期：当前 CLI 启动路径在租约创建处失败。

- [ ] **Step 3: 实现只读路径**

只读命令绕过 `workspace_lease`、目录创建和自动迁移；写命令仍通过租约保护。只读路径不得写事件日志、数据库或工作区文件。

- [ ] **Step 4: 运行 Core 回归**

运行专项测试及 Core 全量 pytest；记录 Windows 环境中真实工作区 dry-run 的结果，不操作真实课程删除。

---

### Task 5: 最终验证与发布候选

**Files:**
- Modify: `../../../docs/40_开发实施/_中控.md`
- Create: `../../../docs/40_开发实施/2026-10-07-白屏工具窗口与CLI只读路径修复记录.md`
- Modify: `../../../README.md`（仅补充当前验证命令/限制）
- Modify: `../../../AGENTS.md`（仅补充工具侧栏与只读 CLI 约束）

- [ ] **Step 1: 运行验证矩阵**

依次运行：

```powershell
npm --prefix apps/desktop run test:learning
npm --prefix apps/desktop run test:themes
npm --prefix apps/desktop run build
$env:PYTHONPATH='packages/core/src'; pytest -q packages/core/tests
```

- [ ] **Step 2: 重新编译 Engine 与安装包**

使用仓库已有构建脚本生成 Engine、MSI 和 NSIS；记录绝对路径与 SHA256。

- [ ] **Step 3: 原生人工验收清单**

用户需手动确认：白紫/序光打开练习与笔记、独立窗口最大化/缩放/置顶/放回侧栏、保存失败后的“不保存退出”、DPI/多屏；自动化通过不替代上述验收。

---
