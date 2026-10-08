# 主题切换滚动、课程侧栏与大纲修复实施计划

> **For agentic workers:** 本计划在当前会话内按小步执行；每步先验证再修改，不覆盖其他 Agent 的未提交工作。

**Goal:** 修复设置页滚到底切换序光后的空白布局、统一白紫/序光课程工作区的固定左栏，并让两套主题都显示同步的课程/本节大纲。

**Architecture:** 只把固定视口几何应用到课程工作区和独立工具窗口，不让主题把普通设置/计划页面强制变成阅读器视口。课程页面由共享 AppShell 提供固定左栏空间，CourseReader 始终向共享侧栏挂载 CourseOutline，主题只负责视觉样式，不决定大纲是否存在。

**Tech Stack:** Vue 3 + TypeScript + Vite；Tauri/WebView2；Node 静态契约测试；合成数据原生烟测。

## Global Constraints

- 不读取、修改或删除真实学习资料、真实答案、真实工作区数据库。
- 不使用 `git reset`、`git clean`、`git add .`，不覆盖其他 Agent 未提交修改。
- 不新增第二套前端，不改变 Core/API/答案/笔记/事务/幂等逻辑。
- 设置、计划、反馈页面保持普通文档滚动；只有课程工作区与独立工具窗口使用固定视口布局。
- 白紫与序光必须共享 CourseOutline 的挂载和选择行为；主题只改变外观。
- 自动化测试不替代用户最终视觉验收。

---

### Task 1: 防止主题布局污染设置页

**Files:**
- Modify: `../../../apps/desktop/src/features/courses/styles/sequence-light.css`
- Modify: `../../../apps/desktop/scripts/test-sequence-light.cjs`
- Modify: `../../../apps/desktop/scripts/smoke-native-tools.py`

**Interfaces:**
- 课程固定布局选择器只匹配 `.app-shell.learning-shell` 或 `.app-shell.focus-shell`。
- 普通 `/settings`、`/plans`、`/queue` 页面继续由基础 AppShell 文档流管理。

- [x] **Step 1: 写失败契约**

在 `test-sequence-light.cjs` 断言序光 CSS 不得使用无范围的 `body { overflow:hidden }` 和 `.app-shell { height:100dvh... }` 作为普通页面规则，且必须包含课程/焦点窗口限定选择器。

- [x] **Step 2: 最小修复**

将序光全局几何收敛为：

```css
:root[data-theme-id="sequence-light"] body { background: var(--theme-surface-canvas); }
:root[data-theme-id="sequence-light"] .app-shell.learning-shell,
:root[data-theme-id="sequence-light"] .app-shell.focus-shell { height:100dvh; min-height:0; grid-template-rows:minmax(0,1fr); overflow:hidden; }
:root[data-theme-id="sequence-light"] .app-shell.desktop-shell.learning-shell,
:root[data-theme-id="sequence-light"] .app-shell.desktop-shell.focus-shell { height:calc(100dvh - 44px); }
```

并把序光的课程主内容、侧栏滚动规则限制到 `.learning-shell`/`.focus-shell`。

- [x] **Step 3: 原生回归**

在 `smoke-native-tools.py` 中增加“设置页滚到底 → 切换序光”的断言：切换后 `body` 不得为 `overflow:hidden`，页面文档高度应大于视口且当前设置内容仍可见；随后继续执行原有序光课程烟测。

---

### Task 2: 统一课程左栏为固定层

**Files:**
- Modify: `../../../apps/desktop/src/app/styles/workspace.css`
- Modify: `../../../apps/desktop/scripts/test-white-violet.cjs`
- Modify: `../../../apps/desktop/scripts/test-sequence-light.cjs`

**Interfaces:**
- 课程壳仍通过 AppShell 的第一列保留导航宽度；左栏固定不随中央阅读区滚动。
- 面板打开/收起时使用 `--panel-nav-width`，不改变主阅读区和工具区的列契约。

- [x] **Step 1: 写失败契约**

主题测试断言课程壳必须包含 `position:fixed` 的共享左栏规则，并使用 `top/bottom/width` 约束；不允许只依赖主题自己的 `position:sticky`。

- [x] **Step 2: 最小实现**

在 `workspace.css` 增加共享规则：

```css
.app-shell.learning-shell > .sidebar {
  position:fixed !important;
  inset:0 auto 0 0;
  width:var(--panel-nav-width,228px);
  height:auto !important;
  min-height:0;
}
.app-shell.desktop-shell.learning-shell > .sidebar { top:44px; }
```

保留 AppShell 网格第一列作为布局占位，避免主内容覆盖固定左栏；课程大纲内部继续自己滚动。

---

### Task 3: 白紫挂载并渲染课程/本节大纲

**Files:**
- Modify: `../../../apps/desktop/src/features/courses/components/CourseReader.vue`
- Modify: `../../../apps/desktop/src/features/courses/styles/white-violet.css`
- Modify: `../../../apps/desktop/scripts/test-white-violet.cjs`

**Interfaces:**
- `CourseOutline` 的 props/emits 不变：课程选择、本节标题跳转、返回课程目录。
- CourseReader 无论 `sequenceTheme` 为何值，只要是课程导航可见，就把同一份 `CourseOutline` Teleport 到 `#course-sidebar-content`。

- [x] **Step 1: 写失败契约**

断言 `CourseReader.vue` 的 CourseOutline Teleport 不再由 `sequenceTheme &&` 控制；白紫 CSS 必须包含课程槽位、课程/本节切换、列表滚动和当前项样式。

- [x] **Step 2: 最小实现**

把：

```vue
<Teleport v-if="sequenceTheme && shellPanel?.navigationVisible?.value" ...>
```

改为：

```vue
<Teleport v-if="shellPanel?.navigationVisible?.value" ...>
```

在白紫样式中提供与序光相同的结构布局变量，但使用白紫现有 surface/border/accent 令牌。不得复制业务逻辑或新增主题分支。

- [x] **Step 3: 运行前端回归**

运行 `npm --prefix apps/desktop run test:learning`、`npm --prefix apps/desktop run test:themes`、`npm --prefix apps/desktop run build`。

---

### Task 4: 原生验证与发布产物

**Files:**
- Modify: `../../../docs/40_开发实施/_中控.md`
- Modify: `../../../docs/00_总控.md`
- Create: `../../../docs/40_开发实施/2026-10-07-主题切换滚动与课程侧栏修复记录.md`
- Modify: `../../../README.md`
- Modify: `../../../AGENTS.md`

- [x] **Step 1: 运行完整验证**

```powershell
npm --prefix apps/desktop run test:learning
npm --prefix apps/desktop run test:themes
npm --prefix apps/desktop run build
$env:PYTHONPATH='packages/core/src'; packages/core/.venv/Scripts/python.exe -m pytest -q packages/core/tests
$env:PYTHONPATH='apps/desktop/scripts'; packages/core/.venv/Scripts/python.exe apps/desktop/scripts/smoke-native-tools.py
```

- [x] **Step 2: 重建 Engine、MSI 与 NSIS**

使用既有 `build-engine.ps1` 和 `npm run tauri build`，记录绝对路径与 SHA-256。

- [x] **Step 3: 回写事实**

记录根因、修复范围、测试结果、产物哈希；`business_acceptance` 继续保持 `not_evaluated`。
