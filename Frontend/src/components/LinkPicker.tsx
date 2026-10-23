import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { pagesApi } from '../api/pages'
import type { PageSummary } from '../api/types'
import { useApp } from '../settings-context'
import { Modal } from './Ui'

/**
 * Choose an existing page of the world (search by title or alias). Creating a new page is an
 * explicit, separate option — mentions never create pages automatically.
 */
export default function LinkPicker({ worldId, initial = '', exclude, title, allowCreate = true, onPick, onClose }: {
  worldId: number; initial?: string; exclude?: number[]; title?: string; allowCreate?: boolean
  onPick: (page: Pick<PageSummary, 'id' | 'title'>) => void; onClose: () => void
}) {
  const { t, notify } = useApp()
  const [q, setQ] = useState(initial)
  const [results, setResults] = useState<PageSummary[]>([])
  const [active, setActive] = useState(0)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      pagesApi.lookup(worldId, q.trim(), controller.signal)
        .then((r) => { setResults(r.filter((p) => !exclude?.includes(p.id))); setActive(0) })
        .catch((err: unknown) => { if (!(err instanceof ApiError && err.isAborted)) notify(String((err as Error).message), 'error') })
    }, 150)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [q, worldId, exclude, notify])

  const create = () => {
    if (!q.trim() || creating) return
    setCreating(true)
    pagesApi.create(worldId, { title: q.trim() })
      .then((page) => onPick(page))
      .catch((err: unknown) => notify(err instanceof ApiError ? err.message : String(err), 'error'))
      .finally(() => setCreating(false))
  }

  return (
    <Modal title={title ?? t('enc.linkTitle')} onClose={onClose}>
      <input className="field" autoFocus placeholder={t('enc.linkSearch')} value={q} onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          if (e.key === 'Enter') { e.preventDefault(); if (results[active]) onPick(results[active]); else if (allowCreate) create() }
        }} />
      <div className="picker-list">
        {results.map((p, i) => (
          <button key={p.id} className={'picker-item' + (i === active ? ' on' : '')} onMouseEnter={() => setActive(i)} onClick={() => onPick(p)}>
            <span className="tree-icon">{p.icon || '·'}</span>{p.title}
            {p.aliases.length > 0 && <small className="muted"> · {p.aliases.join(', ')}</small>}
          </button>
        ))}
        {results.length === 0 && <p className="muted">{t('ui.nothing')}</p>}
        {allowCreate && q.trim() && !results.some((p) => p.title.toLocaleLowerCase('uk') === q.trim().toLocaleLowerCase('uk')) && (
          <button className="picker-item create" disabled={creating} onClick={create}>+ {t('enc.createNamed')} «{q.trim()}»</button>
        )}
      </div>
    </Modal>
  )
}
