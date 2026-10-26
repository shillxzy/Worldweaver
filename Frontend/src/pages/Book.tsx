import { Fragment, Suspense, lazy, useEffect, useRef, useState } from 'react'
import { useAccess } from '../access'
import { authApi } from '../api/auth'
import { booksApi } from '../api/books'
import { arcsApi, chaptersApi } from '../api/chapters'
import { collabApi } from '../api/collab'
import type { ImportMode, ImportPreview } from '../api/chapters'
import type { Arc, Book, Chapter, ChapterSummary, Comment, UserSettings } from '../api/types'
import CommentsPanel from '../components/CommentsPanel'
import { hit, useCommentHighlights, useSelectionAnchor } from '../components/commentAnchors'
import type { Anchor } from '../components/commentAnchors'
import CoverArt from '../components/CoverArt'
import DocView from '../components/DocView'
import Header from '../components/Header'
import Icon from '../components/Icon'
import { Confirm, Empty, ErrorState, Loading, Modal } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'

// The Tiptap editor is the heaviest dependency; load it only when a chapter is opened for writing.
const ChapterEditor = lazy(() => import('../components/ChapterEditor'))

export default function BookPage({ book, focus }: { book: Book; focus?: string }) {
  const { t, notify, refreshBooks } = useApp()
  const access = useAccess()
  const focusChapter = focus?.startsWith('chapter:') ? Number(focus.split(':')[1]) : null
  const [open, setOpen] = useState(focusChapter !== null || sessionStorage.getItem('ww-book-open') === String(book.id))
  // Readers and commenters get the reading view; only editors and above open the editor.
  const [mode, setMode] = useState<'write' | 'read'>(access.edit ? 'write' : 'read')
  const view = access.edit ? mode : 'read'
  const [commentsOpen, setCommentsOpen] = useState(false)
  const mainRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLElement>(null)
  const [activeId, setActiveId] = useState<number | null>(focusChapter)
  const [importing, setImporting] = useState(false)
  const [deleting, setDeleting] = useState<ChapterSummary | null>(null)
  const { busy, run } = useBusy()
  const chapters = useAsync<ChapterSummary[]>((signal) => chaptersApi.list(book.id, signal), [book.id])
  const arcs = useAsync<Arc[]>((signal) => arcsApi.list(book.id, signal), [book.id])
  const [arcEditing, setArcEditing] = useState<Arc | 'new' | null>(null)
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const arcOf = new Map((arcs.data ?? []).map((a) => [a.id, a]))
  const prefs = useAsync<UserSettings>(() => authApi.settings(), [])
  const counts = useAsync<Record<string, number>>(
    async (signal) => (access.comment ? (await collabApi.commentCounts(book.world, book.id, signal)).chapters : {}),
    [book.world, book.id, access.comment],
  )
  const list = chapters.data ?? []
  const activeIdResolved = activeId ?? list[0]?.id ?? null
  const active = useAsync<Chapter | null>(
    (signal) => (activeIdResolved ? chaptersApi.get(book.id, activeIdResolved, signal) : Promise.resolve(null)),
    [book.id, activeIdResolved],
  )

  // Comments on passages, Google Docs style: a button next to the selection, the commented passages
  // highlighted in the text, and a click on a highlight opens its thread.
  const comments = useAsync<Comment[]>(
    (signal) => (access.comment && activeIdResolved ? collabApi.comments(book.world, { chapter: activeIdResolved }, signal) : Promise.resolve([])),
    [book.world, activeIdResolved, access.comment],
  )
  // Both belong to one chapter: switching chapters drops them without an effect.
  const [focused, setFocus] = useState<{ chapter: number | null; id: number } | null>(null)
  const [quoted, setQuoted] = useState<(Anchor & { chapter: number | null }) | null>(null)
  const focusId = focused?.chapter === activeIdResolved ? focused.id : null
  const pending = quoted?.chapter === activeIdResolved ? quoted : null
  const setFocusId = (id: number | null) => setFocus(id === null ? null : { chapter: activeIdResolved, id })
  const setPending = (a: Anchor | null) => setQuoted(a && { ...a, chapter: activeIdResolved })
  const panelOpen = useRef(commentsOpen)
  useEffect(() => { panelOpen.current = commentsOpen }, [commentsOpen])
  // With the panel open, a new selection becomes the quote of the next comment (as before).
  const selected = useSelectionAnchor(mainRef, access.comment, (a) => {
    if (panelOpen.current) setQuoted({ quote: a.quote, occurrence: a.occurrence, chapter: activeIdResolved })
  })
  const anchors = (comments.data ?? []).filter((c) => !c.parent && !c.resolved && c.quote)
    .map((c) => ({ id: c.id, quote: c.quote, occurrence: c.quote_occurrence }))
  const ranges = useCommentHighlights(mainRef, anchors, focusId, `${activeIdResolved}:${view}:${active.data?.revision ?? ''}`)
  // Open threads per chapter; the open chapter's number is live (it follows the panel).
  const openCount = (id: number | null) => (id !== null && id === activeIdResolved && comments.data
    ? comments.data.filter((c) => !c.parent && !c.resolved).length : counts.data?.[String(id)] ?? 0)
  const commentSelection = () => {
    if (!selected) return
    setPending({ quote: selected.quote, occurrence: selected.occurrence })
    setFocusId(null)
    setCommentsOpen(true)
  }
  const pickHighlight = (e: React.MouseEvent) => {
    if (!access.comment || !document.getSelection()?.isCollapsed) return
    const id = hit(ranges.current, e.clientX, e.clientY)
    if (id !== null) { setFocusId(id); setCommentsOpen(true) }
  }
  const showInText = (id: number) => {
    setFocusId(id)
    ranges.current.get(id)?.startContainer.parentElement?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }

  // Keep the open chapter visible in the list (e.g. after "next chapter" or a link to chapter 80).
  useEffect(() => {
    const list = listRef.current
    const item = list?.querySelector<HTMLElement>('.chapter-item.on')
    if (!list || !item) return
    const top = item.getBoundingClientRect().top - list.getBoundingClientRect().top + list.scrollTop
    if (top < list.scrollTop || top + item.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTo({ top: top - list.clientHeight / 3, behavior: 'smooth' })
    }
  }, [activeIdResolved, chapters.data])

  useEffect(() => {
    try { sessionStorage.setItem('ww-book-open', open ? String(book.id) : '') } catch { /* optional */ }
  }, [open, book.id])

  const addChapter = () => void run(async () => {
    try {
      const created = await chaptersApi.create(book.id, { title: `${t('bk.chapter')} ${list.length + 1}` })
      chapters.reload()
      setActiveId(created.id)
      void refreshBooks()
    } catch (err) { notify(errorText(err), 'error') }
  })

  const move = (index: number, delta: number) => {
    const order = list.map((c) => c.id)
    const target = index + delta
    if (target < 0 || target >= order.length) return
    ;[order[index], order[target]] = [order[target], order[index]]
    void run(async () => {
      try { chapters.setData(await chaptersApi.reorder(book.id, order)) } catch (err) { notify(errorText(err), 'error'); chapters.reload() }
    })
  }

  const removeChapter = (c: ChapterSummary) => void run(async () => {
    try {
      await chaptersApi.remove(book.id, c.id)
      setDeleting(null)
      if (activeIdResolved === c.id) setActiveId(null)
      chapters.reload()
      void refreshBooks()
    } catch (err) { notify(errorText(err), 'error') }
  })

  if (!open) {
    return (
      <>
        <Header title={t('s.book')} sub={t('bk.closed')} />
        <div className="shelf">
          <button className="cover-art" onClick={() => setOpen(true)}><CoverArt p={book} big /></button>
        </div>
      </>
    )
  }

  return (
    <>
      <div className="page-head">
        <Header title={book.title} sub={`${list.length} ${t('bk.chapters')} · ${book.word_count ?? 0} ${t('ov.words')}`} />
        <div className="head-acts">
          {access.edit && (
            <div className="seg">
              <button className={mode === 'write' ? 'on' : ''} onClick={() => setMode('write')}><Icon n="pen" />{t('bk.write')}</button>
              <button className={mode === 'read' ? 'on' : ''} onClick={() => setMode('read')}><Icon n="read" />{t('bk.read')}</button>
            </div>
          )}
          {access.comment && list.length > 0 && (
            <button className={'btn-ghost' + (commentsOpen ? ' on' : '')} onClick={() => setCommentsOpen((v) => !v)}>
              <Icon n="comment" />{t('cm.title')}{openCount(activeIdResolved) ? ` · ${openCount(activeIdResolved)}` : ''}
            </button>
          )}
          {access.edit && <button className="btn-ghost" onClick={() => setImporting(true)}>{t('bk.import')}</button>}
          {access.edit && <button className="btn-ghost" disabled={!list.length} onClick={() => void booksApi.exportDocx(book).catch((err) => notify(errorText(err), 'error'))}>{t('bk.export')}</button>}
          <button className="link" onClick={() => setOpen(false)}>{t('bk.close')}</button>
        </div>
      </div>
      <ErrorState error={chapters.error} onRetry={chapters.reload} />
      {chapters.loading && !chapters.data ? <Loading /> : list.length === 0 ? (
        <Empty title={t('bk.emptyTitle')} text={access.edit ? t('bk.emptyText') : t('ro.emptyBook')}
          action={access.edit ? <div className="head-acts"><button className="btn" onClick={addChapter} disabled={busy}>+ {t('bk.addChapter')}</button>
            <button className="btn-ghost" onClick={() => setImporting(true)}>{t('bk.import')}</button></div> : undefined} />
      ) : (
        <div className={'book-layout' + (commentsOpen ? ' with-comments' : '')}>
          <nav className="chapter-list" ref={listRef}>
            {list.map((c, i) => {
              // An arc heading opens each run of chapters of one arc (in reading order).
              const arc = c.arc !== null ? arcOf.get(c.arc) : undefined
              const startsArc = arc && (i === 0 || list[i - 1].arc !== c.arc)
              const hidden = arc && collapsed.has(arc.id) && c.id !== activeIdResolved
              const runLength = startsArc ? list.slice(i).findIndex((x) => x.arc !== c.arc) : 0
              return (
                <Fragment key={c.id}>
                  {startsArc && (
                    <div className="arc-head">
                      <button className="arc-name" onClick={() => setCollapsed((prev) => {
                        const next = new Set(prev)
                        if (next.has(arc.id)) next.delete(arc.id); else next.add(arc.id)
                        return next
                      })} title={collapsed.has(arc.id) ? t('arc.expand') : t('arc.collapse')}>
                        <span className="arc-caret">{collapsed.has(arc.id) ? '▸' : '▾'}</span>
                        <span>{arc.title}</span>
                        <small>{runLength === -1 ? list.length - i : runLength} {t('arc.chapters')}</small>
                      </button>
                      {access.edit && <button className="icon-btn" onClick={() => setArcEditing(arc)} aria-label={t('arc.edit')}>✎</button>}
                    </div>
                  )}
                  {!hidden && (
                    <div className={'chapter-item' + (c.id === activeIdResolved ? ' on' : '') + (arc ? ' in-arc' : '')}>
                      <button className="chapter-name" onClick={() => setActiveId(c.id)}
                        title={c.updated_by_name ? `${t('bk.lastEditedBy')}: ${c.updated_by_name}` : undefined}>
                        <span>{i + 1}. {c.title}</span>
                        <small>
                          {c.word_count} · {t('chStatus.' + c.status)}
                          {openCount(c.id) ? <span className="comment-badge" title={t('cm.open')}> · 💬 {openCount(c.id)}</span> : null}
                        </small>
                      </button>
                      {access.edit && <div className="chapter-acts">
                        <button className="icon-btn" onClick={() => move(i, -1)} disabled={i === 0 || busy} aria-label="up">↑</button>
                        <button className="icon-btn" onClick={() => move(i, 1)} disabled={i === list.length - 1 || busy} aria-label="down">↓</button>
                        <button className="icon-btn" onClick={() => void chaptersApi.exportDocx(book.id, c).catch((err) => notify(errorText(err), 'error'))} aria-label="docx">⤓</button>
                        <button className="icon-btn" onClick={() => setDeleting(c)} aria-label={t('ui.delete')}>×</button>
                      </div>}
                    </div>
                  )}
                </Fragment>
              )
            })}
            {access.edit && (
              <div className="chapter-adds">
                <button className="btn-ghost" onClick={addChapter} disabled={busy}>+ {t('bk.addChapter')}</button>
                <button className="btn-ghost" onClick={() => setArcEditing('new')} disabled={busy}>+ {t('arc.add')}</button>
              </div>
            )}
          </nav>
          <div className="chapter-main" ref={mainRef} onClick={pickHighlight}>
            <ErrorState error={active.error} onRetry={active.reload} />
            {active.loading ? <Loading /> : active.data && (
              view === 'write' ? (
                <Suspense fallback={<Loading />}><ChapterEditor key={`${active.data.id}:${active.data.revision}`} bookId={book.id} worldId={book.world} chapter={active.data}
                  quickEnabled={prefs.data?.quick_checks_enabled ?? true} spellEnabled={prefs.data?.spellcheck_enabled ?? true}
                  onMetaSaved={(c) => chapters.setData((prev) => (prev ?? []).map((x) => (x.id === c.id ? { ...x, ...c } : x)))} /></Suspense>
              ) : (
                <Reader chapter={active.data} arc={active.data.arc !== null ? arcOf.get(active.data.arc)?.title : undefined} index={list.findIndex((c) => c.id === active.data!.id)} total={list.length}
                  onPrev={() => { const i = list.findIndex((c) => c.id === active.data!.id); if (i > 0) setActiveId(list[i - 1].id) }}
                  onNext={() => { const i = list.findIndex((c) => c.id === active.data!.id); if (i < list.length - 1) setActiveId(list[i + 1].id) }} />
              )
            )}
          </div>
          {commentsOpen && activeIdResolved && (
            <CommentsPanel worldId={book.world} target={{ chapter: activeIdResolved }} state={comments}
              quote={pending?.quote} occurrence={pending?.occurrence} onQuoteUsed={() => setPending(null)}
              focusId={focusId} onFocus={showInText} onClose={() => { setCommentsOpen(false); setFocusId(null) }} />
          )}
        </div>
      )}
      {selected && (
        <button className="selection-comment" onMouseDown={(e) => e.preventDefault()} onClick={commentSelection}
          style={{ top: Math.min(selected.rect.bottom + 8, window.innerHeight - 44), left: Math.min(Math.max(8, selected.rect.left + selected.rect.width / 2 - 60), window.innerWidth - 140) }}>
          <Icon n="comment" />{t('cm.onSelection')}
        </button>
      )}
      {importing && (
        <ImportDialog book={book} chapters={list} activeId={activeIdResolved} onClose={() => setImporting(false)}
          onDone={(created) => { setImporting(false); chapters.reload(); active.reload(); if (created[0]) setActiveId(created[0].id); void refreshBooks() }} />
      )}
      {arcEditing && (
        <ArcDialog bookId={book.id} arc={arcEditing === 'new' ? null : arcEditing} chapters={list}
          activeId={activeIdResolved} onClose={() => setArcEditing(null)}
          onDone={() => { setArcEditing(null); arcs.reload(); chapters.reload() }} />
      )}
      {deleting && (
        <Confirm title={t('ui.confirmDelete')} text={`${deleting.title} — ${t('bk.deleteChapterText')}`} confirmLabel={t('ui.delete')} busy={busy}
          onCancel={() => setDeleting(null)} onConfirm={() => removeChapter(deleting)} />
      )}
    </>
  )
}

