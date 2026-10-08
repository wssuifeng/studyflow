/**
 * 纯展示视图注册表。
 *
 * 展示包可以替换「容器语言」，但不能替换业务：这里登记的都是纯展示组件，
 * 它们只消费 props/slots/既有 UI 事件，不发业务请求、不持有保存状态。
 *
 * 查找按【主题ID】进行：同一位置（槽位）在不同主题下可以是不同容器，
 * 因此一个构建里能同时装载多个候选而不互相顶掉。
 *
 * 本文件是构建期生成物（候选 overlay 会覆写）；产品默认注册表为空，
 * 因此正式构建永远只包含产品自己的容器实现。
 */
import { generatedDisplayRegistry } from './display-registry.generated'

export type DisplayViewKey = 'shell' | 'titlebar' | 'navigation' | 'reading-shell' | 'teaching'

/** 取某主题在某槽位的容器实现；未注册时返回 undefined，调用方使用产品默认结构。 */
export function displayView(themeId: string, key: DisplayViewKey): unknown {
  return generatedDisplayRegistry.views?.[themeId]?.[key]
}

/** 该主题是否提供了任何一个展示容器（用于诊断与状态标注）。 */
export function themeHasDisplayPack(themeId: string): boolean {
  const pack = generatedDisplayRegistry.views?.[themeId]
  return !!pack && Object.keys(pack).length > 0
}

/** 本次构建装载的候选标识，仅用于状态显示。 */
export function displayPackCandidate(): string {
  return generatedDisplayRegistry.candidate ?? ''
}
