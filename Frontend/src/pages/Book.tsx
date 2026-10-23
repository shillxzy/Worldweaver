import { Suspense, lazy, useEffect, useState } from 'react'
import { authApi } from '../api/auth'
import { booksApi } from '../api/books'
import { chaptersApi } from '../api/chapters'
import type { ImportMode, ImportPreview } from '../api/chapters'
import type { Book, Chapter, ChapterSummary, UserSettings } from '../api/types'
import CoverArt from '../components/CoverArt'
import Header from '../components/Header'
import Icon from '../components/Icon'
import { Confirm, Empty, ErrorState, Loading, Modal } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'

// The Tiptap editor is the heaviest dependency; load it only when a chapter is opened for writing.
const ChapterEditor = lazy(() => import('../components/ChapterEditor'))

export default function BookPage({ book, focus }: { book: Book; focus?: string }) {
  const { t, notify, refreshBooks } = useApp()
  const focusChapter = focus?.startsWith('chapter:') ? Number(focus.split(':')[1]) : null
  const [open, setOpen] = useState(focusChapter !== null || sessionStorage.getItem('ww-book-open') === String(book.id))
  const [mode, setMode] = useState<'write' | 'read'>('write')
  const [activeId, setActiveId] = useState<number | null>(focusChapter)
  const [importing, setImporting] = useState(false)
  const [deleting, setDeleting] = useState<ChapterSummary | null>(null)
  const { busy, run } = useBusy()
  const chapters = useAsync<ChapterSummary[]>((signal) => chaptersApi.list(book.id, signal), [book.id])
  const prefs = useAsync<UserSettings>(() => authApi.settings(), [])
  const list = chapters.data ?? []
  const activeIdResolved = activeId ?? list[0]?.id ?? null
  const active = useAsync<Chapter | null>(
    (signal) => (activeIdResolved ? chaptersApi.get(book.id, activeIdResolved, signal) : Promise.resolve(null)),
    [book.id, activeIdResolved],
  )

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
          <div className="seg">
            <button className={mode === 'write' ? 'on' : ''} onClick={() => setMode('write')}><Icon n="pen" />{t('bk.write')}</button>
            <button className={mode === 'read' ? 'on' : ''} onClick={() => setMode('read')}><Icon n="read" />{t('bk.read')}</button>
          </div>
          <button className="btn-ghost" onClick={() => setImporting(true)}>{t('bk.import')}</button>
          <button className="btn-ghost" disabled={!list.length} onClick={() => void booksApi.exportDocx(book).catch((err) => notify(errorText(err), 'error'))}>{t('bk.export')}</button>
          <button className="link" onClick={() => setOpen(false)}>{t('bk.close')}</button>
        </div>
      </div>
      <ErrorState error={chapters.error} onRetry={chapters.reload} />
      {chapters.loading && !chapters.data ? <Loading /> : list.length === 0 ? (
        <Empty title={t('bk.emptyTitle')} text={t('bk.emptyText')}
          action={<div className="head-acts"><button className="btn" onClick={addChapter} disabled={busy}>+ {t('bk.addChapter')}</button>
            <button className="btn-ghost" onClick={() => setImporting(true)}>{t('bk.import')}</button></div>} />
      ) : (
        <div className="book-layout">
          <nav className="chapter-list">
            {list.map((c, i) => (
              <div key={c.id} className={'chapter-item' + (c.id === activeIdResolved ? ' on' : '')}>
                <button className="chapter-name" onClick={() => setActiveId(c.id)}>
                  <span>{i + 1}. {c.title}</span>
                  <small>{c.word_count} · {t('chStatus.' + c.status)}{c.is_flashback ? ' · ⟲' : ''}</small>
                </button>
                <div className="chapter-acts">
                  <button className="icon-btn" onClick={() => move(i, -1)} disabled={i === 0 || busy} aria-label="up">↑</button>
                  <button className="icon-btn" onClick={() => move(i, 1)} disabled={i === list.length - 1 || busy} aria-label="down">↓</button>
                  <button className="icon-btn" onClick={() => void chaptersApi.exportDocx(book.id, c).catch((err) => notify(errorText(err), 'error'))} aria-label="docx">⤓</button>
                  <button className="icon-btn" onClick={() => setDeleting(c)} aria-label={t('ui.delete')}>×</button>
                </div>
              </div>
            ))}
            <button className="btn-ghost" onClick={addChapter} disabled={busy}>+ {t('bk.addChapter')}</button>
          </nav>
          <div className="chapter-main">
            <ErrorState error={active.error} onRetry={active.reload} />
            {active.loading ? <Loading /> : active.data && (
              mode === 'write' ? (
                <Suspense fallback={<Loading />}><ChapterEditor key={`${active.data.id}:${active.data.revision}`} bookId={book.id} worldId={book.world} chapter={active.data}
                  quickEnabled={prefs.data?.quick_checks_enabled ?? true} spellEnabled={prefs.data?.spellcheck_enabled ?? true}
                  onMetaSaved={(c) => chapters.setData((prev) => (prev ?? []).map((x) => (x.id === c.id ? { ...x, ...c } : x)))} /></Suspense>
              ) : (
                <Reader chapter={active.data} index={list.findIndex((c) => c.id === active.data!.id)} total={list.length}
                  onPrev={() => { const i = list.findIndex((c) => c.id === active.data!.id); if (i > 0) setActiveId(list[i - 1].id) }}
                  onNext={() => { const i = list.findIndex((c) => c.id === active.data!.id); if (i < list.length - 1) setActiveId(list[i + 1].id) }} />
              )
            )}
          </div>
        </div>
      )}
      {importing && (
        <ImportDialog book={book} chapters={list} activeId={activeIdResolved} onClose={() => setImporting(false)}
          onDone={(created) => { setImporting(false); chapters.reload(); active.reload(); if (created[0]) setActiveId(created[0].id); void refreshBooks() }} />
      )}
      {deleting && (
        <Confirm title={t('ui.confirmDelete')} text={`${deleting.title} — ${t('bk.deleteChapterText')}`} confirmLabel={t('ui.delete')} busy={busy}
          onCancel={() => setDeleting(null)} onConfirm={() => removeChapter(deleting)} />
      )}
    </>
  )
}

function Reader({ chapter, index, total, onPrev, onNext }: { chapter: Chapter; index: number; total: number; onPrev: () => void; onNext: () => void }) {
  const { t } = useApp()
  return (
    <>
      <div className="paper reader">
        <h2>{chapter.title}</h2>
        {chapter.plain_text.split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>)}
        <div className="pn">{index + 1} / {total}</div>
      </div>
      <div className="pager">
        <button className="link" disabled={index === 0} onClick={onPrev}>{t('bk.prev')}</button>
        <button className="link" disabled={index === total - 1} onClick={onNext}>{t('bk.next')}</button>
      </div>
    </>
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
