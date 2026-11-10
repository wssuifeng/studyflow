export type InstallationInfo = {
 workspace:string;workspace_exists:boolean;cli_path:string|null;cli_argv:string[];source_cli:boolean;
 cli_available:boolean;skill_path:string;skill_kind:'installed'|'repository';skill_available:boolean;agent_ready:boolean;
 agent_workspace_entry_path:string|null;agent_workspace_entry_status:'found'|'missing'|'invalid'
}
function normalizedPath(value:string){const path=value.replace(/\\/g,'/').replace(/\/+$/,'');return /^[a-z]:/i.test(path)?path.toLowerCase():path}
function absolutePath(value:unknown):value is string{return typeof value==='string'&&(/^[a-z]:[\\/]/i.test(value)||value.startsWith('/')||value.startsWith('\\'))}
export function agentConnection(info:InstallationInfo|null,doctorRoot?:string){
 if(!info)return {ready:false,reason:'正在读取接入信息…',text:''}
 if(!info.agent_ready||!info.cli_available||!info.skill_available||!absolutePath(info.skill_path)||!absolutePath(info.workspace)||!Array.isArray(info.cli_argv)||!info.cli_argv.length||!absolutePath(info.cli_argv[0]))return {ready:false,reason:'CLI、Skill 或工作区尚不可用，请检查安装资源后重试。',text:''}
 if(doctorRoot&&normalizedPath(doctorRoot)!==normalizedPath(info.workspace))return {ready:false,reason:'工作区连接信息不一致，暂不复制。请重新连接后重试。',text:''}
 const status=info.agent_workspace_entry_status
 const validStatus=status==='found'||status==='missing'||status==='invalid'
 if(!validStatus||(status==='found'&&!absolutePath(info.agent_workspace_entry_path)))return {ready:false,reason:'Agent 协作区入口状态无效，请重新读取接入信息。',text:''}
 const entryPath=status==='found'?info.agent_workspace_entry_path:'未发现'
 const restoreInstruction=status==='found'
  ?'入口状态为 found：读取上述 AGENTS.md，并按 Skill 恢复协作区上下文。'
  :status==='missing'
   ?'入口状态为 missing：先按 Skill 初始化独立协作区，再读取新建的 AGENTS.md；不得在数据根、安装目录或源码仓库初始化。'
   :'入口状态为 invalid：停止初始化和后续业务操作，报告指针无效；不要自动修复指针或另建协作区。'
 const text=[
 'StudyFlow Agent 会话启动',
 'Skill（'+(info.skill_kind==='installed'?'安装内':'仓库')+'）：'+info.skill_path,
 'CLI 绝对路径：'+(info.cli_path||'源码 CLI（见下方参数）'),
 'CLI 调用参数（JSON数组）：'+JSON.stringify(info.cli_argv),
 'StudyFlow 数据工作区：'+info.workspace,
 'Agent 协作区入口状态：'+status,
 'Agent 协作区入口文档：'+entryPath,
 '1. 先读取上述 Skill，并按其中的会话入口流程行动。',
 '2. 使用上述 CLI 参数和明确的数据工作区执行 version、capabilities、doctor；核对返回的工作区路径与状态，不要切换数据根。',
 '3. '+restoreInstruction,
 '4. 恢复后简要汇报核验结果、协作区当前状态，并依据工作区记录和 CLI 实际能力列出当前可做事项。若用户已给出具体任务，直接说明该任务并进入 Skill 对应流程，不要要求用户重新选择。',
 '具体业务流程以 Skill 为准；本启动指令不重复定义业务步骤。'
 ].join('\n')
 return {ready:true,reason:status==='invalid'?'协作区指针无效；复制内容将要求停止并报告。':'已确认 CLI、Skill 和工作区路径。',text}
}
