export type InstallationInfo = {
 workspace:string;workspace_exists:boolean;cli_path:string|null;cli_argv:string[];source_cli:boolean;
 cli_available:boolean;skill_path:string;skill_kind:'installed'|'repository';skill_available:boolean;agent_ready:boolean
}
function normalizedPath(value:string){const path=value.replace(/\\/g,'/').replace(/\/+$/,'');return /^[a-z]:/i.test(path)?path.toLowerCase():path}
function absolutePath(value:unknown):value is string{return typeof value==='string'&&(/^[a-z]:[\\/]/i.test(value)||value.startsWith('/')||value.startsWith('\\'))}
export function agentConnection(info:InstallationInfo|null,doctorRoot?:string){
 if(!info)return {ready:false,reason:'正在读取接入信息…',text:''}
 if(!info.agent_ready||!info.cli_available||!info.skill_available||!absolutePath(info.skill_path)||!absolutePath(info.workspace)||!Array.isArray(info.cli_argv)||!info.cli_argv.length||!absolutePath(info.cli_argv[0]))return {ready:false,reason:'CLI、Skill 或工作区尚不可用，请检查安装资源后重试。',text:''}
 if(doctorRoot&&normalizedPath(doctorRoot)!==normalizedPath(info.workspace))return {ready:false,reason:'工作区连接信息不一致，暂不复制。请重新连接后重试。',text:''}
 const text=[
 '请使用 StudyFlow '+(info.skill_kind==='installed'?'安装内 Skill':'仓库 Skill')+'：',info.skill_path,
 ...(info.cli_path?['CLI 绝对路径：',info.cli_path]:['源码 CLI（使用下列完整参数，不要猜测独立 exe）：']),
 'CLI 调用参数（逐项）：',JSON.stringify(info.cli_argv),
 '明确工作区：',info.workspace,
 '先读取 Skill，再使用上述 CLI 与明确工作区执行 version、capabilities、doctor；核对返回路径和可写状态。',
 '课程编写/修订先按 Skill 制课入口读取 course-authoring、authoring-presentation 与相应任务提示词；英语额外读取 english-course-authoring。若副本缺少规则，明确报告缺口，不凭聊天记忆宣称质量通过。',
 '作答前可见的题面/requirements 只含任务与约束，不放参考答案或评分答案清单；作者参考独立关联练习 ID。结构校验、内容审核与真实渲染分别验证。',
 '仅经已发现的 CLI 能力创建/修订课程与批改；不直接 SQL、不替学习者作答、不静默切换工作区。',
 '通用传输：call --method <method> --file <JSON> --format json；具体方法先以 capabilities 和 system.schema 核实。'
 ].join('\n')
 return {ready:true,reason:'已确认 CLI、Skill 和工作区路径。',text}
}
