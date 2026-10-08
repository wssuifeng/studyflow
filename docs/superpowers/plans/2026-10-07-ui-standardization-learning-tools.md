# StudyFlow UI Standardization and Learning Tools Implementation Plan

> **For agentic workers:** This plan is executed inline in the current session. Do not use direct SQL, do not reset or clean the working tree, and do not overwrite unrelated agent changes.

**Goal:** Establish one stable StudyFlow page skeleton while improving the sequence-light/white-violet learning tools, exercise presentation, plan notebook, sound volume controls, and safe course-workspace reset.

**Architecture:** Keep one Vue/Tauri frontend and Python Core/CLI. Themes provide validated semantic tokens, bounded visual recipes and local assets, while the shell owns layout geometry, scroll ownership and functional regions. Course lifecycle remains in Core; the UI exposes only compact actionable summaries. Course cleanup is an explicit CLI/Core operation with a dry-run and backup-first guard.

**Tech Stack:** Vue 3 + TypeScript, Tauri 2/Rust window shell, Python Core/CLI, SQLite managed by Core, Node test runner, Playwright/Python smoke tests.

## Global Constraints

- Fixed learning skeleton: titlebar → fixed navigation/course outline → reading area → optional tool rail.
- The sequence/white-violet right tool rail contains only `exercises` and `notes`; outline and progress are not tool tabs.
- Do not render a per-question lifecycle timeline; detailed lifecycle remains in backend/review pages.
- Preserve plan-level notebook data and existing answer/review records unless the explicit workspace purge command is executed.
- No direct SQL, SQLite file editing, or deletion by filesystem manipulation.
- Theme JSON remains non-executable; custom themes cannot inject templates or arbitrary CSS.
- Public Skill synchronization must be backed up and must copy the complete repository Skill tree, not only `../../../skills/studyflow-agent/SKILL.md`.
- Do not claim user visual acceptance from automated tests.

### Task 1: Create the implementation contract and regression tests

**Files:**
- Create: `../../../docs/30_系统设计/UI标准化与主题契约-v2.md`
- Modify: `../../../apps/desktop/scripts/test-white-violet.cjs`
- Modify: `../../../apps/desktop/scripts/test-sequence-light.cjs`
- Modify: `../../../apps/desktop/scripts/test-themes.cjs`

- [ ] Record fixed shell regions, scroll owners, theme responsibilities, tool-tab contract, exercise and notebook UI responsibilities.
- [ ] Add static guards that sequence tools expose only exercises and notes and that lifecycle timelines are absent from `KnowledgeExercises.vue`.
- [ ] Add theme checks for bounded layout recipes and fixed sidebar geometry.
- [ ] Run `npm --prefix apps/desktop run test:themes` and keep failures as the implementation checklist.

### Task 2: Standardize theme layout ownership

**Files:**
- Modify: `../../../apps/desktop/src/shared/themes/display.ts`
- Modify: `../../../apps/desktop/src/shared/themes/contract.ts`
- Modify: `../../../apps/desktop/src/shared/themes/runtime.css`
- Modify: `../../../apps/desktop/src/app/styles/workspace.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/white-violet.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/sequence-light.css`
- Modify: `../../../apps/desktop/src/shared/themes/builtin/white-violet.json`
- Modify: `../../../apps/desktop/src/shared/themes/builtin/sequence-light.json`

- [ ] Keep theme tokens and bounded recipes, but make shell geometry and tool ownership shared defaults.
- [ ] Prevent a theme from changing the number/order of functional regions or scroll owners.
- [ ] Keep fixed left navigation and independent central reading scroll for both official themes.
- [ ] Preserve backward parsing for existing theme JSON and custom-theme safety.
- [ ] Run theme unit tests and production build.

### Task 3: Simplify learning tools and redesign exercise cards

**Files:**
- Modify: `../../../apps/desktop/src/features/courses/dock/state.ts`
- Modify: `../../../apps/desktop/src/features/courses/components/CourseToolsSidebar.vue`
- Modify: `../../../apps/desktop/src/features/courses/components/CourseToolContent.vue`
- Modify: `../../../apps/desktop/src/features/learning/components/KnowledgeExercises.vue`
- Modify: `../../../apps/desktop/src/features/learning/styles/answers.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/sequence-light.css`
- Modify: `../../../apps/desktop/src/features/courses/styles/white-violet.css`

