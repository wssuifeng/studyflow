/** Formal product assets are independent of the replaceable candidate overlay registry. */
import readingBook from './assets/white-violet-book.png'
import quietEdge from './assets/white-violet-edge.svg'
import sequenceLandscape from './assets/sequence-light-landscape.png'
import sequenceOrigami from './assets/sequence-light-origami.png'
import cinnabarGrain from './assets/cinnabar-paper-grain.svg'
import cinnabarMeander from './assets/cinnabar-paper-meander.svg'
import cinnabarSeal from './assets/cinnabar-paper-seal.svg'

export const builtinDisplayAssets: Record<string, () => string | null> = {
  'sequence-light::sidebar-landscape': () => sequenceLandscape,
  'sequence-light::sidebar-origami': () => sequenceOrigami,
  'white-violet::reading-book': () => readingBook,
  'white-violet::quiet-edge': () => quietEdge,
  // 内置主题「国风朱红」经设置页选中后使用同一资产解析入口；未选中时不会被加载。
  'cinnabar-paper::paper-grain': () => cinnabarGrain,
  'cinnabar-paper::desk-meander': () => cinnabarMeander,
  'cinnabar-paper::study-seal': () => cinnabarSeal,
}
