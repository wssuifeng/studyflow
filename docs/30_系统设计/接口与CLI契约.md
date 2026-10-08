# StudyFlow 接口与CLI契约

直接上游：[需求规格](../20_需求分析/需求规格说明.md)。精确参数以version/capabilities和实际CLI为准。

规则：[Skill](../../skills/studyflow-agent/SKILL.md)、[CLI契约](../../skills/studyflow-agent/references/cli-contract.md)、[整课答卷](../../skills/studyflow-agent/references/course-answers.md)。

- 先version/capabilities/doctor/today，核对数据工作区，读取JSON结果和退出码。
- plan/task：计划、任务、日程；course：导入、详情、多知识点、answers get/save/submit。
- assignment queue/submission get：真实答案、待批改叶子与历史；review write：只写允许状态。
- revise/retest：通常由用户在UI执行，只有明确授权才可代提交新版本。
- document read/check、snapshot generate：工作区文件与短上下文。
- workspace export/import：一致性备份和校验迁移；db-upgrade：开发迁移。

course import相对文件按进程cwd解析；跨目录传工作区内绝对路径。document read传工作区相对路径。已注册路径不自动增补新题。

Engine协议1.2为UTF-8 JSONL stdio；app1.4.0沿用中文写入、整课事务并增加个人草稿与写入诊断。内部错误只返回安全diagnostic_id，不回显请求、答案、SQL或凭据。


## 一体化学习新增契约

- CLI `course study-open --id <course-id> --idempotency-key <key> [--new-version] --format json`开始或恢复；`course study-detail --study-id <id> --format json`只读固定版本。已有`course detail`是源课程，不冒充本轮冻结上下文。
- `course answers save/submit`的JSON对象可指定`study_session_id`，不能混用不同学习轮次的草稿。原命令保持兼容。
- `assignment queue`新增`batches`及逐题`study_context`、`snapshot_status`。有快照时以其题面/材料为批改依据；路径只是来源位置。
- Engine新增`course.study.open/get/progress.save/reading.complete`；标准JSONL和协议1.2保持兼容。仅参数与方法增量，不强制改变外部调用路径。
- 阅读位置保存携带expected_version；答案写入沿用逐题expected_version、父记录和原幂等键。新版只在本轮通过/阅读完成后显式开启，不自动升级。


## STUDY-02增量契约（2026-10-02）

- CLI `course notes-get --study-id ...`与`course notes-save --study-id ... --lesson-id ... --file ... --expected-version ... --idempotency-key ...`；详细字段见[个人草稿契约](../../skills/studyflow-agent/references/study-notes.md)。相对草稿路径按工作区解析，TXT/Markdown均作为UTF-8纯文本读取。

- Engine `course.notes.get/save`共享Core，协议仍为1.2；save需要study_session_id、lesson_id、text、expected_version和原幂等键，不能跨冻结轮次写入。

- doctor可写探针执行写入/flush/fsync，按实际结果汇总healthy和workspace.writable。只读、锁、约束与磁盘满有稳定分类；日志不可写时返回diagnostic_unavailable，不回显请求正文或SQL参数。

- 窗口新建与Always on Top属于Tauri桥，不属于CLI业务命令。独立窗口复用同一Vue/Engine；浏览器只验证专注布局，不能据此宣称原生失焦、最小化或关闭已验收。

## 1.5.0：计划笔记与工具窗

Engine协议仍为1.2，通过capabilities发现增量：

| 入口 | 输入 | 输出与边界 |
|---|---|---|
| Engine plan.notebook.get | plan_line_id | version、blocks、legacy_notes；纯读取 |
| Engine plan.notebook.save | plan_line_id、blocks、expected_version、idempotency_key | 新version与规范化块；独立笔记事务，不提交答案 |
| CLI plan notebook-get | --id --format json | 确认工作区后读取计划笔记 |
| CLI plan notebook-save | --id --file --expected-version --idempotency-key --format json | UTF-8 JSON必须位于数据工作区；全列表版本控制 |

块字段与冲突约束见[Skill笔记契约](../../skills/studyflow-agent/references/plan-notebooks.md)。course.notes.get/save和旧CLI保留为兼容接口。

原生open_tool_window采用异步任务，只接受notes/exercises/outline与安全本地ID，主窗限定创建/切换/级联关闭。工具页只读取已存在的course.study.get，不能以新窗口偷开学习轮次。窗口间prepare/ack/release汇合保存，超时绝不视为成功；正文摘录向当前笔记编辑窗口确认转交。

## 结构化课程包契约（app/Core1.6.0，2026-10-03）

