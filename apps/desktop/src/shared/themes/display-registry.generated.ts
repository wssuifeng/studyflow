/**
 * 展示注册表（构建期生成位）。
 *
 * 产品构建使用这份空注册表：正式包只包含产品自己的容器与样式。
 * 候选 overlay 构建（scripts/build-overlay.mjs）会在隔离构建树里**覆写本文件**，
 * 静态 import 候选的 CSS / 纯展示 Vue / 本地素材，因此：
 *   · 展示包是 Vite 真实编译进唯一 Vue 的，不是运行期改 dist 或猜路径注入；
 *   · 干净重构建后依然装载（注册表本身就是源码的一部分）；
 *   · 候选无法借注册表触碰 shared/api、业务 composable 或 Core。
 *
 * 键名约定：
 *   · views 按【主题ID】分组，因为同一位置（槽位）在不同主题下需要不同容器；
 *   · assets 用 `${themeId}::${assetKey}`，与主题 JSON 里声明的素材标识对应。
 * 一个构建里可以同时装载多个候选（用于同一预览内切换比较）：
 * 皮肤样式都以 [data-overlay-name] 作用域化，互不串扰。
 */
import type { DisplayViewKey } from './view-registry'

export type GeneratedDisplayRegistry = {
  /** 该注册表包含的候选标识（产品构建为空串）。 */
  candidate: string
  /** 主题ID → 槽位 → 纯展示容器组件。 */
  views: Record<string, Partial<Record<DisplayViewKey, unknown>>>
  /** 惰性素材加载器：只有真正用到时才解析 URL，缺图返回 null 由调用方回退。 */
  assets: Record<string, () => string | null>
}

export const generatedDisplayRegistry: GeneratedDisplayRegistry = {
  candidate: '',
  views: {},
  assets: {},
}
