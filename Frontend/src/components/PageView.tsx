import { Suspense, lazy, useRef, useState } from 'react'
import { useAccess } from '../access'
import { pagesApi } from '../api/pages'
import { PAGE_TYPES } from '../data/projects'
import type { PageDetail, PageProperty, PageSummary } from '../api/types'
import { errorText, useAsync, useBusy, useSelectionQuote } from '../hooks'
import { useApp } from '../settings-context'
import CommentsPanel from './CommentsPanel'
import DocView from './DocView'
import { CharacterBanner, CharacterInfo, FactionInfo, InfoRow, InfoSection } from './EntityPanel'
import Icon from './Icon'
import { CropUpload, Lightbox } from './ImageCropper'
import type { SaveState } from './PageEditor'
import PropertyList from './PropertyList'
import { ErrorState, Loading, Modal } from './Ui'

// Tiptap is the heavy part; it is shared with the chapter editor chunk.
const PageEditor = lazy(() => import('./PageEditor'))


/** One encyclopedia page in the main work area: header, properties, entity data, free text, children, links. */
export default function PageView({ worldId, pageId, pages, onOpen, onChanged, onCreateChild, onDeleted }: {
  worldId: number; pageId: number; pages: PageSummary[]
  onOpen: (id: number) => void; onChanged: (p: PageSummary) => void; onCreateChild: (parent: number) => void; onDeleted: () => void
}) {
  const { t, notify } = useApp()
  const access = useAccess()
  const [commentsOpen, setCommentsOpen] = useState(false)
  const [openComments, setOpenComments] = useState<number | null>(null)
  const textRef = useRef<HTMLDivElement>(null)
  const selection = useSelectionQuote(textRef, commentsOpen)
  const loaded = useAsync<PageDetail>((signal) => pagesApi.get(worldId, pageId, signal), [worldId, pageId])
  const [live, setLive] = useState<{ id: number; page: PageDetail } | null>(null)
  const page = live?.id === pageId ? live.page : loaded.data
  const [saveState, setSaveState] = useState<SaveState>('saved')
  const [menu, setMenu] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [moving, setMoving] = useState(false)
  const [viewCover, setViewCover] = useState(false)
  const { busy, run } = useBusy()

  const apply = (p: PageDetail) => { setLive({ id: p.id, page: p }); onChanged(p) }
  const patch = (data: Parameters<typeof pagesApi.update>[2]) => void run(async () => {
    try { apply(await pagesApi.update(worldId, pageId, data)) } catch (err) { notify(errorText(err), 'error') }
  })

  if (loaded.loading && !loaded.data) return <Loading />
  if (loaded.error) return <ErrorState error={loaded.error} onRetry={loaded.reload} />
  if (!page || !loaded.data) return null

  const typeLabel = (type: string) => (PAGE_TYPES.includes(type) ? t('ptype.' + type) : type)
  const stateText: Record<SaveState, string> = { saved: t('ed.saved'), dirty: t('ed.dirty'), saving: t('ed.saving'), error: t('ed.retrying'), conflict: t('ed.conflict') }
  const brokenLinks = page.links.filter((l) => l.broken)
  const openEntity = (type: 'character' | 'faction', id: number) => {
    pagesApi.byEntity(worldId, type, id).then((p) => onOpen(p.id)).catch((err) => notify(errorText(err), 'error'))
  }
  // Rows shown inside "Характеристики" for every page: other names + free properties.
  const characteristics = (
    <>
      <InfoRow label={page.entity_type === 'character' ? t('info.otherNames') : t('info.aliases')}>
        <AliasEditor aliases={page.aliases} readOnly={!access.edit} onChange={(aliases) => patch({ aliases })} />
      </InfoRow>
      <PropertyList worldId={worldId} pageId={page.id} properties={page.properties} pages={pages} onOpenPage={onOpen}
        onChange={(properties: PageProperty[]) => setLive({ id: page.id, page: { ...page, properties } })} />
    </>
  )
  const cover = page.has_cover ? pagesApi.coverUrl(worldId, page) : null
  // Character pages carry the character's banner at the top (the same one its card shows).
  const characterBanner = !cover && page.entity_type === 'character' && page.entity_id ? page.entity_id : null

  return (
    <article className="page-view">
      {characterBanner && <CharacterBanner worldId={worldId} characterId={characterBanner} />}
      {cover && (
        <div className="page-cover">
          <img src={cover} alt="" onClick={() => setViewCover(true)} />
          {viewCover && <Lightbox src={cover} alt={page.title} onClose={() => setViewCover(false)} />}
        </div>
      )}
      <nav className="crumbs" aria-label={t('enc.breadcrumbs')}>
        {page.breadcrumbs.map((c) => (
          <span key={c.id}><button className="link" onClick={() => onOpen(c.id)}>{c.icon} {c.title}</button> / </span>
        ))}
      </nav>
      <header className="page-header">
        <input className="page-icon" maxLength={4} defaultValue={page.icon} placeholder="✦" aria-label={t('enc.icon')} key={`icon-${page.id}`}
          readOnly={!access.edit} onBlur={(e) => { if (e.target.value !== page.icon) patch({ icon: e.target.value.trim() }) }} />
        <input className="page-title" defaultValue={page.title} key={`title-${page.id}`} aria-label={t('ui.title')} readOnly={!access.edit}
          onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
          onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== page.title) patch({ title: v }); else e.target.value = page.title }} />
        <div className="page-actions">
          {access.edit && <span className={'save-state ' + saveState}>{stateText[saveState]}</span>}
          {access.comment && (
            <button className={'btn-ghost small' + (commentsOpen ? ' on' : '')} onClick={() => setCommentsOpen((v) => !v)}>
              <Icon n="comment" />{t('cm.title')}{openComments ? ` · ${openComments}` : ''}
            </button>
          )}
          {access.edit && <button className="icon-btn" onClick={() => setMenu(!menu)} aria-label={t('enc.more')}>⋯</button>}
          {menu && (
            <div className="menu page-menu" onMouseLeave={() => setMenu(false)}>
              {!characterBanner && <CropUpload aspect={3} outputWidth={1500} className="menu-btn" onUpload={async (file) => {
                setMenu(false)
                try { apply(await pagesApi.uploadCover(worldId, page.id, file)) } catch (err) { notify(errorText(err), 'error') }
              }}>{page.has_cover ? t('enc.changeCover') : t('enc.addCover')}</CropUpload>}
              {page.has_cover && <button onClick={() => { setMenu(false); void pagesApi.removeCover(worldId, page.id).then(() => loaded.reload()).then(() => setLive(null)).catch((err) => notify(errorText(err), 'error')) }}>{t('enc.removeCover')}</button>}
              <button onClick={() => { setMenu(false); onCreateChild(page.id) }}>{t('enc.addSubpage')}</button>
              <button onClick={() => { setMenu(false); setMoving(true) }}>{t('enc.move')}</button>
              <button onClick={() => {
                setMenu(false)
                const name = window.prompt(t('enc.templateName'), page.title)
                if (name) void pagesApi.saveAsTemplate(worldId, page.id, name).then(() => notify(t('enc.templateSaved'))).catch((err) => notify(errorText(err), 'error'))
              }}>{t('enc.saveTemplate')}</button>
              <button className="danger-text" onClick={() => { setMenu(false); setDeleting(true) }}>{t('ui.delete')}</button>
            </div>
          )}
        </div>
      </header>
      <div className="page-columns">
        <div className="page-main" ref={textRef}>
          {access.edit ? (
            <Suspense fallback={<Loading />}>
              <PageEditor key={page.id} worldId={worldId} page={loaded.data} onOpenPage={onOpen} onState={setSaveState}
                onSaved={(p) => apply(p)} />
            </Suspense>
          ) : <DocView doc={page.content} className="prose page-prose" onPageLink={onOpen} />}

          <footer className="page-foot">
            <section>
              <p className="label first">{t('enc.subpages')}</p>
              {page.children.map((c) => <button key={c.id} className="page-link-row" onClick={() => onOpen(c.id)}>{c.icon || '·'} {c.title}</button>)}
              {access.edit && <button className="link" onClick={() => onCreateChild(page.id)}>+ {t('enc.addSubpage')}</button>}
              {!access.edit && page.children.length === 0 && <p className="muted">—</p>}
            </section>
            <section>
              <p className="label first">{t('enc.backlinks')}</p>
              {page.backlinks.length === 0 && <p className="muted">{t('enc.noBacklinks')}</p>}
              {page.backlinks.map((b) => (
                <button key={b.id} className="page-link-row" onClick={() => onOpen(b.id)}>
                  {b.icon || '·'} {b.title} <small className="muted">{b.origins.map((o) => t('enc.origin.' + o)).join(', ')}</small>
                </button>
              ))}
              {brokenLinks.length > 0 && (
                <p className="warn">{t('enc.brokenLinks')}: {brokenLinks.map((l) => `#${l.target_ref}`).join(', ')}</p>
              )}
            </section>
          </footer>
        </div>

        <aside className="infobox" aria-label={t('info.title')}>
          {page.entity_type === 'character' && page.entity_id
            ? <CharacterInfo worldId={worldId} characterId={page.entity_id} onOpenEntity={openEntity}>{characteristics}</CharacterInfo>
            : page.entity_type === 'faction' && page.entity_id
              ? <FactionInfo worldId={worldId} factionId={page.entity_id} onOpenEntity={openEntity}>{characteristics}</FactionInfo>
              : <InfoSection title={t('info.characteristics')}>{characteristics}</InfoSection>}
          <div className="info-meta">
            <label className="type-pill">
              <select value={PAGE_TYPES.includes(page.page_type) ? page.page_type : '__custom'} aria-label={t('enc.pageType')}
                disabled={page.entity_type !== null || !access.edit}
                title={page.entity_type ? t('enc.typeLocked') : undefined}
                onChange={(e) => {
                  const v = e.target.value === '__custom' ? window.prompt(t('enc.customType'), '')?.trim() : e.target.value
                  if (v) patch({ page_type: v })
                }}>
                {PAGE_TYPES.map((type) => <option key={type} value={type}>{typeLabel(type)}</option>)}
                <option value="__custom">{PAGE_TYPES.includes(page.page_type) ? t('enc.customTypeOption') : page.page_type}</option>
              </select>
            </label>
            <span className="muted">
              {t('enc.updated')} {new Date(page.updated_at).toLocaleString()}
              {page.updated_by_name && <> · {page.updated_by_name}</>}
            </span>
          </div>
        </aside>
      </div>

      {commentsOpen && (
        <div className="comments-drawer">
          <CommentsPanel worldId={worldId} target={{ page: page.id }} quote={selection.quote} onQuoteUsed={selection.clear}
            onClose={() => setCommentsOpen(false)} onCount={setOpenComments} />
        </div>
      )}
      {moving && (
        <MoveDialog page={page} pages={pages} onClose={() => setMoving(false)} onMove={(parent) => void run(async () => {
          try {
            const moved = await pagesApi.move(worldId, page.id, parent)
            setMoving(false)
            onChanged(moved)
            setLive(null)
            loaded.reload()
          } catch (err) { notify(errorText(err), 'error') }
        })} />
      )}
      {deleting && (
        <DeleteDialog page={page} pages={pages} busy={busy} onClose={() => setDeleting(false)} onDelete={(mode) => void run(async () => {
          try {
            const r = await pagesApi.remove(worldId, page.id, mode)
            notify(`${t('ui.deleted')}: ${r.deleted}`)
            setDeleting(false)
            onDeleted()
          } catch (err) { notify(errorText(err), 'error') }
        })} />
      )}
    </article>
  )
}

