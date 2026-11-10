# 2026-11-01 · StudyFlow Agent长期工作区与质量闸门修订

## 1. 目标与范围

根据用户对新会话入口、长期学习/制课记忆和渲染误判的要求，补全StudyFlow Agent Skill与独立协作工作区的工作流、职责边界、基础文档命名、参考资料归档/使用日志和学习/批改记录规则；随后按用户要求把更新后的Skill编入安装包。本轮不读取或修改StudyFlow业务数据，也未改业务功能代码。

## 2. Skill变更

- Skill源版本：2.9.12 → 2.9.13。
- 新会话入口要求核验实际CLI、扫描明确任务根和Agent协作根；必读当前状态、目标、活动计划、决定及最近相关session/learning/grading记录；按当前CLI能力和已登记工作列出菜单。用户已明确任务时不重复追问；需要时询问是否有新参考资料。
- 新增[workspace-structure.md](../../skills/studyflow-agent/references/workspace-structure.md)：定义`GOAL-*`、`PLAN-*`、`REF-*`协作编号与CLI业务ID的区别；目标完成时间/证据；参考原件、hash、衍生件和逐次使用日志；课程草稿/不可变发布快照；CLI学习证据和每次批改回执的路径、字段及隐私边界。
- 长期闭环改为：目标与条件 → 有限计划 → 参考归档/记录实际阅读 → 草稿 → 结构校验 → 内容审核 → 真实UI渲染 → 授权CLI发布及readback → 学习证据归档 → 批改回执 → 目标/后续计划更新。
- 真实渲染是独立证据关。当前用户提供的CLI实测为37项能力、49个schema方法且无渲染/截图方法；quality-check只读外部回执，不能自证渲染。没有真实桌面端/StudyFlow Vue浏览器结果时必须标未验。
- [cli-contract.md](../../skills/studyflow-agent/references/cli-contract.md)主标题及Notebook format 2标题改成明确的历史兼容说明；本机能力始终按实际CLI发现。

## 3. 协作工作区变更

在既有独立Agent协作根中补足并规范：`state/goals.md`、`goals/`、`plans/`、`references/`、`records/sessions/`、`records/learning/`、`records/grading/`，并更新`AGENTS.md`、`INDEX.md`、`state/current.md`、`state/decisions.md`、课程归档说明和各目录README。未覆盖或迁移历史记录。

协作区目前尚未登记用户目标、计划或参考资料，也没有实际学习/批改记录；只创建规范和索引，不臆造数据。当前CLI状态采用用户提供的预检报告，明确标注本轮未重跑CLI、未查计划/课程/学习队列。用户报告的CLI为App/CLI 1.8.16，实际安装Skill 2.9.12、公共Skill 2.9.11；CLI版本不能证明MSI覆盖安装来源。

## 4. 验证与边界

- `skill-creator/scripts/quick_validate.py`：Skill有效。
- Skill Markdown本地链接：22份文件通过；协作区Markdown本地链接：16份文件通过。
- `audit_project_docs.py`完整运行；本轮新增记录已无断链，仍有3条旧的1.8.13/1.8.14构建记录指向已不存在的临时构建目录/截图，保留历史原文未改。
- `git diff --check`退出0；输出包含既有CRLF/LF转换提示，不是空白错误。
- 没有运行真实渲染、没有course quality-check、没有读取/写入课程、目标、学习答案、笔记或批改队列。
- 前端学习136/136、主题89/89、英语56/56；Core 508 passed/2 skipped；冻结CLI与Engine各48项；前端production build通过。
- UI-contract与release Tauri/WebView2原生smoke未运行：项目venv缺Playwright，系统Python缺SQLAlchemy；未安装依赖。真实课程渲染、course quality-check、计划/课程/学习答案/笔记/批改队列均未查询。
- 本轮未同步公共/安装Skill，未安装MSI，未直接SQL，未提交/推送Git；用户体验与业务/学习效果未验收。

## 5. 1.8.17候选安装包

- 用户在Skill/协作工作区治理完成后要求重编译；源码App/Core版本为1.8.17，Engine协议1.2，MSI包含Skill 2.9.13。
- MSI：`apps/desktop/src-tauri/target/release/bundle/msi/StudyFlow_1.8.17_x64_en-US.msi`；33,849,344 bytes；SHA-256 `B44ED5AFEABA0EB142E1A5668B9EC617644BDC38081B01386162D61C2E49A9A9`。
- `MsiVerifyPackageW=0`；ProductVersion `1.8.17`，ProductCode `{D34C737B-FC02-4964-AB95-28E4098EBB04}`，UpgradeCode `{ABFFC78E-4655-5CA9-B66B-386907AB5FEE}`，Manufacturer `wssuifeng`；签名状态`NotSigned`。
- WiX dark读取45个MSI File载荷；42/42 Skill文件与仓库源逐项SHA-256一致，CLI/Engine各自与构建资源一致。MSI桌面EXE大小及1.8.17版本资源与release EXE相同；字节差异仅3处，字符串从`BUNDLE_TYPE_VAR_UNKNOWN`改为`BUNDLE_TYPE_VAR_MSI`。
- 构建命令：`npm --prefix apps/desktop run tauri -- build --bundles msi --no-sign`。验证回执：`apps/desktop/test-results/msi-1.8.17-verify/verification.json`。
- 未签名、未安装、未复制到维护目录；公共Skill仍2.9.11，安装目录Skill仍2.9.12。MSI候选不代表现有安装更新。

## 6. 后续

新会话按协作区`AGENTS.md` → `INDEX.md` → `state/current.md` / `state/goals.md` / `state/decisions.md` → 活动计划 → 最近相关记录恢复。收到目标或新资料后按固定ID登记；只有实际CLI读取到学习事实时才建learning记录，每次批改写入都建grading回执。后续公共/安装Skill同步、MSI安装和用户体验验收仍分开处理；不由候选构建推导部署或验收完成。
