/** Presentation only: never rewrites a frozen lesson or answer. */
export function learningContent(renderedHtml: string, title: string): string {
  const html = new DOMParser().parseFromString(renderedHtml, 'text/html')
  const heading = html.querySelector('h1')
  const normalized=(text:string)=>text.replace(/^\d+[｜|·.、\s]+/,'').replace(/[\s、，,]/g,'')
  if (heading?.textContent && normalized(heading.textContent) === normalized(title)) heading.remove()
  // Old authored lessons mixed scheduling/source instructions into the leading paragraph.
  // Hide only explicit leading metadata, not general instructions inside teaching content.
  for (const node of Array.from(html.body.children)) {
    if (node.tagName !== 'P' || !/^(建议用时|教材定位|本地PDF|第一天无需设计真正的通信系统)[：:\s。]/.test(node.textContent?.trim() || '')) break
    node.remove()
  }
  const walker = html.createTreeWalker(html.body, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) {
    const node = walker.currentNode
    if (node.parentElement?.closest('code, pre')) continue
    node.textContent = node.textContent?.replace(/&#(?:x20|32);/gi, ' ') || ''
  }
  return html.body.innerHTML
}
