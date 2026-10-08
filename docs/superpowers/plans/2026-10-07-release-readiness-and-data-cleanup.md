# StudyFlow 收尾与发布就绪实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成当前收尾范围内可安全执行的 SQLite 批量写入修复、课程清理保护、公共 Skill 备份隔离、安装包重建与工程文档收口；对受运行身份限制的真实工作区删除保留明确阻塞证据。

**Architecture:** 保持 Vue/Tauri/Python Core/CLI/SQLite 既有边界，不引入 Redis、第二套前端或第二套数据访问路径。SQLite 仅在连接初始化阶段配置本机临时存储策略，课程清理由现有受控 CLI 执行，课程 Markdown 文件删除必须经过数据库引用保护；安装包使用当前源码和已构建的 Core/Engine 重新生成。

**Tech Stack:** Python 3.13、SQLAlchemy 2、SQLite、pytest、Vue/TypeScript、Tauri、PowerShell、MSI/NSIS。

## Global Constraints

- 不执行 `git reset`、`git clean`、`git add .`，不覆盖其他 Agent 的未提交修改。
- 不直接 SQL 删除真实工作区课程，不修改 ACL，不提权，不绕过工作区租约。
- 公开仓库只包含 StudyFlow 源码、工程文档和正式 Skill；学习资料、数据库、答案、日志、安装包不进入仓库。
- 自动化测试通过不等于用户视觉验收；真实工作区清理、安装体验和最终视觉仍分别记录。
- SQLite 修复必须先有可复现失败证据，再实施最小修复；不得以 WAL、批量提交或全局缓存服务替代根因调查。

## Task 1: 固化 SQLite 临时文件根因并修复整课写入

**Files:**
- Modify: `../../../packages/core/src/studyflow/infrastructure/persistence/database.py`
- Modify: `../../../packages/core/tests/conftest.py` only if the production engine helper needs direct fixture coverage
- Modify: `../../../packages/core/tests/test_optimization.py` only if a focused regression assertion is needed
- Test: `../../../packages/core/tests/test_optimization.py`

**Evidence:** 在 Windows + Python 3.13 + SQLite 3.45.3 下，实际 StudyFlow schema 使用 ORM `RETURNING` 连续写入约 187—281 行时返回 `SQLITE_CANTOPEN`；同一 schema 的 raw driver 写入通过；在连接建立时设置 `PRAGMA temp_store=MEMORY` 后 500 条连续写入通过。失败时数据库回滚完整，说明不是业务数据约束错误，而是 SQLite 默认文件临时存储路径在该长事务/RETURNING 路径上的临时文件打开失败。

- [x] **Step 1: Add an engine-level regression assertion**

运行：

```powershell
& '.\\.venv\\Scripts\\python.exe' -m pytest tests/test_optimization.py::test_whole_course_500_boundary_and_501_no_registration -q
```

当前预期：失败并出现 `sqlite3.OperationalError: unable to open database file`。

- [x] **Step 2: Configure only SQLite connections**

在 `build_engine()` 与 `init_db()` 共用的连接初始化路径中，为 SQLite 连接设置 `PRAGMA temp_store=MEMORY`，确保测试中直接 `create_engine(...); init_db(engine)` 的连接也获得配置；不得对 MySQL 分支设置 SQLite pragma，不得加入 WAL 或外部缓存依赖。

- [x] **Step 3: Verify the focused regression**

运行：

```powershell
& '.\\.venv\\Scripts\\python.exe' -m pytest tests/test_optimization.py::test_whole_course_500_boundary_and_501_no_registration -q
& '.\\.venv\\Scripts\\python.exe' -m pytest tests/test_optimization.py::test_hundred_courses_two_thousand_answers_queue_projection -q
```

预期：两项均 PASS，且 501 题仍在校验阶段拒绝，不创建课程提交记录。

- [x] **Step 4: Run all Core tests**

运行：

```powershell
& '.\\.venv\\Scripts\\python.exe' -m pytest -q
```

记录总数、失败项和运行日期；若其他失败与本改动无关，不扩大修复范围。

## Task 2: 保护共享 Markdown 与 Document 记录

