# 2026-10-06 · screenshot-to-code 原型到真实 Vue 工程适配记录

## 1. 任务状态

- 入口模式：`engineering-adaptation`
- 当前结论：`partial`（工程适配与自动化验证完成；用户最终视觉验收仍为 `not_evaluated`）
- 本轮目标：不再停留在查看设计图，把已生成的 screenshot-to-code 原型映射到真实 StudyFlow Vue/Tauri 工程。
- 未修改：Core、Engine、API 契约、数据库、答案/笔记真实数据、学习状态所有者和可靠退出业务链。
- 未提交、未推送、未生成安装包。

## 2. Skill 使用证据

### 已读取

- `<public-skill-root>/mockup-to-page/SKILL.md`
- `<public-skill-root>/screenshot-to-code/SKILL.md`
- `<public-skill-root>/webapp-testing/SKILL.md`
- `<codex-skill-root>/systematic-debugging/SKILL.md`
- `../../AGENTS.md`

### 实际使用

- `mockup-to-page`：按“原型 → 工程适配 → 独立验证”处理，禁止把单文件原型当正式业务代码。
- `screenshot-to-code`：原型产物作为视觉结构来源，实际参考了工具栏、文档组件、练习生命周期和课程大纲变体。
- `webapp-testing`：使用真实 Chromium + 合成 Core 工作区执行浏览器 smoke 并保存截图。
- `systematic-debugging`：定位 smoke 中多出一次 `course.study.progress.save` 的根因，确认是测试脚本为了截图主动触发 `scroll` 事件导致的预期阅读进度保存，不是主题切换副作用；已改为仅调整截图位置而不触发业务滚动事件。

## 3. 原型来源

- 原型来源：本地维护候选区中的历史 HTML 设计稿（已按用户决定清理，未进入公开仓库）。

这些文件只提供布局、排版、层次和组件视觉参考；原型中的假数据、假保存状态和静态生命周期没有进入正式业务。

## 4. 已适配的正式工程

### 4.1 文档组件

文件：

- `apps/desktop/src/features/courses/components/TeachingContent.vue`
- `apps/desktop/src/features/courses/styles/sequence-light.css`

映射关系：

| 原型视觉组件 | 真实 `TeachingBlock` | 正式行为 |
|---|---|---|
| 定义块 | `concept` | 使用真实正文和摘录记笔记能力 |
| 术语/对照表 | `comparison` | 使用真实 columns/rows，保留横向滚动 |
| 步骤线 | `steps` | 使用真实步骤顺序和正文 |
| 案例卡 | `example` | 使用真实 given/steps/conclusion |
| 提醒块 | `callout` | 使用真实 tone，保留警示语义 |
| 总结条 | `summary` | 使用真实 items |
| 练习入口 | `practice` | 触发真实 `openPractice`，不伪造练习 |

新增 `data-reading-component` 仅用于视觉定位和调试，不改变业务数据。

### 4.2 练习生命周期

文件：

- `apps/desktop/src/features/learning/components/KnowledgeExercises.vue`
- `apps/desktop/src/features/courses/styles/sequence-light.css`

原型的时间线已改为根据真实 `AnswerRow` 推导：

`草稿 → 已提交 → 批改 → 修正/复测 → 通过`

状态来源：

- `row.answer` / `row.draft`
- `row.submission.status`
- `row.action`：`FIRST`、`REVISION`、`RETEST`、`WAITING_RETEST_TASK`、`LOCKED`

保留真实操作：暂时跳过、自动保存、整课提交、查看原答案、查看反馈、修正、独立复测、查看历史版本。原型展示的四个虚构状态不会被静态渲染。

### 4.3 课程大纲

文件：

- `apps/desktop/src/features/courses/components/CourseOutline.vue`
- `apps/desktop/src/features/courses/styles/sequence-light.css`

课程大纲项现在同时显示：真实知识点标题、真实状态文字、状态图标和序号；继续保留“课程大纲 / 本节大纲”切换、当前项高亮、标题定位和返回课程目录。

### 4.4 可靠状态的视觉收束

在 `sequence-light.css` 中补充了：

- 保存失败/恢复提示的统一警示层；
- 不保存退出对话框的桌面端层级；
- 独立工具窗口的条带和底栏视觉；
- 右侧工具栏与练习生命周期的统一间距、阴影、状态色和焦点表现。

同时修复了 `white-violet.css` 中两个未加主题作用域的展示规则，避免 `.teaching-group`、`.step-title` 和 `.teaching-kind-icon` 泄漏到其他主题。

## 5. 验证结果

执行日期：2026-10-06。

| 验证 | 命令/方式 | 结果 |
|---|---|---|
| Vue 类型与生产构建 | `npm run build`（工作目录 `apps/desktop`） | 通过，`vue-tsc` 与 `vite build` 均通过 |
| 主题与展示契约 | `npm run test:themes` | `39 passed / 0 failed` |
| 学习链 | `npm run test:learning` | `64 passed / 0 failed` |
| 真实浏览器与 Core smoke | `packages/core/.venv/Scripts/python.exe apps/desktop/scripts/smoke-themes.py` | `ok: true`，无页面错误；主题切换不产生额外 Core 写入 |
| 截图证据 | 本地测试输出（不入仓库） | 已生成序光/白紫课程、工具栏、笔记、设置、窄屏和缩放截图 |

最新 smoke 证据：

截图和 smoke JSON 为可再生成的本地证据，按公开仓库边界未提交；命令与结果保留在本记录中。

## 6. 尚未等同完成的事项

- 用户尚未完成人眼视觉验收；自动化通过不等于“最终设计已采纳”。
- 原生 OS 窗口、多屏、DPI/系统缩放和真实安装包体验未在本轮重新验证。
- 独立工具窗口的业务共享链已有测试，但本轮没有重新生成独立窗口专用 screenshot-to-code 变体。
- 文档组件仍由结构化 `TeachingBlock` 和旧 Markdown 兼容路径共同承载，不表示所有旧 Markdown 都会自动获得结构化组件语义。

