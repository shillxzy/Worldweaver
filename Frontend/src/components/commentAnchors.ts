/**
 * Comments anchored to a passage of the chapter, Google Docs style, without touching the text.
 *
 * A comment stores its quote and which occurrence of it was selected. To show it, the quote is found
 * again in the rendered text (reading view or editor) and painted with the CSS Custom Highlight API —
 * no marks in the document, so commenters never change the chapter and edits never break the comment.
 * Matching ignores whitespace: a selection across paragraphs reads "a\n\nb" but the text nodes say "ab".
 */
import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'

/** The element that holds the chapter text inside ``root``: the reading view or the editor. */
export function textRoot(root: HTMLElement | null): HTMLElement | null {
  return root?.querySelector<HTMLElement>('.doc-view, .ProseMirror') ?? null
}

type Index = { chars: string; nodes: Text[]; offsets: number[] }

/** Every non-whitespace character of ``root`` with the text node and offset it came from. */
function indexText(root: HTMLElement): Index {
  const chars: string[] = []
  const nodes: Text[] = []
  const offsets: number[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
    const text = node.data
    for (let i = 0; i < text.length; i++) {
      if (/\s/.test(text[i])) continue
      chars.push(text[i]); nodes.push(node); offsets.push(i)
    }
  }
  return { chars: chars.join(''), nodes, offsets }
}

const squash = (text: string) => text.replace(/\s+/g, '')

/** Start positions (in the squashed text) of every occurrence of ``needle``. */
function occurrences(chars: string, needle: string): number[] {
  const found: number[] = []
  if (!needle) return found
  for (let at = chars.indexOf(needle); at !== -1; at = chars.indexOf(needle, at + 1)) found.push(at)
  return found
}

export type Anchor = { quote: string; occurrence: number }

/** The current selection inside ``root`` as an anchor (its quote and which occurrence it is), or null. */
export function selectionAnchor(root: HTMLElement | null): (Anchor & { rect: DOMRect }) | null {
  const text = textRoot(root)
  const selection = document.getSelection()
  if (!text || !selection || selection.isCollapsed || !selection.rangeCount) return null
  const range = selection.getRangeAt(0)
  if (!text.contains(range.commonAncestorContainer)) return null
  const quote = selection.toString().trim().slice(0, 500)
  if (!squash(quote)) return null
  // Squashed position where the selection starts: count non-whitespace characters before it.
  const before = document.createRange()
  before.selectNodeContents(text)
  before.setEnd(range.startContainer, range.startOffset)
  const start = squash(before.toString()).length
  const index = indexText(text)
  const occurrence = occurrences(index.chars, squash(quote)).filter((at) => at < start).length
  return { quote, occurrence, rect: range.getBoundingClientRect() }
}

/** DOM ranges of anchored comments that can still be found in the text (id → range). */
export function locate(root: HTMLElement | null, anchors: { id: number; quote: string; occurrence: number }[]): Map<number, Range> {
  const ranges = new Map<number, Range>()
  const text = textRoot(root)
  if (!text || !anchors.length) return ranges
  const index = indexText(text)
  for (const a of anchors) {
    const needle = squash(a.quote)
    const found = occurrences(index.chars, needle)
    if (!found.length) continue // the passage was rewritten: the comment stays in the panel only
    const at = found[Math.min(a.occurrence, found.length - 1)]
    const end = at + needle.length - 1
    const range = document.createRange()
    range.setStart(index.nodes[at], index.offsets[at])
    range.setEnd(index.nodes[end], index.offsets[end] + 1)
    ranges.set(a.id, range)
  }
  return ranges
}

type HighlightRegistry = { set: (name: string, h: unknown) => void; delete: (name: string) => void }
const registry = (): HighlightRegistry | null =>
  (typeof CSS !== 'undefined' && 'highlights' in CSS ? (CSS as unknown as { highlights: HighlightRegistry }).highlights : null)
const HighlightCtor = (globalThis as unknown as { Highlight?: new (...ranges: Range[]) => unknown }).Highlight

/** Paint the ranges (and the active one more strongly). Browsers without the API just show no highlight. */
export function paint(ranges: Range[], active: Range | null) {
  const highlights = registry()
  if (!highlights || !HighlightCtor) return
  highlights.set('ww-comment', new HighlightCtor(...ranges))
  if (active) highlights.set('ww-comment-active', new HighlightCtor(active)); else highlights.delete('ww-comment-active')
}

export function unpaint() {
  registry()?.delete('ww-comment')
  registry()?.delete('ww-comment-active')
}

/** Which anchored comment (if any) is under the point the user clicked. */
export function hit(ranges: Map<number, Range>, x: number, y: number): number | null {
  const doc = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
    caretRangeFromPoint?: (x: number, y: number) => Range | null
  }
  const position = doc.caretPositionFromPoint?.(x, y)
  const node = position?.offsetNode ?? doc.caretRangeFromPoint?.(x, y)?.startContainer
  const offset = position?.offset ?? doc.caretRangeFromPoint?.(x, y)?.startOffset ?? 0
  if (!node) return null
  for (const [id, range] of ranges) {
    try {
      if (range.isPointInRange(node, offset)) return id
    } catch { /* the node left the document */ }
  }
  return null
}

/** The live selection inside the chapter text (with where it is on screen), or null. */
export function useSelectionAnchor(root: RefObject<HTMLElement | null>, enabled: boolean, onAnchor?: (a: Anchor) => void) {
  const [selected, setSelected] = useState<(Anchor & { rect: DOMRect }) | null>(null)
  const callback = useRef(onAnchor)
  useEffect(() => { callback.current = onAnchor })
  useEffect(() => {
    if (!enabled) return
    const onChange = () => {
      const anchor = selectionAnchor(root.current)
      setSelected(anchor)
      if (anchor) callback.current?.(anchor)
    }
    document.addEventListener('selectionchange', onChange)
    window.addEventListener('scroll', onChange, true)  // keep the button next to the selection
    return () => { document.removeEventListener('selectionchange', onChange); window.removeEventListener('scroll', onChange, true) }
  }, [root, enabled])
  return enabled ? selected : null
}

/**
 * Highlight the anchored comments in the chapter text and keep the highlight in place while the text
 * changes (typing in the editor, switching to the reading view). Returns the current ranges by comment id.
 */
export function useCommentHighlights(root: RefObject<HTMLElement | null>, anchors: { id: number; quote: string; occurrence: number }[],
  focusId: number | null, key: string) {
  const ranges = useRef(new Map<number, Range>())
  const signature = JSON.stringify(anchors)
  useEffect(() => {
    const el = root.current
    if (!el) return
    const list = JSON.parse(signature) as typeof anchors
    let timer = 0
    const update = () => {
      ranges.current = locate(el, list)
      paint([...ranges.current.values()], focusId !== null ? ranges.current.get(focusId) ?? null : null)
    }
    update()
    const observer = new MutationObserver(() => { window.clearTimeout(timer); timer = window.setTimeout(update, 250) })
    observer.observe(el, { childList: true, subtree: true, characterData: true })
    return () => { observer.disconnect(); window.clearTimeout(timer); ranges.current = new Map(); unpaint() }
  }, [root, signature, focusId, key])
  return ranges
}
