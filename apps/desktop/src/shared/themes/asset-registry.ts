/**
 * 本地素材注册表。
 *
 * 主题 JSON 只能声明「素材标识 + 用途 + 比例 + 安全区 + 回退色」，
 * 永远不能给路径。真正的文件由构建期生成的注册表（display-registry.generated.ts）
 * 静态 import 进来，Vite 在打包时解析为带 hash 的本地资源。
 *
 * 因此：JSON 里不可能出现 ../ 逃逸、绝对路径或网络地址；缺图时返回 null，
 * 由调用方走纯色回退，学习流程不受影响。
 */
import { generatedDisplayRegistry } from './display-registry.generated'
import { builtinDisplayAssets } from './builtin-assets'

export type DisplayAssetRef = { url: string; fallback: string; aspectRatio: string; safeArea: number; role: string }

const cache = new Map<string, string | null>()

function resolve(key: string): string | null {
  if (cache.has(key)) return cache.get(key) ?? null
  let url: string | null = null
  try {
    const loader = generatedDisplayRegistry.assets?.[key] ?? builtinDisplayAssets[key]
    url = typeof loader === 'function' ? loader() : null
  } catch {
    // 素材加载失败只影响装饰：回退为纯色，绝不阻塞正文。
    url = null
  }
  cache.set(key, url)
  return url
}

/** 素材是否真实可用（用于「无图模式」与缺图回退判定）。 */
export function hasDisplayAsset(key: string): boolean {
  return resolve(key) !== null
}

/**
 * 解析主题声明的素材。
 * @param intensity 用户图像强度偏好；none 直接返回 null（不回退成网络图，也不报错）。
 */
export function resolveDisplayAsset(
  themeId: string,
  asset: { key: string; role: string; aspect_ratio: string; safe_area: number; fallback: string },
  intensity: 'full' | 'subtle' | 'none' = 'full',
): DisplayAssetRef | null {
  if (intensity === 'none') return null
  const url = resolve(`${themeId}::${asset.key}`)
  if (!url) return null
  return { url, fallback: asset.fallback, aspectRatio: asset.aspect_ratio, safeArea: asset.safe_area, role: asset.role }
}
