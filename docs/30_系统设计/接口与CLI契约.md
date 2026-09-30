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
