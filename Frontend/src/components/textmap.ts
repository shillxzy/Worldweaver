import type { Node as PMNode } from '@tiptap/pm/model'

/**
 * Plain-text view of a ProseMirror document with a mapping back to document positions.
 * Text blocks are joined with "\n\n"; hard breaks become "\n". Inside a text block every
 * character (and every hard break) occupies exactly one position, so mapping is linear.
 */
export type TextMap = { text: string; blocks: { pos: number; start: number; length: number }[] }

export function buildTextMap(doc: PMNode): TextMap {
  const blocks: TextMap['blocks'] = []
  const parts: string[] = []
  let offset = 0
  doc.descendants((node, pos) => {
    if (!node.isTextblock) return true
    const text = node.textBetween(0, node.content.size, undefined, '\n')
    if (parts.length) offset += 2
    blocks.push({ pos, start: offset, length: text.length })
    parts.push(text)
    offset += text.length
    return false
  })
  return { text: parts.join('\n\n'), blocks }
}

/** Convert a plain-text offset to a document position (null if it falls between blocks). */
export function offsetToPos(map: TextMap, offset: number): number | null {
  for (const block of map.blocks) {
    if (offset >= block.start && offset <= block.start + block.length) return block.pos + 1 + (offset - block.start)
  }
  return null
}

/** Window of text around a document position, used for quick checks of the edited fragment. */
export function fragmentAround(map: TextMap, pos: number, radius = 2): { text: string; offset: number } {
  const index = Math.max(0, map.blocks.findIndex((b) => pos >= b.pos && pos <= b.pos + b.length + 1))
  const from = map.blocks[Math.max(0, index - radius)]
  const to = map.blocks[Math.min(map.blocks.length - 1, index + radius)]
  if (!from || !to) return { text: '', offset: 0 }
  return { text: map.text.slice(from.start, to.start + to.length), offset: from.start }
}