function Reader({ chapter, arc, index, total, onPrev, onNext }: {
  chapter: Chapter; arc?: string; index: number; total: number; onPrev: () => void; onNext: () => void
}) {
  const { t } = useApp()
  return (
    <>
      <div className="paper reader">
        {arc && <div className="reader-arc">{arc}</div>}
        <h2>{chapter.title}</h2>
        <DocView doc={chapter.content} />
        <div className="pn">{index + 1} / {total}</div>
      </div>
      <div className="pager">
        <button className="link" disabled={index === 0} onClick={onPrev}>{t('bk.prev')}</button>
        <button className="link" disabled={index === total - 1} onClick={onNext}>{t('bk.next')}</button>
      </div>
    </>
  )
}

/** Create or change an arc: its title and the run of chapters it covers (in reading order). */
function ArcDialog({ bookId, arc, chapters, activeId, onClose, onDone }: {
  bookId: number; arc: Arc | null; chapters: ChapterSummary[]; activeId: number | null; onClose: () => void; onDone: () => void
}) {
  const { t, notify } = useApp()
  const own = arc ? chapters.filter((c) => c.arc === arc.id) : []
  const fallback = activeId ?? chapters[0]?.id ?? 0
  const [title, setTitle] = useState(arc?.title ?? '')
  const [first, setFirst] = useState(own[0]?.id ?? fallback)
  const [last, setLast] = useState(own[own.length - 1]?.id ?? fallback)
  const [confirming, setConfirming] = useState(false)
  const { busy, run } = useBusy()
  const save = () => void run(async () => {
    try {
      const data = { title: title.trim(), first_chapter: first, last_chapter: last }
      if (arc) await arcsApi.update(bookId, arc.id, data); else await arcsApi.create(bookId, data)
      onDone()
    } catch (err) { notify(errorText(err), 'error') }
  })
  const remove = () => void run(async () => {
    try { if (arc) await arcsApi.remove(bookId, arc.id); onDone() } catch (err) { notify(errorText(err), 'error') }
  })
  const pick = (value: number, set: (id: number) => void) => (
    <select className="field" value={value} onChange={(e) => set(Number(e.target.value))}>
      {chapters.map((c, i) => <option key={c.id} value={c.id}>{i + 1}. {c.title}</option>)}
    </select>
  )
  return (
    <Modal title={arc ? t('arc.edit') : t('arc.new')} onClose={onClose} footer={<>
      {arc && <button className="btn-danger" disabled={busy} onClick={() => setConfirming(true)}>{t('arc.delete')}</button>}
      <span className="spacer" />
      <button className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
      <button className="btn" disabled={busy || !title.trim() || !chapters.length} onClick={save}>{t('ui.save')}</button>
    </>}>
      <div className="form">
        <label>{t('arc.title')}
          <input className="field" autoFocus maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && title.trim()) save() }} />
        </label>
        <label>{t('arc.from')}{pick(first, setFirst)}</label>
        <label>{t('arc.to')}{pick(last, setLast)}</label>
        <small className="muted">{t('arc.hint')}</small>
      </div>
      {confirming && (
        <Confirm title={t('arc.delete')} text={`${arc?.title} — ${t('arc.hint')}`} confirmLabel={t('ui.delete')} busy={busy}
          onCancel={() => setConfirming(false)} onConfirm={remove} />
      )}
    </Modal>
  )
}

