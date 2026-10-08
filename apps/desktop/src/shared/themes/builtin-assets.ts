/** Formal product assets are independent of the replaceable candidate overlay registry. */
import readingBook from './assets/white-violet-book.png'
import quietEdge from './assets/white-violet-edge.svg'
import sequenceLandscape from './assets/sequence-light-landscape.png'
import sequenceOrigami from './assets/sequence-light-origami.png'

export const builtinDisplayAssets: Record<string, () => string | null> = {
  'sequence-light::sidebar-landscape': () => sequenceLandscape,
  'sequence-light::sidebar-origami': () => sequenceOrigami,
  'white-violet::reading-book': () => readingBook,
  'white-violet::quiet-edge': () => quietEdge,
}
