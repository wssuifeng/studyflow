# StudyFlow

**本地优先的个人学习工作台：学习者使用桌面界面，任意外部 Agent 使用同一套 CLI。**

学习计划 → 顺序课程 → 多知识点 → 作答 → 批改 → 修正/复测 → 下一步。软件不内置在线 AI API，不绑定特定模型供应商；外部 Agent 或人工通过 CLI 编写课程和反馈。

源码 **1.3.0**，Engine 协议 **1.2**，公共 Skill **1.5.0**。当前是持续迭代的验收候选，内部工程测试不等于用户体验验收或生产就绪承诺。

## 主要能力

- 按学习计划聚合课程，兼容当天安排和顺序推进。
- 一门课程包含多个知识点，左右导航保留阅读进度；整课保存和提交作答。
- 批改逐题追溯，保留原答案、修正版、复测、反馈和下一动作。
- 中立 CLI 提供能力发现、课程导入、待批改队列、反馈及上下文操作。
- Tauri 桌面自动管理 Python Engine 和 SQLite，不要求学习者手动开服务。
- Markdown 内容和数据工作区可受控备份、校验和迁移。

## 项目结构

```text
StudyFlow/
├─ desktop/          Vue/TypeScript 界面、Tauri 壳和构建脚本
├─ studyflow_app/     Python Core/CLI/Engine、迁移与测试
├─ skills/           studyflow-agent Skill 的仓库源
├─ docs/             软件工程生命周期文档
├─ scripts/          发布边界检查
└─ .github/          CI、CODEOWNERS、PR 模板
```

仓库不包含个人课程记录、真实答案、数据库、旧学习主控、安装包或原私人 Git 历史。公开示例与测试素材是合成的产品验证内容。

## 开发快速开始（Windows / PowerShell）

需要 Python 3.12+、Node.js 22、Rust 与 Tauri Windows 构建依赖，完整说明见 [构建与开发](docs/40_开发实施/构建与开发.md)。

```powershell
# 仓库根目录
py -3 -m venv studyflow_app/.venv
$python = Join-Path $PWD 'studyflow_app/.venv/Scripts/python.exe'
& $python -m pip install -e './studyflow_app[dev]' 'pyinstaller>=6.10,<7'
& $python -m pytest studyflow_app/tests
npm --prefix desktop ci
npm --prefix desktop run build
& ./desktop/scripts/build-engine.ps1
npm --prefix desktop run tauri -- dev
```

## CLI 和外部 Agent

```powershell
# 明确选择数据工作区；安装目录不等于数据工作区
$env:STUDYFLOW_WORKSPACE = Join-Path $env:LOCALAPPDATA 'StudyFlow-demo'
& $python -X utf8 -m studyflow version --format json
& $python -X utf8 -m studyflow capabilities --format json
& $python -X utf8 -m studyflow doctor --format json
& $python -X utf8 -m studyflow assignment queue --format json
```

只对新建的演示工作区使用 `init`，不能拿初始化修复已有数据。课程生成不表示学习者完成或掌握。

安装 Skill：把 [skills/studyflow-agent](skills/studyflow-agent/SKILL.md) 完整复制到你的 Agent 支持的 Skill 目录。不限 Codex；MSI 当前不安装独立 CLI，也不修改系统 PATH，CLI 从开发环境使用。

## 文档

[工程总控](docs/00_总控.md) · [定义](docs/10_系统定义/系统定义.md) · [需求](docs/20_需求分析/需求规格说明.md) · [架构](docs/30_系统设计/系统架构设计.md) · [数据模型](docs/30_系统设计/数据模型与持久化设计.md) · [CLI](docs/30_系统设计/接口与CLI契约.md) · [发布范围](docs/40_开发实施/公开发布与项目迁移.md)

贡献与合并由仓库所有者决定，见 [CONTRIBUTING](CONTRIBUTING.md) 和 [SECURITY](SECURITY.md)。目前未指定项目级开源许可证；公开不等于已授权所有使用方式，不要替所有者添加许可证。第三方依赖仍遵守各自许可证。
