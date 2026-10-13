<script setup lang="ts">
import {ref,onMounted,computed} from 'vue'
import {agentConnection,type InstallationInfo} from '../agentConnection'
import ThemeSettings from './ThemeSettings.vue'
import {activeTheme} from '../../../shared/themes'
import {invoke} from '@tauri-apps/api/core'
import {engineCall,isTauri} from '../../../shared/api'
import {notify,reportError,navigate,makeRequestKey} from '../../../shared/ui'
import {listToolWindows,prepareTools,releaseTools} from '../../courses/dock/toolWindows'
import {soundEnabled,soundVolume,setSoundEnabled,setSoundVolume,interactionFeedback} from '../../../shared/ui/interaction'
import {readingPreferences,applyReadingPreferences,resetReadingPreferences} from '../../../shared/ui/readingPreferences'
import type {DoctorData} from '../../../shared/api/contracts'
const props=defineProps<{doctor:DoctorData|null}>()
const installation=ref<InstallationInfo|null>(null),backupPath=ref(''),target=ref(''),busy=ref(false),restored=ref(''),result=ref(''),confirmed=ref(false)
const connectionLoading=ref(true),connectionError=ref(''),copyBusy=ref(false)
const connection=computed(()=>agentConnection(installation.value,props.doctor?.workspace.root))
async function refreshConnection(){
 connectionLoading.value=true;connectionError.value='';installation.value=null
 try {installation.value=await engineCall<InstallationInfo>('system.installation');if(!backupPath.value)backupPath.value=installation.value.workspace+'-backup.studyflow'}
 catch(cause){connectionError.value='接入信息读取失败，请检查连接后重试。';reportError(cause)}
 finally{connectionLoading.value=false}
}
onMounted(refreshConnection)
async function copyAgent(){
 if(connectionLoading.value||copyBusy.value||!connection.value.ready)return
 copyBusy.value=true
 try{await navigator.clipboard.writeText(connection.value.text);notify('Agent接入信息已复制。')}
 catch(cause){reportError(cause)}finally{copyBusy.value=false}
}
async function operate(method:string){
 if(busy.value)return;busy.value=true
 try{let data:any
 if(method==='workspace.restore'&&!confirmed.value){notify('请确认恢复到新目录。','info');return}
 const params=method==='workspace.restore'?{path:backupPath.value,target_root:target.value}:{path:backupPath.value}
 data=await engineCall(method,params);result.value=method==='workspace.export'?'备份已导出，建议验证后保留到其他磁盘。':method==='workspace.validate'?'校验通过 · '+data.file_count+'份文件 · '+data.schema_revision:'恢复完成，原工作区未替换。'
 if(method==='workspace.restore')restored.value=data.workspace_root
 notify(result.value)
 }catch(cause){reportError(cause)}finally{busy.value=false}
}
async function switchTo(){
 if(!restored.value||busy.value)return
 busy.value=true
 let requestId:string|undefined
 try{
  const prepared=await prepareTools('shutdown')
  requestId=prepared.requestId
  if(!prepared.ok){notify('独立工具窗口仍有未保存内容，请先处理后再切换工作区。','info');return}
  await invoke('close_tool_windows')
  await invoke('switch_workspace',{path:restored.value})
  window.location.hash='/today';window.location.reload()
 }catch(cause){reportError(cause)}finally{
  if(requestId)await releaseTools(requestId)
  busy.value=false
 }
}
</script>
<template>
 <div class="page-intro"><h2>工作区与阅读设置</h2><p class="muted">本地记录独立于安装目录；升级不会主动删除学习数据。</p></div>
 <section class="workspace-panel"><h3>当前数据位置</h3><p class="workspace-path">{{doctor?.workspace.root||installation?.workspace||'尚未连接'}}</p><p>连接 {{doctor?.healthy?'正常':'需要检查'}} · {{doctor?.database.driver}} · 材料采用课程组件，兼容旧文档</p><h4>外部Agent接入</h4><p class="workspace-path">{{installation?.cli_path||installation?.cli_argv?.join(' ')||'正在读取 CLI 路径…'}}</p><p class="muted small">{{installation?.source_cli?'开发模式使用当前 Python 解释器与仓库 Skill；安装版使用随附 CLI，不需要开发环境。':'安装版使用随附 CLI 与安装内 Skill，不需要源码或 Python 开发环境。'}}不自动修改系统 PATH。</p><p class="muted small" role="status">{{connectionError||connection.reason}}</p><button class="secondary-button" :disabled="connectionLoading||copyBusy||!connection.ready" @click="copyAgent">{{copyBusy?'复制中…':'复制Agent接入说明'}}</button><button v-if="!connectionLoading&&!connection.ready" class="text-button" @click="refreshConnection">重新读取</button></section>
 <section class="workspace-panel"><h3>备份与恢复</h3><label class="field-label">备份文件绝对路径<input v-model="backupPath" placeholder="例如 D:\Backup\StudyFlow.studyflow"/></label><div class="management-controls"><button class="secondary-button" :disabled="busy||!backupPath" @click="operate('workspace.export')">导出一致性备份</button><button class="secondary-button" :disabled="busy||!backupPath" @click="operate('workspace.validate')">验证备份</button></div><label class="field-label">恢复到新的工作区目录<input v-model="target" placeholder="不覆盖当前目录"/></label><label><input v-model="confirmed" type="checkbox"/> 已确认恢复目标；原目录及现有记录保留</label><div class="management-controls"><button class="secondary-button" :disabled="busy||!confirmed||!target" @click="operate('workspace.restore')">校验并恢复到新目录</button><button v-if="isTauri()&&restored" class="primary-button" :disabled="busy" @click="switchTo">切换到已恢复工作区</button></div><p v-if="result" role="status">{{result}}</p><p class="muted small">程序正在使用的目录不能热替换；后台CLI竞争时会明确拒绝维护。</p></section>
 <ThemeSettings/>
 <section class="workspace-panel"><h3>阅读偏好</h3><div class="reading-preferences"><label>字号 {{readingPreferences.font}}px<input v-model.number="readingPreferences.font" type="range" min="13" max="22" @input="applyReadingPreferences"/></label><label>行距 {{readingPreferences.lineHeight}}<input v-model.number="readingPreferences.lineHeight" type="range" min="1.5" max="2.3" step="0.05" @input="applyReadingPreferences"/></label><label>正文宽度 {{readingPreferences.width}}px<input v-model.number="readingPreferences.width" type="range" min="560" max="1100" step="20" @input="applyReadingPreferences"/></label></div><button class="text-button" @click="resetReadingPreferences">恢复默认阅读设置</button></section>
 <section class="workspace-panel feedback-preferences"><h3>操作反馈</h3><div class="sound-setting-row"><label class="sound-preference"><input type="checkbox" :checked="soundEnabled" @change="setSoundEnabled(($event.target as HTMLInputElement).checked);interactionFeedback('preview')"/> 启用轻柔操作音效</label><button class="text-button" :disabled="!soundEnabled||soundVolume===0||activeTheme.sound_profile==='muted'" @click="interactionFeedback('preview')">试听</button></div><label class="sound-volume-control">音效音量 <output>{{soundVolume}}%</output><input :value="soundVolume" type="range" min="0" max="100" step="1" :disabled="!soundEnabled" @input="setSoundVolume(Number(($event.target as HTMLInputElement).value))"/></label><p v-if="activeTheme.sound_profile==='muted'" class="muted small">当前主题采用静音反馈；切换到有音色的主题后，音量设置仍会保留。</p><p class="muted small">音效只提供即时操作反馈，不影响保存、提交和批改状态；状态同时用文字与视觉反馈表达。</p></section>
</template>