- [ ] Remove `outline` from right-tool state while preserving stale-state normalization for persisted old docks.
- [ ] Keep outline in the left course-outline area and keep progress in the reader/outline summary.
- [ ] Replace each question lifecycle ribbon with a prominent question template and a compact course-level answer summary.
- [ ] Keep backend lifecycle data and feedback/history navigation intact.
- [ ] Allow skip, autosave, previous/next and final course submission without changing Core contracts.
- [ ] Run learning unit tests and browser smoke checks.

### Task 4: Redesign plan notebook for compact and detached modes

**Files:**
- Modify: `../../../apps/desktop/src/features/notes/components/PlanNotebook.vue`
- Modify: `../../../apps/desktop/src/features/notes/styles/notebook.css`
- Modify: `../../../apps/desktop/src/features/courses/components/CourseToolsSidebar.vue`
- Modify: `../../../apps/desktop/src/features/courses/styles/sequence-light.css`

- [ ] Keep one plan-level continuous notebook data model.
- [ ] Add compact rail mode and wide detached-document mode using the same component/data.
- [ ] Improve source grouping, search/scope controls, reading mode, export, conflict recovery and document-level save state.
- [ ] Reduce card repetition and empty vertical space; keep source attribution visible but subordinate.
- [ ] Run notebook and tool-window tests.

### Task 5: Add sound volume preference

**Files:**
- Modify: `../../../apps/desktop/src/shared/ui/interaction.ts`
- Modify: `../../../apps/desktop/src/features/workspace/components/WorkspaceSettings.vue`
- Modify: `../../../apps/desktop/src/features/workspace/components/ThemeSettings.vue`
- Modify: `../../../apps/desktop/src/shared/styles/iteration.css`
- Modify: `../../../apps/desktop/src/shared/styles/index.css`
- Modify: `../../../apps/desktop/scripts/test-themes.cjs`

- [ ] Preserve v1 on/off preference and migrate to a v2 volume preference.
- [ ] Add a bounded 0–100 volume setting with a safe default and optional preview action.
- [ ] Apply volume through a shared Web Audio master gain, synchronized across windows.
- [ ] Keep theme sound profile separate from user volume.
- [ ] Test migration, persistence and disabled/muted behavior.

### Task 6: Add safe course purge CLI/Core flow and reset the current workspace

**Files:**
- Modify: `../../../packages/core/src/studyflow/modules/courses/service.py`
- Modify: `../../../packages/core/src/studyflow/application/facade.py`
- Modify: `../../../packages/core/src/studyflow/interfaces/cli/commands/courses.py`
- Modify: `../../../packages/core/src/studyflow/interfaces/cli/commands/workspace.py`
- Modify: `../../../packages/core/src/studyflow/interfaces/cli/capabilities.py` or its current capability registry
- Create/modify: `../../../packages/core/tests/test_course_cleanup.py`
- Modify: `../../../skills/studyflow-agent/SKILL.md`
- Create: 课程清理契约已并入当前 CLI/工作区治理文档，历史计划不再引用独立文件。

- [ ] Add read-only `workspace purge-courses --dry-run --format json`.
- [ ] Add explicit confirmation and backup requirement for the write operation.
- [ ] Delete course-owned records through Core service relationships, preserving plan lines, schema and workspace settings.
- [ ] Remove course-owned content files only through a validated service-owned path list; never recursively delete arbitrary workspace files.
- [ ] Export the current workspace before the destructive operation, run dry-run, then execute the confirmed purge.
- [ ] Re-run `doctor` and `today` and verify zero courses.

### Task 7: Synchronize the public Skill and finalize evidence

**Files:**
- Modify: `<public-skill-root>\studyflow-agent\...` (explicit public copy, backed up first)
- Modify: `../../../README.md`
- Modify: `../../../AGENTS.md`
- Modify: `../../../docs/00_总控.md`
- Modify: `../../../docs/40_开发实施/_中控.md`
- Create: `../../../docs/40_开发实施/2026-10-06-学习工具与课程清理实施记录.md`

- [ ] Back up the public Skill directory, then synchronize the full Skill tree from the repository source.
- [ ] Run Skill/CLI help, Core tests, Vue tests/build and browser smoke checks.
- [ ] Record course purge IDs/counts, public Skill hash comparison, and known user-acceptance limitations.
- [ ] Do not commit/push or archive the session unless separately authorized after review.

