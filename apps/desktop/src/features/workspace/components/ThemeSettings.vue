<script setup lang="ts">
import { ref, computed } from 'vue'
import { activeTheme, availableThemes, themeNotice, selectTheme, importTheme, exportTheme, removeTheme, resetTheme, setDisplayOptions, imageIntensity, typographyPreference } from '../../../shared/themes'
import { MAX_THEME_BYTES, MAX_CUSTOM_THEMES } from '../../../shared/themes/contract'
import type { ThemeResult } from '../../../shared/themes/controller'
import { notify } from '../../../shared/ui'
const input = ref<HTMLInputElement | null>(null), importing = ref(false), message = ref(''), failed = ref(false), removal = ref('')
const custom = computed(() => availableThemes.value.find(item => item.theme.id === activeTheme.value.id)?.source === 'custom')
const scaleChoice = computed(() => typographyPreference.value.scale === 'auto' ? 'auto' : String(typographyPreference.value.scale))
const lineChoice = computed(() => typographyPreference.value.lineHeight === 'auto' ? 'auto' : String(typographyPreference.value.lineHeight))
const SCALES = [{ id: 'auto', label: '跟随主题' }, { id: '0.95', label: '略紧 0.95' }, { id: '1', label: '标准 1.0' }, { id: '1.08', label: '略大 1.08' }]
const LINES = [{ id: 'auto', label: '跟随主题' }, { id: '1.65', label: '紧凑 1.65' }, { id: '1.85', label: '标准 1.85' }, { id: '2.05', label: '宽松 2.05' }]
const IMAGES = [{ id: 'full', label: '使用主题素材' }, { id: 'subtle', label: '弱化素材' }, { id: 'none', label: '无图模式' }]
function report(result: ThemeResult, success: string) {
  failed.value = !result.ok
  message.value = result.ok ? success : result.error
  if (result.ok) notify(success, 'info')
}
function choose(id: string) { removal.value = ''; report(selectTheme(id), '主题已切换，学习内容保持不变。') }
function chooseScale(value: string) { report(setDisplayOptions({ typography: { scale: value === 'auto' ? 'auto' : Number(value), lineHeight: typographyPreference.value.lineHeight } }), '正文字号标度已更新。') }
function chooseLine(value: string) { report(setDisplayOptions({ typography: { scale: typographyPreference.value.scale, lineHeight: value === 'auto' ? 'auto' : Number(value) } }), '行距已更新。') }
function chooseImage(value: 'full' | 'subtle' | 'none') { report(setDisplayOptions({ image_intensity: value }), value === 'none' ? '已切换为无图模式，装饰素材不再加载。' : '图像强度已更新。') }
async function readFile(event: Event) {
  const el = event.target as HTMLInputElement, file = el.files?.[0]
  if (!file || importing.value) return
  importing.value = true
  try {
    if (file.size > MAX_THEME_BYTES) { report({ ok: false, error: '主题文件最多32KB，请选择完整的主题JSON配置。' }, ''); return }
    report(importTheme(await file.text()), '主题已导入并应用。')
  } catch { report({ ok: false, error: '无法读取此文件，请重新选择主题JSON。' }, '') }
  finally { importing.value = false; el.value = '' }
}
function download() {
  const url = URL.createObjectURL(new Blob([exportTheme()], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url; link.download = activeTheme.value.id + '.theme.json'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  message.value = '已导出当前主题配置。内置主题另存时请先修改ID，再导入为自定义主题。'; failed.value = false
}
function remove() { const name = activeTheme.value.name; report(removeTheme(removal.value), `已移除“${name}”，学习记录保持不变。`); removal.value = '' }
</script>
<template>
  <section class="workspace-panel theme-settings" aria-labelledby="theme-settings-heading">
    <header class="theme-settings-heading"><div><h3 id="theme-settings-heading">外观主题</h3><p class="muted small">同一套课程与工具，换一种舒服的阅读环境。</p></div><span class="theme-current-label">当前 · {{ activeTheme.name }}</span></header>
    <div class="theme-options" role="group" aria-label="选择外观主题">
      <button v-for="item in availableThemes" :key="item.theme.id" type="button" class="theme-option" :class="{ selected: activeTheme.id === item.theme.id }" :aria-pressed="activeTheme.id === item.theme.id" @click="choose(item.theme.id)">
        <span class="theme-preview" aria-hidden="true" :style="{ '--preview-canvas': item.theme.tokens['surface.canvas'], '--preview-panel': item.theme.tokens['surface.panel'], '--preview-raised': item.theme.tokens['surface.raised'], '--preview-accent': item.theme.tokens['accent.primary'], '--preview-text': item.theme.tokens['text.primary'], '--preview-border': item.theme.tokens['border.subtle'] }">
          <span class="theme-preview-nav"><i/><i/><i/></span><span class="theme-preview-page"><i class="preview-title"/><i/><i/><span class="preview-callout"><i/></span></span><span class="theme-preview-tools"><i/><i/></span>
        </span>
        <span class="theme-option-heading"><strong>{{ item.theme.name }}</strong><span class="theme-choice-indicator">{{ activeTheme.id === item.theme.id ? '✓ 已选择' : item.theme.appearance === 'dark' ? '深色' : '浅色' }}</span></span>
        <span class="theme-option-description">{{ item.theme.description }}</span><span v-if="item.source === 'custom'" class="theme-custom-label">本地导入</span>
      </button>
    </div>
    <div class="theme-display-options">
      <div class="theme-option-row" role="group" aria-label="正文字号标度">
        <span class="theme-option-label">字号标度</span>
        <div class="theme-chip-row"><button v-for="item in SCALES" :key="item.id" type="button" class="theme-chip" :class="{ selected: scaleChoice === item.id }" :aria-pressed="scaleChoice === item.id" @click="chooseScale(item.id)">{{ item.label }}</button></div>
      </div>
      <div class="theme-option-row" role="group" aria-label="正文行距">
        <span class="theme-option-label">正文行距</span>
        <div class="theme-chip-row"><button v-for="item in LINES" :key="item.id" type="button" class="theme-chip" :class="{ selected: lineChoice === item.id }" :aria-pressed="lineChoice === item.id" @click="chooseLine(item.id)">{{ item.label }}</button></div>
      </div>
      <div class="theme-option-row" role="group" aria-label="图像强度">
        <span class="theme-option-label">图像强度</span>
        <div class="theme-chip-row"><button v-for="item in IMAGES" :key="item.id" type="button" class="theme-chip" :class="{ selected: imageIntensity === item.id }" :aria-pressed="imageIntensity === item.id" @click="chooseImage(item.id as 'full' | 'subtle' | 'none')">{{ item.label }}</button></div>
      </div>
      <p class="muted small theme-display-hint">排版与图像强度与主题分开保存：切换主题不会重置你的选择；装饰素材缺失或选择无图模式时，正文仍使用纯色表面。</p>
    </div>
    <div class="theme-config-actions"><button class="secondary-button" :disabled="importing" @click="input?.click()">{{ importing ? '正在读取…' : '导入主题JSON' }}</button><button class="secondary-button" @click="download">导出当前主题</button><button class="text-button" @click="report(resetTheme(), '已恢复默认主题，学习内容保持不变。')">恢复默认主题</button><button v-if="custom" class="text-button" @click="removal = activeTheme.id">移除此自定义主题</button></div>
    <input ref="input" type="file" accept=".json,application/json" class="visually-hidden" tabindex="-1" aria-label="导入主题配置文件" @change="readFile"/>
    <div v-if="removal" class="theme-remove-confirm" role="group" aria-label="确认移除主题"><span>仅移除这份外观配置，不影响学习记录。确认移除？</span><button class="secondary-button" @click="remove">确认移除</button><button class="text-button" @click="removal = ''">取消</button></div>
    <p v-if="message" class="theme-action-message small" :class="{ error: failed }" :role="failed ? 'alert' : 'status'">{{ message }}</p>
    <p v-if="themeNotice" class="theme-storage-notice small" role="status">{{ themeNotice }}</p>
    <p class="muted small theme-config-hint">切换不重载课程，不重置字号、行距和音效开关。仅接受本地色板及展示预设配置，最多 {{ MAX_CUSTOM_THEMES }} 份自定义主题；同ID导入会更新该自定义主题。</p>
  </section>
</template>