function ImportDialog({ book, chapters, activeId, onClose, onDone }: {
  book: Book; chapters: ChapterSummary[]; activeId: number | null; onClose: () => void; onDone: (created: ChapterSummary[]) => void
}) {
  const { t, notify } = useApp()
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<ImportMode>('split_headings')
  const [target, setTarget] = useState<number | null>(activeId)
  const [level, setLevel] = useState<number | null>(null)
  const [error, setError] = useState('')
  const { busy, run } = useBusy()
  const tooLarge = !!file && file.size > MAX_DOCX_BYTES
  const wantPreview = !!file && !tooLarge && mode === 'split_headings'
  const preview = useAsync<ImportPreview | null>(
    (signal) => (wantPreview && file ? chaptersApi.previewDocx(file, level ?? undefined, signal) : Promise.resolve(null)),
    [wantPreview, file?.name, file?.size, file?.lastModified, level],
  )
  const plan = wantPreview ? preview.data : null
  const pickFile = (next: File | null) => {
    setFile(next); setLevel(null)
    setError(next && next.size > MAX_DOCX_BYTES ? t('bk.tooLarge') : '')
  }
  const submit = () => {
    if (!file || tooLarge) return
    void run(async () => {
      try {
        const created = await chaptersApi.importDocx(book.id, file, mode, mode === 'replace_chapter' ? target ?? undefined : undefined,
          mode === 'split_headings' ? plan?.split_level ?? undefined : undefined)
        notify(t('bk.imported'))
        onDone(created)
      } catch (err) { setError(errorText(err)) }
    })
  }
  return (
    <Modal title={t('bk.import')} onClose={onClose} wide={wantPreview} footer={<>
      <button className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
      <button className="btn" disabled={!file || tooLarge || busy || (wantPreview && (preview.loading || !!preview.error))} onClick={submit}>
        {busy ? t('ui.loading') : plan ? t('bk.importCount').replace('{n}', String(plan.chapters.length)) : t('bk.importGo')}
      </button>
    </>}>
      <div className="form">
        <input type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
        <label className="check"><input type="radio" checked={mode === 'split_headings'} onChange={() => setMode('split_headings')} />{t('bk.modeSplit')}</label>
        <label className="check"><input type="radio" checked={mode === 'new_chapter'} onChange={() => setMode('new_chapter')} />{t('bk.modeOne')}</label>
        <label className="check"><input type="radio" checked={mode === 'replace_chapter'} disabled={!chapters.length} onChange={() => setMode('replace_chapter')} />{t('bk.modeReplace')}</label>
        {mode === 'replace_chapter' && (
          <select className="field" value={target ?? ''} onChange={(e) => setTarget(Number(e.target.value))}>
            {chapters.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        )}
        {wantPreview && <ImportPreviewList preview={preview.data ?? null} loading={preview.loading} error={preview.error ? errorText(preview.error) : ''}
          onLevel={setLevel} />}
        <small className="muted">{t('bk.importHint')}</small>
        {error && <p className="field-error">{error}</p>}
      </div>
    </Modal>
  )
}

const MAX_DOCX_BYTES = 10 * 1024 * 1024

function ImportPreviewList({ preview, loading, error, onLevel }: {
  preview: ImportPreview | null; loading: boolean; error: string; onLevel: (level: number) => void
}) {
  const { t } = useApp()
  if (error) return <p className="field-error">{error}</p>
  if (!preview) return <p className="muted import-note">{t('bk.previewLoading')}</p>
  const arcs = preview.chapters.reduce((sum, c) => sum + c.merged.length, 0)
  return (
    <div className={`import-preview${loading ? ' stale' : ''}`}>
      <div className="import-summary">
        <b>{t('bk.previewFound').replace('{n}', String(preview.chapters.length))}</b>
        {preview.levels.length > 1 && (
          <label className="inline-field">{t('bk.splitBy')}
            <select className="field" value={preview.split_level ?? ''} onChange={(e) => onLevel(Number(e.target.value))}>
              {preview.levels.map((lv) => (
                <option key={lv.level} value={lv.level}>
                  {t('bk.headingLevel').replace('{n}', String(lv.level))} · {lv.count}{lv.level === preview.suggested_level ? ` · ${t('bk.suggested')}` : ''}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {arcs > 0 && <small className="muted">{t('bk.previewArcs').replace('{n}', String(arcs))}</small>}
      {preview.levels.length === 0 && <small className="muted">{t('bk.previewNoHeadings')}</small>}
      <ol className="import-list">
        {preview.chapters.map((c, i) => (
          <li key={i}>
            <span className="import-title">
              {c.title}
              {c.lead_in && <span className="tag">{t('bk.leadIn')}</span>}
            </span>
            <small className="muted">{c.word_count.toLocaleString()} {t('bk.wordsShort')}</small>
            {c.merged.map((m, j) => <small key={j} className="import-merged">↳ {m}</small>)}
          </li>
        ))}
      </ol>
    </div>
  )
}