function AliasEditor({ aliases, readOnly, onChange }: { aliases: string[]; readOnly?: boolean; onChange: (a: string[]) => void }) {
  const { t } = useApp()
  if (readOnly) return aliases.length ? <span className="prop-tags">{aliases.map((a) => <span key={a} className="tag">{a}</span>)}</span> : <span className="muted">—</span>
  return (
    <span className="prop-tags aliases">
      {aliases.map((a) => (
        <span key={a} className="tag">{a}<button className="icon-btn" aria-label={t('ui.delete')} onClick={() => onChange(aliases.filter((x) => x !== a))}>×</button></span>
      ))}
      <input className="prop-input narrow" placeholder={t('enc.addAlias')} onKeyDown={(e) => {
        const v = e.currentTarget.value.trim()
        if (e.key === 'Enter' && v) { e.preventDefault(); e.currentTarget.value = ''; if (!aliases.includes(v)) onChange([...aliases, v]) }
      }} />
    </span>
  )
}

function descendantIds(pages: PageSummary[], id: number): Set<number> {
  const out = new Set<number>()
  const walk = (pid: number) => pages.filter((p) => p.parent === pid).forEach((c) => { out.add(c.id); walk(c.id) })
  walk(id)
  return out
}

function MoveDialog({ page, pages, onClose, onMove }: { page: PageSummary; pages: PageSummary[]; onClose: () => void; onMove: (parent: number | null) => void }) {
  const { t } = useApp()
  const banned = descendantIds(pages, page.id)
  const [target, setTarget] = useState<string>(page.parent ? String(page.parent) : '')
  return (
    <Modal title={t('enc.move')} onClose={onClose} footer={<>
      <button className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
      <button className="btn" onClick={() => onMove(target ? Number(target) : null)}>{t('enc.move')}</button>
    </>}>
      <select className="field" value={target} onChange={(e) => setTarget(e.target.value)} autoFocus>
        <option value="">{t('enc.rootLevel')}</option>
        {pages.filter((p) => p.id !== page.id && !banned.has(p.id)).map((p) => <option key={p.id} value={p.id}>{p.icon} {p.title}</option>)}
      </select>
    </Modal>
  )
}

function DeleteDialog({ page, pages, busy, onClose, onDelete }: {
  page: PageDetail; pages: PageSummary[]; busy: boolean; onClose: () => void; onDelete: (mode?: 'lift' | 'delete') => void
}) {
  const { t } = useApp()
  const count = descendantIds(pages, page.id).size
  return (
    <Modal title={`${t('ui.delete')} «${page.title}»?`} onClose={onClose} footer={<>
      <button className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
      {count > 0 && <button className="btn-ghost" disabled={busy} onClick={() => onDelete('lift')}>{t('enc.deleteLift')}</button>}
      <button className="btn-danger" disabled={busy} onClick={() => onDelete(count > 0 ? 'delete' : undefined)}>
        {count > 0 ? `${t('enc.deleteAll')} (${count + 1})` : t('ui.delete')}
      </button>
    </>}>
      <p>{t('ui.deleteText')}</p>
      {count > 0 && <p className="warn">{t('enc.hasChildren')}: {count}</p>}
      {page.entity_type && <p className="muted">{t('enc.deletesEntity')}</p>}
      {page.backlinks.length > 0 && <p className="muted">{t('enc.willBreakLinks')}: {page.backlinks.length}</p>}
    </Modal>
  )
}
