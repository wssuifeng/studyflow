<script setup lang="ts">
/**
 * 展示槽位：把「哪个纯展示容器来实现这个位置」交给构建期注册表决定。
 *
 * · 产品默认注册表为空 → 直接渲染产品自带容器（fallback）或默认插槽内容；
 * · 候选 overlay 构建在注册表里登记自己的纯展示 Vue → 同一位置换成候选容器；
 * · 候选容器只消费这里透传的 props / slots / 既有 UI 事件，无法触及业务状态。
 *
 * 组件实例不因主题切换而重挂：只有解析结果变化时才换实现，
 * 因此输入框、IME、选区、滚动锚点与未确认请求的载荷都不会被主题切换打断。
 */
import { computed, useSlots, type Component } from 'vue'
import { displayView, type DisplayViewKey } from '../themes/view-registry'
import { displayThemeId } from '../themes/display-loader'

const props = defineProps<{
  slot: DisplayViewKey
  /** 产品默认容器（组件或原生标签名，如 'div'）；与默认插槽二选一。 */
  fallback?: Component | string
  /** 透传给容器实现的展示 props（只读数据，不含业务状态所有者）。 */
  viewProps?: Record<string, unknown>
}>()
const slots = useSlots()
// 按当前主题解析：切换主题只换容器实现，不重挂整棵业务组件树。
const resolved = computed<Component | string | null>(() => (displayView(displayThemeId.value, props.slot) as Component | undefined) ?? props.fallback ?? null)
const passthrough = computed(() => Object.keys(slots))
// Native fallback elements do not consume named slots. Render those slots as
// real children while custom display components still receive named slots.
const nativeFallback = computed(() => typeof resolved.value === 'string')
</script>
<template>
  <component :is="resolved" v-if="resolved && !nativeFallback" v-bind="viewProps">
    <template v-for="name in passthrough" :key="name" #[name]="slotProps">
      <slot :name="name" v-bind="slotProps ?? {}" />
    </template>
  </component>
  <component :is="resolved" v-else-if="resolved" v-bind="viewProps">
    <template v-for="name in passthrough" :key="name">
      <slot :name="name" />
    </template>
  </component>
  <slot v-else/>
</template>
