# Frontend Shell Hardening Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with a focused verification gate after each task. Do not treat automated tests as user visual acceptance.

**Goal:** 修复前端壳层审计中确认的生命周期、路由滚动、反馈提示和队列分页风险，并把序光/白紫课程壳层收敛到同一套几何与状态反馈标准。

**Architecture:** 保留 `workspace-shell`、`learning-shell`、`focus-shell` 三种职责：`workspace-shell` 管理普通主窗口固定导航和主内容滚动，`learning-shell` 只增加课程阅读布局，`focus-shell` 只服务独立工具窗口。业务状态、Engine 协议和学习数据模型不改；通过 AppShell 的滚动入口、QueueView 的分页边界和共享 CSS Token 修复问题。

**Tech Stack:** Vue 3 + TypeScript、CSS、Node test、Vite；不引入新依赖，不启动 Redis/Memurai，不操作真实学习数据。

## Global Constraints

- 只修改 StudyFlow 源码、前端测试、实施计划和实施记录。
- 不修改真实学习工作区、真实答案、数据库、安装目录或公共 Skill。
- 不使用 `git reset`、`git clean`、`git add .`，不自动 commit/push。
- 课程正文滚动位置不能被普通页面路由滚动重置逻辑破坏。
- `business_acceptance` 保持 `not_evaluated`，自动化通过不等于用户视觉验收。

### Task 1: Lock down the failing lifecycle and navigation behaviors

**Files:**
- Modify: `../../../apps/desktop/src/app/App.vue:47-55,57-63,108-119`
- Test: `../../../apps/desktop/scripts/test-study-tools.cjs` or the nearest existing App lifecycle test file

**Interfaces:**
- Consumes: `prepareTools`, `releaseTools`, `confirmNavigation`, `QueueData`.
- Produces: single-release shutdown cleanup, route-scoped feedback state, a normal-page scroll reset helper.

- [x] **Step 1: Add regression assertions**
  - Assert a failed shutdown preparation cannot release the same request ID through both the immediate branch and `finally`.
  - Assert route changes clear `newFeedback` when leaving course/tool routes.
  - Assert normal route changes reset `.main-content` but do not reset the course reader's internal reading container.

- [x] **Step 2: Implement the smallest fix**
  - Only assign `shutdownRequest` after a successful `prepareTools('shutdown')`, or clear it immediately after explicit release in the failed branch.
  - In `readRoute`, clear stale feedback when the next route is not `course` or `tool`.
  - Add a small `resetMainScrollForRoute` helper that calls `document.querySelector('.workspace-shell:not(.focus-shell) > .main-content')?.scrollTo({top:0,left:0})` after route assignment, without querying `.study-material-body`.

- [x] **Step 3: Run the focused tests**
  - Run: `npm --prefix apps/desktop run test:learning`
  - Expected: all existing learning/lifecycle tests pass, including save-failure exit and tool-window release tests.

### Task 2: Make queue pagination ownership explicit

**Files:**
- Modify: `../../../apps/desktop/src/app/App.vue:53-55,77-80`
- Modify: `../../../apps/desktop/src/features/reviews/components/QueueView.vue`
- Modify if needed: `../../../apps/desktop/src/shared/api/contracts/reviews.ts`
- Test: `../../../apps/desktop/scripts/test-study-tools.cjs` or a new focused queue test under `../../../apps/desktop/scripts/`

**Interfaces:**
- Consumes: `assignment.summary` with `limit` and `next_cursor`.
- Produces: a queue view whose loaded items, cursor, and visible count are internally consistent.

- [x] **Step 1: Define the boundary**
  - Keep `study.today.queue_counts` for the sidebar badge only.
  - Make `QueueView` own queue-page pagination state.
  - Preserve the initial `QueueData` shape for compatibility, but expose `next_cursor` and an explicit loaded-page boundary.

- [x] **Step 2: Implement the smallest compatible change**
  - Avoid presenting the first 100 items as if they were the complete queue.
  - Ensure the “加载更多” control is shown whenever `next_cursor` exists.
  - Do not change review status filtering or Engine method names.

- [x] **Step 3: Test pagination**
  - Add a synthetic queue larger than the initial page.
  - Verify first page, cursor, second page, deduplication, filters, and sidebar count remain consistent.
  - Run: `npm --prefix apps/desktop run test:learning`.

