import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { ApiError } from '../api/client'
import { pagesApi } from '../api/pages'
import type { Book, PageSummary, PageTemplateInfo } from '../api/types'
import PageTree from '../components/PageTree'
import PageView from '../components/PageView'
import { PAGE_TYPES } from '../data/projects'
import { Empty, ErrorState, Loading, Modal } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { navigate, pagePath, projectPath } from '../router'
import { useAccess } from '../access'
import { useApp } from '../settings-context'

const RECENT_LIMIT = 8

function readRecent(key: string): number[] {
  try { return (JSON.parse(localStorage.getItem(key) ?? '[]') as number[]).filter(Number.isInteger) } catch { return [] }
}

/**
 * The world's encyclopedia: a tree of free-form pages. `pageId` opens a page in the main area
 * (its own URL); without it the home view offers search, type filters and recent pages.
 * `focus=character:ID` (search results, analysis evidence) resolves to the record's page.
 */
export default function Encyclopedia({ book, focus, pageId }: { book: Book; focus?: string; pageId?: number }) {
  const { t, notify } = useApp()
  const worldId = book.world
  const recentKey = `ww-recent-pages-${worldId}`
  const pagesState = useAsync<PageSummary[]>((signal) => pagesApi.list(worldId, {}, signal), [worldId])
  const [creating, setCreating] = useState<{ parent: number | null } | null>(null)
  const [treeHidden, setTreeHidden] = useState(() => {
    try { return localStorage.getItem('ww-tree-hidden') === '1' } catch { return false }
  })
  const pages = useMemo(() => pagesState.data ?? [], [pagesState.data])
  const open = (id: number) => navigate(pagePath(book.id, id))

  // Resolve legacy/entity focus links (e.g. from search or analysis evidence) to the page URL.
  useEffect(() => {
    if (!focus || pageId) return
    const [type, raw] = focus.split(':')
    const id = Number(raw)
    if (!Number.isInteger(id)) return
    const target = type === 'page' ? Promise.resolve({ id }) : pagesApi.byEntity(worldId, type, id)
    target.then((p) => navigate(pagePath(book.id, p.id))).catch((err) => notify(errorText(err), 'error'))
  }, [focus, pageId, worldId, book.id, notify])

  // Remember recently opened pages (per browser, a convenience only).
  useEffect(() => {
    if (!pageId) return
    try {
      const next = [pageId, ...readRecent(recentKey).filter((x) => x !== pageId)].slice(0, RECENT_LIMIT)
      localStorage.setItem(recentKey, JSON.stringify(next))
    } catch { /* storage unavailable */ }
  }, [pageId, recentKey])

  const upsert = (p: PageSummary) => pagesState.setData((prev) => {
    const list = prev ?? []
    return list.some((x) => x.id === p.id) ? list.map((x) => (x.id === p.id ? { ...x, ...pickSummary(p) } : x)) : [...list, pickSummary(p)]
  })

  const move = (id: number, parent: number | null, position?: number) => {
    pagesApi.move(worldId, id, parent, position).then(() => pagesState.reload()).catch((err) => notify(errorText(err), 'error'))
  }

  const toggleTree = () => {
    const next = !treeHidden
    setTreeHidden(next)
    try { localStorage.setItem('ww-tree-hidden', next ? '1' : '') } catch { /* optional convenience */ }
  }

  return (
    // The home view already lists every page, so the tree is shown only next to an open page.
    <div className={'enc-layout' + (!pageId ? ' no-tree' : treeHidden ? ' tree-hidden' : '')} style={{ '--book-accent': book.accent } as CSSProperties}>
      {treeHidden && pageId && (
        <button className="tree-show" onClick={toggleTree} title={t('enc.showTree')} aria-label={t('enc.showTree')}>☰</button>
      )}
      <aside className="enc-side" hidden={treeHidden || !pageId}>
        <div className="enc-side-head">
          <button className="link enc-home" onClick={() => navigate(projectPath(book.id, 'encyclopedia'))}>{t('s.encyclopedia')}</button>
          <button className="icon-btn" onClick={toggleTree} title={t('enc.hideTree')} aria-label={t('enc.hideTree')}>⟨</button>
        </div>
        <ErrorState error={pagesState.error} onRetry={pagesState.reload} />
        {pagesState.loading && !pagesState.data ? <Loading /> : (
          <PageTree pages={pages} currentId={pageId} storageKey={`ww-tree-${worldId}`} onOpen={open}
            onCreateChild={(parent) => setCreating({ parent })} onMove={move} />
        )}
      </aside>
      <main className="enc-main">
        {pageId ? (
          <PageView key={pageId} worldId={worldId} pageId={pageId} pages={pages} onOpen={open} onChanged={upsert}
            onCreateChild={(parent) => setCreating({ parent })}
            onDeleted={() => { pagesState.reload(); navigate(projectPath(book.id, 'encyclopedia')) }} />
        ) : (
          <Home book={book} pages={pages} loading={pagesState.loading && !pagesState.data} recent={readRecent(recentKey)} onOpen={open}
            onNew={() => setCreating({ parent: null })} />
        )}
      </main>
      {creating && (
        <TemplatePicker worldId={worldId} onClose={() => setCreating(null)} onCreated={(p) => {
          setCreating(null)
          pagesState.reload()
          open(p.id)
        }} parent={creating.parent} />
      )}
    </div>
  )
}

function pickSummary(p: PageSummary): PageSummary {
  const { id, title, icon, page_type, parent, sort_order, aliases, has_children, has_cover, entity_type, entity_id, is_public, updated_at } = p
  return { id, title, icon, page_type, parent, sort_order, aliases, has_children, has_cover, entity_type, entity_id, is_public, updated_at }
}