- `course validate-package --file <absolute-package.json> --format json`：校验 `studyflow.course-package/1`，不创建Service、工作区、数据库或发布文件。
- `course import-package --file <absolute-package.json> --format json`：复用校验器，以跨进程发布锁保护不可变内容目录，整课单事务登记；返回课程/计划ID、知识点/块/题量与 `created`。计划须事先存在。
- 同包同内容重放返回原课程ID与 `created=false`；同ID内容变化返回 `COURSE_PACKAGE_CONFLICT`；同计划同名旧课程返回 `COURSE_ALREADY_EXISTS`；另有发布正在进行时返回 `COURSE_PACKAGE_BUSY`。不把这些拒绝当成已覆盖成功。
- 稳定ID限定在所属范围，practice只能引用本知识点已有题目。未知字段、重复JSON键、错误类型、重复ID、缺失引用与超限整包拒绝；精确限额和字段见[课程包契约](../../skills/studyflow-agent/references/course-packages.md)。
- `course detail`与冻结 `course study-detail`提供 `content_blocks`；开始学习冻结结构块和题目。旧轮次无结构块时仍走原Markdown，不能用源课程新内容替换旧轮次上下文。
- 计划笔记摘录支持 `source_block_id`，与原 `source_study_id`、知识点归属一起校验；不创建额外答卷模型。

CLI与Skill适用任意外部Agent，Skill1.9.0；Engine传输协议仍为1.2。该1.6.0基线当时无独立安装CLI或原位更新；1.7.0增量见下节。正在学习的内容仍不热替换。

## 完整优化契约（app/Core1.7.0 / Skill2.0.0）

安装包包含`binaries/studyflow.exe`，与Engine同一冻结Core；任意外部Agent可用绝对路径与显式工作区操作。不改系统PATH。中立入口：`studyflow call --method <method> --file <workspace-request.json> --format json`，成功要求退出码0且`ok=true`，失败退出非0。先发现capabilities，`system.schema`返回`studyflow.agent-contract/2`；未知字段与类型/版本错误有字段路径。

| 方法 | 请求核心字段 | 实现边界 |
|---|---|---|
| assignment.summary | role、plan_line_id/course_id/status/cursor、limit1—100、history | 分页行动投影，不含答案正文；同轮快照批读取一次 |
| assignment.context | submission_ids（1—100） | 答案逐条、冻结知识点contexts去重；按需读评分参考 |
| review.write | 既有字段、issues | quote/location/reason/guidance/next_action；原句须存在，PASSED不带待改issues |
| review.retest.publish | parent_submission_id/title/prompt/objective/idempotency_key，requirements/agent_reference可选 | 发布后冻结；Agent参考不返回学习UI；答案携带retest_task_id |
| submission.resolve-branch | parent_submission_id/child_submission_id/reason | 显式授权下选择有效历史分支，不删除记录 |
| course.update.preview | course_id/path/expected_revision | 返回语义差异、影响轮次与preview_hash |
| course.update.apply | 同上+preview_hash/idempotency_key | 保持Course/计划身份，旧实体与轮次保留；预检后载荷变化拒绝 |
| plan.edit | plan_line_id/expected_version/idempotency_key/operation/values | UPDATE/REORDER/SCHEDULE/RESCHEDULE/CANCEL_SCHEDULE；事务CAS |
| plan.schedule.list | plan_line_id | 安排不改变学习证据 |
| plan.notebook.search/export | plan_line_id；搜索query与可选course_id/lesson_id | 中文搜索、正常Markdown导出；不提交作答 |
| course.source.read | study_session_id/lesson_id，可选block_id | 只读冻结来源，不开启新轮次 |
| workspace.export/validate/restore | path；restore另需target_root | 一致性备份、清单/hash校验、独占维护租约与新目录恢复 |
| system.changes | 无 | 变更token；编辑器有输入时只提示，不卸载覆盖 |
| system.installation | 无 | 实际CLI位置/工作区；无自动PATH操作 |

旧Engine `assignment.queue`保持完整响应；命名CLI `assignment queue`默认轻量，可显式`--full`兼容。新增 `course.study.open.review_round=true` 是已通过后主动复习同一内容的明示轮次，保留旧证据，不自动开始或继承通过。

写入`ENGINE_TIMEOUT/ENGINE_UNCONFIRMED`保留原载荷/键，回读或稳定重放；`ENGINE_BUSY`表示尚未派发。旧无hash回执返回`IDEMPOTENCY_UNVERIFIABLE`，同键变载荷返回`IDEMPOTENCY_KEY_CONFLICT`。课程包/整课统一最多500题。详细字段由源码Schema及[Skill闭环契约](../../skills/studyflow-agent/references/closed-loop-contract.md)保持一致。