**Files:**
- Modify: `../../../packages/core/src/studyflow/modules/courses/service.py`
- Modify: `../../../packages/core/tests/test_course_cleanup.py`

- [x] **Step 1: Add a shared-path fixture case**

构造两个课程，使两个 `Lesson.markdown_path` 指向同一个工作区 Markdown；清理逻辑执行后验证仍有课程/引用时不删除该文件和 `Document` 记录。

- [x] **Step 2: Implement reference-aware deletion**

删除文件前重新查询未被待删除课程集合覆盖的 `Lesson.markdown_path` 引用；只有没有剩余课程引用、没有受保护的文档记录用途时，才删除物理文件和 `Document` 行。删除结果中保留跳过文件的结构化 warning。

- [x] **Step 3: Run cleanup tests**

运行：

```powershell
& '.\\.venv\\Scripts\\python.exe' -m pytest tests/test_course_cleanup.py -q
```

## Task 3: 隔离公共 Skill 备份目录

**Source:** `<public-skill-root>\studyflow-agent`

**Backups:**

```text
<public-skill-root>\studyflow-agent.bak-20261006-ui-tools
<public-skill-root>\studyflow-agent.bak-20261006-ui-tools-final
<public-skill-root>\studyflow-agent.bak-20261006-ui-tools-contract
```

**Target:** `<public-skill-backup-root>\studyflow-agent\`

- [x] **Step 1: Verify source/target boundaries and hashes**
- [x] **Step 2: Move only the three backup directories with one PowerShell operation**
- [x] **Step 3: Recount files and compare SHA-256; confirm public Skill root contains only the formal `studyflow-agent` directory**

不得移动正式 Skill，不得删除备份，不得处理其他技能目录。

## Task 4: 重建并校验安装包

**Files/commands:**

```powershell
$env:CARGO_NET_OFFLINE='true'
npm --prefix apps/desktop run tauri -- build --bundles msi,nsis --no-sign
```

- [x] **Step 1: Confirm frontend build and Core/Engine binaries are current**
- [x] **Step 2: Build MSI and NSIS from current source**
- [x] **Step 3: Record absolute paths, file sizes, timestamps and SHA-256**
- [x] **Step 4: Confirm the package includes the current Vue UI, Core/Engine and formal `studyflow-agent` Skill without private learning data**

## Task 5: 真实工作区课程清理尝试

**Workspace:** `<workspace>`

**Backup:** `<workspace>\.studyflow\backups\pre-course-purge-20261006.zip`

- [x] **Step 1: Run `workspace purge-courses --dry-run --format json` with the rebuilt CLI** — 返回 `WORKSPACE_READ_ONLY`，在租约获取前阻塞，未进入删除。
- [ ] **Step 2: 由正常桌面/安装进程取得租约后运行 `--confirm --backup <verified-backup> --format json`；当前不执行。
- [ ] **Step 3: 清理成功后验证 `course list --format json`；当前不执行。

If the current identity still receives `WORKSPACE_READ_ONLY`, stop without ACL changes, privilege escalation, lease deletion, SQL, or direct SQLite deletion; report this as an external execution blocker.

## Task 6: 工程文档收口

**Files:**
- Modify: `../../../AGENTS.md`
- Modify: `../../../README.md`
- Modify: `../../../docs/00_总控.md`
- Modify: `../../../docs/40_开发实施/_中控.md`
- Create or modify: `../../../docs/40_开发实施/2026-10-07-收尾与发布就绪实施记录.md`

记录：SQLite 根因和修复前后压力测试、共享文件保护测试、Skill 备份隔离、安装包构建证据、真实工作区清理是否阻塞，以及 `business_acceptance` 仍需用户确认的边界。

## Completion Criteria

- Core 全量测试与前端既有学习/主题测试通过。
- 课程清理专项通过，且共享 Markdown 不被误删。
- 公共 Skill 备份不再参与 Skill 发现。
- MSI/NSIS 重新构建并有哈希证据。
- 真实工作区要么在正常租约下完成受控清理，要么保留 `WORKSPACE_READ_ONLY` 证据并明确需要用户在安装版/桌面进程中执行。
- 文档只写入真实命令结果，不把计划或自动化测试写成用户验收。


