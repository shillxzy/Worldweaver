import type { CSSProperties, ReactNode } from 'react'
import type { DocNode } from '../api/types'

type Mark = { type: string; attrs?: { href?: string } }
type Node = { type: string; text?: string; marks?: Mark[]; attrs?: Record<string, unknown>; content?: Node[] }

/**
 * Read-only rendering of a stored document (no editor needed). Only the node and mark types the
 * server accepts are rendered; text is always rendered as text, never as HTML.
 */
export default function DocView({ doc, onPageLink, className = '' }: {
  doc: DocNode; onPageLink?: (pageId: number) => void; className?: string
}) {
  const root = doc as unknown as Node
  return <div className={'doc-view ' + className}>{(root.content ?? []).map((n, i) => block(n, i, onPageLink))}</div>
}

function align(node: Node): CSSProperties | undefined {
  const a = node.attrs?.textAlign
  return typeof a === 'string' ? { textAlign: a as CSSProperties['textAlign'] } : undefined
}

function block(node: Node, key: number, onPageLink?: (id: number) => void): ReactNode {
  const kids = () => (node.content ?? []).map((n, i) => block(n, i, onPageLink))
  const inline = () => (node.content ?? []).map((n, i) => text(n, i, onPageLink))
  switch (node.type) {
    case 'paragraph': return <p key={key} style={align(node)}>{inline()}</p>
    case 'heading': {
      const level = node.attrs?.level === 1 ? 1 : node.attrs?.level === 3 ? 3 : 2
      const Tag = (`h${level}`) as 'h1' | 'h2' | 'h3'
      return <Tag key={key} style={align(node)}>{inline()}</Tag>
    }
    case 'blockquote': return <blockquote key={key}>{kids()}</blockquote>
    case 'bulletList': return <ul key={key}>{kids()}</ul>
    case 'orderedList': return <ol key={key} start={typeof node.attrs?.start === 'number' ? node.attrs.start : undefined}>{kids()}</ol>
    case 'listItem': return <li key={key}>{kids()}</li>
    case 'horizontalRule': return <hr key={key} />
    default: return null
  }
}

function text(node: Node, key: number, onPageLink?: (id: number) => void): ReactNode {
  if (node.type === 'hardBreak') return <br key={key} />
  if (node.type !== 'text' || !node.text) return null
  let out: ReactNode = node.text
  for (const mark of node.marks ?? []) {
    if (mark.type === 'bold') out = <strong>{out}</strong>
    else if (mark.type === 'italic') out = <em>{out}</em>
    else if (mark.type === 'underline') out = <u>{out}</u>
    else if (mark.type === 'strike') out = <s>{out}</s>
    else if (mark.type === 'link') {
      const href = mark.attrs?.href ?? ''
      const page = /^page:(\d+)$/.exec(href)
      if (page && onPageLink) {
        const id = Number(page[1])
        out = <a href="#" className="page-ref" onClick={(e) => { e.preventDefault(); onPageLink(id) }}>{out}</a>
      } else if (/^(https?:|mailto:)/.test(href)) {
        out = <a href={href} target="_blank" rel="noopener noreferrer nofollow">{out}</a>
      }
    }
  }
  return <span key={key}>{out}</span>
}