### Task 3: Consolidate shell geometry and theme scroll ownership

**Files:**
- Modify: `../../../apps/desktop/src/app/styles/workspace.css`
- Modify: `../../../apps/desktop/src/shared/themes/runtime.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/sequence-light.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/white-violet.css`
- Modify: `../../../apps/desktop/src/app/styles/shell.css` only when removing a superseded geometry rule is safe
- Modify: `../../../apps/desktop/scripts/test-themes.cjs` and/or `../../../apps/desktop/scripts/test-sequence-light.cjs`

**Interfaces:**
- Consumes: `workspace-shell`, `learning-shell`, `focus-shell`, `data-theme-shell-contract='v2'`.
- Produces: one geometry contract: fixed navigation rail, Grid column 2 main content, one documented reader scroll owner, and no theme-specific change to shell height/position semantics.

- [x] **Step 1: Add static contract assertions**
  - Assert both themes use the shared shell selectors.
  - Assert theme CSS does not reintroduce `position:sticky` or a competing top-level `.app-shell` height rule for ordinary pages.
  - Assert focus windows remain single-column and ordinary pages remain two-column.

- [x] **Step 2: Move geometry to shared rules**
  - Keep fixed navigation, titlebar offset, main-content overflow, and Grid placement in `workspace.css`/`runtime.css`.
  - Remove or narrow duplicate theme rules that set course shell position/height/overflow.
  - Leave theme-specific artwork, spacing, colors, and component styling in theme files.

- [x] **Step 3: Define reader scroll ownership**
  - Use the same semantic owner for both themes: the course reading body owns long-document scrolling; the main shell owns only the page frame.
  - Keep tool panes independently scrollable.

- [x] **Step 4: Run theme tests and build**
  - Run: `npm --prefix apps/desktop run test:themes`
  - Run: `npm --prefix apps/desktop run build`

### Task 4: Remove dead CSS and correct semantic feedback tokens

**Files:**
- Modify: `../../../apps/desktop/src/shared/styles/notices.css`
- Modify: `../../../apps/desktop/src/app/styles/shell.css`
- Modify: `../../../apps/desktop/src/app/styles/desktop.css`
- Modify: `../../../apps/desktop/src/app/styles/workspace.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/white-violet.css`
- Test: `../../../apps/desktop/scripts/test-themes.cjs`

**Interfaces:**
- Consumes: semantic theme tokens (`status-success`, `status-warning`, `status-danger`, `text-inverse`, `surface-active`).
- Produces: reachable status notices, scoped theme artwork rules, and visible focus/connection/save/error feedback.

- [x] **Step 1: Remove unreachable and duplicate declarations**
  - Remove the unreachable `.main-content:has(.native-tool-window) > .status-banner` selector.
  - Remove duplicate workspace token declarations that are overridden by `runtime.css`, keeping one canonical source.
  - Scope white-violet artwork defaults under the white-violet theme selector.

- [x] **Step 2: Correct feedback semantics**
  - Use full-strength success/warning/danger tokens for status dots.
  - Use distinct focused/unfocused titlebar colors.
  - Use inverse or danger foreground on the close-button danger hover state.
  - Use inverse text on brand-colored marks.

- [x] **Step 3: Run theme and learning tests**
  - Run: `npm --prefix apps/desktop run test:themes`
  - Run: `npm --prefix apps/desktop run test:learning`

### Task 5: Final verification and documentation

**Files:**
- Create: `../../../docs/40_开发实施/2026-10-07-前端壳层风险修复实施记录.md`
- Modify: `../../../docs/40_开发实施/_中控.md`
- Modify: `../../../docs/00_总控.md`
- Modify: `../../../README.md`

- [x] **Step 1: Run the complete available verification**
  - `npm --prefix apps/desktop run test:learning`
  - `npm --prefix apps/desktop run test:themes`
  - `npm --prefix apps/desktop run build`
  - Core tests if the existing local environment supports them.

- [x] **Step 2: Record actual results**
  - Record exact counts and commands.
  - Explicitly record whether a real WebView2/Playwright visual run was available.
  - Keep `business_acceptance=not_evaluated` until the user manually checks the installed application.

- [x] **Step 3: Review the final diff**
  - Inspect only the targeted files.
  - Do not stage or commit unrelated worktree changes.