function Home({ book, pages, loading, recent, onOpen, onNew }: {
  book: Book; pages: PageSummary[]; loading: boolean; recent: number[]; onOpen: (id: number) => void; onNew: () => void
}) {
  const { t, notify } = useApp()
  const [q, setQ] = useState('')
  const [type, setType] = useState('')
  const [found, setFound] = useState<PageSummary[] | null>(null)
  const query = q.trim()

  // Server-side search covers titles, other names and the full text.
  useEffect(() => {
    if (query.length < 2) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      pagesApi.list(book.world, { search: query }, controller.signal).then(setFound)
        .catch((err: unknown) => { if (!(err instanceof ApiError && err.isAborted)) notify(errorText(err), 'error') })
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [query, book.world, notify])

  const types = [...new Set(pages.map((p) => p.page_type))]
  const source = query.length >= 2 && found ? found : pages
  const list = source.filter((p) => !type || p.page_type === type).sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  const recentPages = recent.map((id) => pages.find((p) => p.id === id)).filter((p): p is PageSummary => Boolean(p))
  const typeLabel = (x: string) => (PAGE_TYPES.includes(x) ? t('ptype.' + x) : x)
  const { edit } = useAccess()

  if (loading) return <Loading />
  if (pages.length === 0) {
    return <Empty title={t('enc.emptyTitle')} text={edit ? t('enc.emptyPagesText') : t('ro.emptyEncyclopedia')}
      action={edit ? <button className="btn" onClick={onNew}>+ {t('enc.newPage')}</button> : undefined} />
  }
  return (
    <div className="enc-home-view">
      <div className="enc-home-head">
        <div>
          <h1>{t('s.encyclopedia')}</h1>
          <p className="sub">{t('enc.sub')} «{book.world_name}».</p>
        </div>
        {edit && <button className="btn" onClick={onNew}>+ {t('enc.newPage')}</button>}
      </div>
      <input className="field" placeholder={t('enc.searchPages')} value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="tabs">
        <button className={'tab' + (!type ? ' on' : '')} onClick={() => setType('')}>{t('type.all')}</button>
        {types.map((x) => <button key={x} className={'tab' + (type === x ? ' on' : '')} onClick={() => setType(x)}>{typeLabel(x)}</button>)}
      </div>
      {!query && !type && recentPages.length > 0 && (
        <section>
          <p className="label first">{t('enc.recent')}</p>
          <div className="recent-row">
            {recentPages.map((p) => <button key={p.id} className="recent-card" onClick={() => onOpen(p.id)}><span>{p.icon || '·'}</span>{p.title}</button>)}
          </div>
        </section>
      )}
      <section>
        <p className="label first">{query ? t('enc.results') : t('enc.allPages')} · {list.length}</p>
        {list.length === 0 && <p className="muted">{t('ui.nothing')}</p>}
        {list.map((p) => (
          <button key={p.id} className="page-row" onClick={() => onOpen(p.id)}>
            <span className="tree-icon">{p.icon || '·'}</span>
            <b>{p.title}</b>
            <span className="tag">{typeLabel(p.page_type)}</span>
            <small className="muted">{new Date(p.updated_at).toLocaleDateString()}</small>
          </button>
        ))}
      </section>
    </div>
  )
}

function TemplatePicker({ worldId, parent, onClose, onCreated }: {
  worldId: number; parent: number | null; onClose: () => void; onCreated: (p: PageSummary) => void
}) {
  const { t, notify } = useApp()
  const templates = useAsync<PageTemplateInfo[]>(() => pagesApi.templates(worldId), [worldId])
  const [title, setTitle] = useState('')
  const [choice, setChoice] = useState<PageTemplateInfo | null>(null)
  const { busy, run } = useBusy()
  const create = (tpl: PageTemplateInfo | null) => void run(async () => {
    try {
      const page = await pagesApi.create(worldId, {
        title: title.trim() || t('enc.untitled'), parent,
        ...(tpl?.builtin ? { template: tpl.key } : tpl?.id ? { user_template: tpl.id } : {}),
      })
      onCreated(page)
    } catch (err) { notify(errorText(err), 'error') }
  })
  return (
    <Modal title={parent ? t('enc.addSubpage') : t('enc.newPage')} onClose={onClose} wide footer={<>
      <button className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
      <button className="btn" disabled={busy} onClick={() => create(choice)}>{t('ui.create')}</button>
    </>}>
      <input className="field page-title-input" autoFocus placeholder={t('enc.titlePh')} value={title} onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') create(choice) }} />
      <p className="muted">{t('enc.templateHint')}</p>
      {templates.loading && !templates.data ? <Loading /> : (
        <div className="template-grid">
          {templates.data?.map((tpl) => (
            <button key={tpl.key} className={'template-card' + ((choice?.key ?? 'blank') === tpl.key ? ' on' : '')}
              onClick={() => setChoice(tpl.key === 'blank' ? null : tpl)} onDoubleClick={() => create(tpl.key === 'blank' ? null : tpl)}>
              <span className="tpl-icon">{tpl.icon || '📄'}</span>
              <b>{tpl.name}</b>
              <small>{tpl.properties.length ? tpl.properties.map((p) => p.label).join(', ') : t('enc.freeText')}</small>
              {!tpl.builtin && tpl.id && (
                <span className="link danger-text tpl-del" role="button" onClick={(e) => {
                  e.stopPropagation()
                  void pagesApi.removeTemplate(tpl.id!).then(templates.reload).catch((err) => notify(errorText(err), 'error'))
                }}>{t('ui.delete')}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </Modal>
  )
}
