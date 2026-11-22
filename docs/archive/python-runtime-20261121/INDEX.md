# 1.8.27 Python 后端退役索引

本索引对应全 Rust 替换 W6.1。仓库以 Rust Core、Rust CLI/Engine 和 Tauri/Vue 构建。旧 Web、PyInstaller 入口、Python SQLite 与 MySQL 适配、旧测试服务按本索引归档。

## 恢复与证据

- W0.1 的 `head.bundle`、`worktree.zip`、Git 状态清单及旧 MSI 是原始恢复点。已按迁移计划在隔离目录恢复验证。
- 退役时的确切源码在本目录的本机 `source/`。相对路径保持原样，逐文件 SHA-256 和大小登记在 `source-manifest.json`。`source/` 不进入发布或 Cargo 构建。主仓保留 Git 历史中的已提交版本。
- 本地迁移证据从 `apps/desktop/test-results/rust-migration/2026-11-21-1.8.27/` 查阅。`entrypoints.tsv` 是旧入口索引，`test-map.tsv` 是旧断言映射，`W6.1/` 保存当前入口回执及归档核对。
- 复查旧断言时，在独立目录按清单恢复原路径，并使用 W0 合成工作区。旧输出用于比较契约。现行产品校验从 [实施计划](../../40_开发实施/2026-11-21-全Rust后端替换实施计划.md) 开始。

## 旧模块与现行入口

| 旧范围 | 现行实现或验证 |
|---|---|
| `packages/core` 内的持久化、Alembic、工作区和备份 | `crates/studyflow-core` 的 SQLite 迁移、工作区、归档及写入测试。W1.2–W1.4 覆盖历史行、CAS、异常退出和归档往返。 |
| Python CLI、Engine、PyInstaller、Skill 作者脚本 | `crates/studyflow-runtime` 的原生程序与契约测试，`build-engine.ps1` 装配发布资源。`authoring-workspace` 五个子命令可用当前 CLI 执行。 |
| FastAPI、Jinja、Vite HTTP 代理、MySQL | Tauri `invoke` 和本地 SQLite。旧 HTTP URL、模板及数据库后端属于已批准退役范围。 |
| `smoke-workbench.py`、`smoke_workbench_support.py`、`smoke-iteration.py`、`test_ui_contract.py`、`w0c-browser-verify.py`、`smoke-teaching.py`、`smoke-q234.py`、`smoke-learning-experience.py` | Rust CLI/Engine、Vue 学习套件、`smoke-rust-course-shell.py` 与 CLI 修订闭环共同覆盖课程、作答、计划、笔记、折叠及长正文。旧 Web 表单、旧工作台与 HTTP 桥断言随对应入口退役。 |
| `smoke-native-tools.py`、`native_acceptance_cases.py`、`native_fault_proxy.py`、`native_clipboard_guard.py`、`smoke-tool-bridge.py`、`smoke-app-panel.py` | 真正 WebView2 原生课程壳验证独立笔记窗、单编辑权、主题同步和保存冲突。Vue 渲染/状态测试覆盖工具窗响应与离开保护。旧模拟故障桥的组合场景、物理多屏和真实 IME 保留历史证据及待验记录。 |
| `smoke-notebook-v2.py`、`smoke-notebook-sources.py`、`smoke-notebook-pressure.py` | Rust `notebooks` 覆盖来源、长文与竞写，Vue 笔记 v2 和课程壳覆盖布局、草稿恢复及跨窗。旧浏览器的专项压力数值保留为历史数据。 |
| `smoke-english.py`、`smoke-english-light.py`、`smoke-english-annotation.py`、`smoke-english-keyboard.py`、`smoke-english-feedback.py`、`smoke-english-remediation.py`、`smoke-training-comfort.py`、`smoke-english-practice.py` | Rust 英语、错题和批改回归与 Vue 英语交互承接；`smoke-english-focused.py`、`smoke-english-cli.py` 和 `smoke-english-legacy-submit.py` 验证真原生运行、旧轮次、阅读/听力/作文、离线音频和反馈。旧浏览器像素、旧工具布局与键盘物理手感仅保留原证据。 |
| `smoke-course-authoring.py`、`smoke-course-reset.py` | `course_packages`、`course_lifecycle`、`authoring_cli` 与 CLI 修订脚本核对发布前校验、作者报表、冻结状态及受保护的重开。 |
| `smoke-themes.py`、`smoke-cinnabar-paper.py` | `test:themes` 与 Rust 原生课程壳验证三主题及主题导入。旧 HTTP 浏览器的截图归档。 |
| `smoke-agent-discovery.py` | 建树/安装双模式验证 CLI 定位、能力和内置 Skill。旧脚本固定本机安装路径和公共 Skill 目录，保留原稿供历史核对。 |

保留 `verify-rust-desktop.ps1` 和独立 Python 测试驱动。测试环境可装 Playwright、psutil，桌面产品、原生 CLI、Engine 与随包 Skill 只使用本次原生产物。
