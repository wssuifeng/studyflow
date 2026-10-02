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

Engine协议1.2为UTF-8 JSONL stdio；app1.3.0提供中文写入和整课事务。内部错误只返回安全diagnostic_id，不回显请求、答案、SQL或凭据。


## 一体化学习新增契约

- CLI `course study-open --id <course-id> --idempotency-key <key> [--new-version] --format json`开始或恢复；`course study-detail --study-id <id> --format json`只读固定版本。已有`course detail`是源课程，不冒充本轮冻结上下文。
- `course answers save/submit`的JSON对象可指定`study_session_id`，不能混用不同学习轮次的草稿。原命令保持兼容。
- `assignment queue`新增`batches`及逐题`study_context`、`snapshot_status`。有快照时以其题面/材料为批改依据；路径只是来源位置。
- Engine新增`course.study.open/get/progress.save/reading.complete`；标准JSONL和协议1.2保持兼容。仅参数与方法增量，不强制改变外部调用路径。
- 阅读位置保存携带expected_version；答案写入沿用逐题expected_version、父记录和原幂等键。新版只在本轮通过/阅读完成后显式开启，不自动升级。
