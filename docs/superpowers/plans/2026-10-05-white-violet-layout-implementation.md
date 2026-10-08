# White Violet Learning Workspace Layout Implementation Plan

> **For agentic workers:** Inline execution in the current session. The implementation must preserve the existing Vue/Tauri/Core contracts and run the listed checks after each task.

**Goal:** 将白紫主题的课程阅读工作区重构为清晰的桌面布局：右侧工具区关闭时阅读区完整展开，打开时以等高工作面并排显示，并分离计划进度、课程进度和学习状态。

**Architecture:** 保留现有 `CourseReader`、`workspacePanel`、`CourseToolsSidebar` 和学习状态所有者，仅调整展示层 DOM 结构与 CSS。课程标题区固定承载计划进度，知识点导航承载课程内部进度，底部/工具区承载保存与学习生命周期状态；窄窗口使用产品已有的紧凑工作面退化，不让面板遮挡阅读内容。

**Tech Stack:** Vue 3、TypeScript、现有 CSS token/theme runtime、Tauri window shell；不新增依赖，不改 Core/CLI/Engine/API。

## Global Constraints

- 仅修改 `../../../apps/desktop/src/` 展示层及对应前端测试/实施记录；不改 Core、CLI、Engine、学习数据、答案/笔记状态所有者。
- 继续支持结构化 `content_blocks` 与旧 Markdown fallback 两条正文路径。
- 右侧栏关闭时，计划进度仍必须在课程头部可见；右侧栏打开时不得重复一套完整计划进度。
- 1920×1080、1440×900 为完整桌面工作区；800×600、720×600 必须可达练习/笔记并避免正文与工具无限叠加滚动。
- 失败保存、恢复、退出保护、版本冻结和独立工具窗口行为不变。
- 不新增积分、排行榜、网络图片或业务字段。

---

### Task 1: 课程工作区布局状态与进度归属

**Files:**
- Modify: `../../../apps/desktop/src/features/courses/components/CourseReader.vue`
- Modify: `../../../apps/desktop/src/features/courses/styles/study.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/reader.css`
- Modify: `../../../apps/desktop/src/shared/layout/workspacePanel.ts`（仅在几何契约不足时）

**Interfaces:**
- Consumes: 现有 `data.course`, `data.lessons`, `sidebarOpen`, `shellPanel.geometry`, `readingPercent`。
- Produces: 课程头部固定显示计划进度；`study-unit-layout` 在 `tools-hidden` 与 `panel-open` 下使用明确网格；窄窗口使用 `compact` 工作面。

- [ ] 将当前标题区的下拉式进度改为可持续可见的 `reader-progress-summary`，至少包含：计划名称/课程位置、`01 / 11`、阅读百分比、当前学习状态；不覆盖工具按钮。
- [ ] 保留现有同步反馈按钮和状态文字，不改变事件处理。
- [ ] 让 `study-unit-layout` 的类名由 Vue 状态明确表达 `tools-hidden`、`tools-visible`、`tools-compact`，不要依靠默认类名猜测。
- [ ] 桌面宽度下右侧工具区参与 CSS Grid，不使用绝对定位覆盖正文；只有 `compact` 才采用覆盖式紧凑工作面。
- [ ] 让关闭工具区时中央阅读区使用可读的最大宽度，打开工具区时中央阅读区自然收缩，正文滚动位置保持。

### Task 2: 学习进度与知识点导航组件视觉层级

**Files:**
- Modify: `../../../apps/desktop/src/features/courses/components/KnowledgePointPager.vue`
- Modify: `../../../apps/desktop/src/features/courses/styles/reader.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/study.css`

**Interfaces:**
- Consumes: 既有 `lessons`, `index`, `answerStates`, `busy`。
- Produces: 计划进度、课程知识点进度、当前知识点状态三者视觉上不重叠，状态仍由文字/图标与颜色共同表达。

- [ ] 将知识点导航标记为“课程路径”，显示当前知识点 `01 / N`，不再与计划 `01 / 11` 共用一个视觉容器。
- [ ] 进度轨道必须使用独立标签、独立数值和独立 track；禁止文字压在 track 上。
- [ ] 按未学习、当前、已完成、待批改/待修正/待复测保留语义状态，颜色不能是唯一依据。
- [ ] 确保窄宽度下导航可水平滚动或折叠，不把课程正文挤成不可读窄列。

### Task 3: 教学内容与旧 Markdown fallback 的统一基础层

**Files:**
- Modify: `../../../apps/desktop/src/features/courses/styles/content.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/reader.css`
- Modify: `../../../apps/desktop/src/shared/styles/markdown.css`

**Interfaces:**
- Consumes: `TeachingContent` 七类教学块和旧 `markdown-body`。
- Produces: 两条正文路径拥有一致的正文宽度、标题层级、表格/代码/引用边界和滚动行为。

- [ ] 不改变 Markdown HTML 结构，只补齐主题作用域下的排版变量和状态边界。
- [ ] 让概念、步骤、对比、提醒、练习提示有明确层级，但避免每块都成为厚重卡片。
- [ ] 检查 65ch 左右正文行宽、中文行高、代码块横向滚动和表格横向滚动。
- [ ] 限制正文区域的滚动层级，避免页面、正文、工具三层同时抢占滚轮焦点。

### Task 4: 前端回归验证与交付记录

**Files:**
- Modify: `../../../apps/desktop/scripts/test-white-violet.cjs`（仅补充布局断言时）
- Modify: `../../../docs/40_开发实施/_中控.md`
- Create: `../../../docs/40_开发实施/2026-10-05-白紫第一待选正式版布局实施与验证.md`

**Interfaces:**
- Consumes: 已实施的展示层改动和现有合成课程夹具。
- Produces: 构建、主题测试、学习回归和尺寸截图证据；记录未执行的原生窗口/DPI/人工视觉验收。

- [ ] 运行 `npm --prefix apps/desktop run build`。
- [ ] 运行 `npm --prefix apps/desktop run test:themes` 与 `npm --prefix apps/desktop run test:learning`。
- [ ] 使用现有 smoke 脚本验证课程阅读、工具区开合、作答/笔记可达、保存失败恢复和退出保护不回归。
- [ ] 生成或复用 1920×1080、1440×900、800×600、720×600 截图证据。
- [ ] 仅将工程验证标记为通过；用户视觉验收仍标记 `not_evaluated`，不修改主题默认确认状态。

---
