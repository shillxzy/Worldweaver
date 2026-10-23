import { useMemo, useState } from 'react'
import type { DragEvent } from 'react'
import type { PageSummary } from '../api/types'
import { useAccess } from '../access'
import { useApp } from '../settings-context'

type Props = {
  pages: PageSummary[]
  currentId?: number
  storageKey: string
  onOpen: (id: number) => void
  onCreateChild: (parentId: number | null) => void
  onMove: (id: number, parent: number | null, position?: number) => void
}

function readExpanded(key: string): Set<number> {
  try {
    return new Set((JSON.parse(localStorage.getItem(key) ?? '[]') as number[]).filter(Number.isInteger))
  } catch {
    return new Set()
  }
}

/** Page hierarchy of a world: expand/collapse, drag a page onto another to nest it, "+" to add a subpage. */
export default function PageTree({ pages, currentId, storageKey, onOpen, onCreateChild, onMove }: Props) {
  const { t } = useApp()
  const [expanded, setExpanded] = useState<Set<number>>(() => readExpanded(storageKey))
  const [dragging, setDragging] = useState<number | null>(null)
  const [over, setOver] = useState<number | 'root' | null>(null)
  const [menu, setMenu] = useState<number | null>(null)

  const byParent = useMemo(() => {
    const map = new Map<number | null, PageSummary[]>()
    for (const p of pages) {
      const key = p.parent ?? null
      map.set(key, [...(map.get(key) ?? []), p])
    }
    for (const list of map.values()) list.sort((a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title, 'uk'))
    return map
  }, [pages])

  // Ancestors of the open page are always shown expanded.
  const ancestors = useMemo(() => {
    const byId = new Map(pages.map((p) => [p.id, p]))
    const set = new Set<number>()
    let cur = currentId ? byId.get(currentId) : undefined
    while (cur?.parent) { set.add(cur.parent); cur = byId.get(cur.parent) }
    return set
  }, [pages, currentId])

  const toggle = (id: number) => {
    const next = new Set(expanded)
    if (next.has(id)) next.delete(id); else next.add(id)
    setExpanded(next)
    try { localStorage.setItem(storageKey, JSON.stringify([...next])) } catch { /* optional convenience */ }
  }

  const isDescendant = (id: number, of: number): boolean => {
    let cur = pages.find((p) => p.id === id)
    while (cur?.parent) {
      if (cur.parent === of) return true
      cur = pages.find((p) => p.id === cur!.parent)
    }
    return false
  }

  const drop = (target: number | 'root') => (e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const id = dragging
    setDragging(null)
    setOver(null)
    if (id === null || id === target) return
    if (target !== 'root' && isDescendant(target, id)) return
    onMove(id, target === 'root' ? null : target)
    if (target !== 'root' && !expanded.has(target)) toggle(target)
  }

  const shift = (page: PageSummary, delta: number) => {
    const siblings = byParent.get(page.parent ?? null) ?? []
    const index = siblings.findIndex((p) => p.id === page.id)
    const target = index + delta
    if (target >= 0 && target < siblings.length) onMove(page.id, page.parent, target)
    setMenu(null)
  }

  const { edit } = useAccess()
  const render = (parent: number | null, depth: number) => (byParent.get(parent) ?? []).map((page) => {
    const children = byParent.get(page.id) ?? []
    const open = expanded.has(page.id) || ancestors.has(page.id)
    return (
      <div key={page.id} className="tree-branch">
        <div
          className={'tree-row' + (page.id === currentId ? ' on' : '') + (over === page.id ? ' drop' : '')}
          style={{ paddingLeft: 4 + depth * 14 }}
          draggable={edit} onDragStart={(e) => { setDragging(page.id); e.dataTransfer.effectAllowed = 'move' }}
          onDragEnd={() => { setDragging(null); setOver(null) }}
          onDragOver={(e) => { if (dragging !== null && dragging !== page.id) { e.preventDefault(); setOver(page.id) } }}
          onDragLeave={() => setOver((o) => (o === page.id ? null : o))}
          onDrop={drop(page.id)}
        >
          <button className="tree-toggle" onClick={() => toggle(page.id)} aria-label={open ? t('enc.collapse') : t('enc.expand')}
            style={{ visibility: children.length ? 'visible' : 'hidden' }}>{open ? '▾' : '▸'}</button>
          <button className="tree-title" onClick={() => onOpen(page.id)} title={page.title}>
            <span className="tree-icon">{page.icon || '·'}</span>{page.title}
          </button>
          {edit && (
            <span className="tree-acts">
              <button className="icon-btn" onClick={() => onCreateChild(page.id)} aria-label={t('enc.addSubpage')} title={t('enc.addSubpage')}>+</button>
              <button className="icon-btn" onClick={() => setMenu(menu === page.id ? null : page.id)} aria-label={t('enc.more')}>⋯</button>
            </span>
          )}
          {menu === page.id && (
            <div className="menu tree-menu" onMouseLeave={() => setMenu(null)}>
              <button onClick={() => shift(page, -1)}>{t('enc.moveUp')}</button>
              <button onClick={() => shift(page, 1)}>{t('enc.moveDown')}</button>
              {page.parent !== null && <button onClick={() => { onMove(page.id, null); setMenu(null) }}>{t('enc.toRoot')}</button>}
            </div>
          )}
        </div>
        {open && children.length > 0 && render(page.id, depth + 1)}
      </div>
    )
  })

  return (
    <nav className="page-tree" aria-label={t('enc.tree')}>
      {pages.length === 0 && <p className="muted">{t('enc.treeEmpty')}</p>}
      {render(null, 0)}
      {edit && (
        <div className={'tree-root-drop' + (over === 'root' ? ' drop' : '')}
          onDragOver={(e) => { if (dragging !== null) { e.preventDefault(); setOver('root') } }}
          onDragLeave={() => setOver((o) => (o === 'root' ? null : o))} onDrop={drop('root')}>
          {dragging !== null ? t('enc.dropRoot') : <button className="link" onClick={() => onCreateChild(null)}>+ {t('enc.newPage')}</button>}
        </div>
      )}
    </nav>
  )
}
