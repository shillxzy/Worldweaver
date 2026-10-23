import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { pagesApi } from '../api/pages'
import type { PageSummary, PageTemplateInfo } from '../api/types'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'
import { Modal } from './Ui'

/**
 * Link text to a page: pick an existing page of the world (search by title or alias, inflected
 * forms included) or create a new one with its own title and type. Mentions never create pages
 * automatically — creating is always this explicit second option.
 */
export default function LinkPicker({ worldId, initial = '', exclude, title, allowCreate = true, onPick, onClose }: {
  worldId: number; initial?: string; exclude?: number[]; title?: string; allowCreate?: boolean
  onPick: (page: Pick<PageSummary, 'id' | 'title'>) => void; onClose: () => void
}) {
  const { t, notify } = useApp()
  const selected = initial.trim()
  const [q, setQ] = useState(selected)
  const [results, setResults] = useState<PageSummary[]>([])
  const [active, setActive] = useState(0)
  const [newTitle, setNewTitle] = useState(selected)
  const [type, setType] = useState<PageTemplateInfo | null>(null)
  const templates = useAsync<PageTemplateInfo[]>(() => (allowCreate ? pagesApi.templates(worldId) : Promise.resolve([])), [worldId, allowCreate])
  const { busy, run } = useBusy()

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      pagesApi.lookup(worldId, q.trim(), controller.signal)
        .then((r) => { setResults(r.filter((p) => !exclude?.includes(p.id))); setActive(0) })
        .catch((err: unknown) => { if (!(err instanceof ApiError && err.isAborted)) notify(errorText(err), 'error') })
    }, 150)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [q, worldId, exclude, notify])

  const create = () => {
    const name = newTitle.trim()
    if (!name) return
    void run(async () => {
      try {
        onPick(await pagesApi.create(worldId, {
          title: name,
          ...(type?.builtin ? { template: type.key } : type?.id ? { user_template: type.id } : {}),
        }))
      } catch (err) { notify(errorText(err), 'error') }
    })
  }
  const types = (templates.data ?? []).filter((tpl) => tpl.key !== 'blank')

  return (
    <Modal title={title ?? t('enc.linkTitle')} onClose={onClose} wide={allowCreate}>
      {selected && <p className="link-selected">{t('link.selected')} <b>«{selected}»</b></p>}

      <section className="link-part">
        <h4>{t('link.existing')}</h4>
        <input className="field" autoFocus placeholder={t('enc.linkSearch')} value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)) }
            if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
            if (e.key === 'Enter' && results[active]) { e.preventDefault(); onPick(results[active]) }
          }} />
        <div className="picker-list">
          {results.map((p, i) => (
            <button key={p.id} className={'picker-item' + (i === active ? ' on' : '')} onMouseEnter={() => setActive(i)} onClick={() => onPick(p)}>
              <span className="tree-icon">{p.icon || '·'}</span>{p.title}
              {p.aliases.length > 0 && <small className="muted"> · {p.aliases.join(', ')}</small>}
            </button>
          ))}
          {results.length === 0 && <p className="muted">{t('link.noneFound')}</p>}
        </div>
      </section>

      {allowCreate && (
        <section className="link-part">
          <h4>{t('link.createNew')}</h4>
          <input className="field" placeholder={t('enc.titlePh')} value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); create() } }} />
          {selected && newTitle.trim() === selected && <small className="muted">{t('link.titleHint')}</small>}
          <div className="link-types">
            <button className={'type-chip' + (type === null ? ' on' : '')} onClick={() => setType(null)}>📄 {t('link.plainPage')}</button>
            {types.map((tpl) => (
              <button key={tpl.key} className={'type-chip' + (type?.key === tpl.key ? ' on' : '')} onClick={() => setType(tpl)}>
                {tpl.icon || '📄'} {tpl.name}
              </button>
            ))}
          </div>
          <button className="btn link-create" disabled={busy || !newTitle.trim()} onClick={create}>
            {busy ? t('ui.loading') : t('link.createAndLink')}
          </button>
        </section>
      )}
    </Modal>
  )
}
