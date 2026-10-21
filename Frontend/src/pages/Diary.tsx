import { useState } from 'react'
import type { DragEvent } from 'react'
import { boardsApi } from '../api/boards'
import type { Board, BoardItem, Book } from '../api/types'
import Header from '../components/Header'
import { Confirm, ErrorState, Loading } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'
import { cssVars } from '../utils'

const COLORS = ['#e879a8', '#3fb8c9', '#e0b36a', '#6fd1a0', '#c58bff', '#7aa2ff']

/** Loads the book's board, creating it (with default columns) on first visit. */
async function loadBoard(bookId: number, title: string, signal: AbortSignal): Promise<Board> {
  const boards = await boardsApi.forBook(bookId, signal)
  return boards[0] ?? boardsApi.create({ title, book: bookId, with_default_columns: true })
}

export default function Diary({ book }: { book: Book }) {
  const { t, notify } = useApp()
  const board = useAsync<Board>((signal) => loadBoard(book.id, t('s.diary'), signal), [book.id])
  const [drafts, setDrafts] = useState<Record<number, string>>({})
  const [editingNote, setEditingNote] = useState<number | null>(null)
  const [noteText, setNoteText] = useState('')
  const [dragged, setDragged] = useState<number | null>(null)
  const [deleting, setDeleting] = useState<BoardItem | null>(null)
  const [linkFrom, setLinkFrom] = useState<number | null>(null)
  const { busy, run } = useBusy()
  const b = board.data

  const columns = (b?.items ?? []).filter((i) => i.kind === 'column').sort((x, y) => x.order - y.order)
  const notesOf = (colId: number) => (b?.items ?? []).filter((i) => i.parent === colId).sort((x, y) => x.order - y.order || x.id - y.id)
  const titleOf = (id: number) => b?.items.find((i) => i.id === id)?.text.slice(0, 40) ?? ''

  const guard = (action: () => Promise<void>) => void run(async () => {
    try { await action() } catch (err) { notify(errorText(err), 'error'); board.reload() }
  })

  const addNote = (col: BoardItem) => {
    const text = (drafts[col.id] ?? '').trim()
    if (!b || !text) return
    guard(async () => {
      const item = await boardsApi.addItem(b.id, { kind: 'note', text, parent: col.id, order: notesOf(col.id).length })
      board.setData((prev) => ({ ...prev!, items: [...prev!.items, item] }))
      setDrafts({ ...drafts, [col.id]: '' })
    })
  }

  const addColumn = () => {
    if (!b) return
    guard(async () => {
      const item = await boardsApi.addItem(b.id, { kind: 'column', text: t('di.newColumn'), color: COLORS[columns.length % COLORS.length], order: columns.length, x: columns.length * 260 })
      board.setData((prev) => ({ ...prev!, items: [...prev!.items, item] }))
    })
  }

  const saveText = (item: BoardItem, text: string) => {
    if (!b || text.trim() === item.text) { setEditingNote(null); return }
    guard(async () => {
      const updated = await boardsApi.updateItem(b.id, item.id, { text: text.trim() })
      board.setData((prev) => ({ ...prev!, items: prev!.items.map((i) => (i.id === item.id ? updated : i)) }))
      setEditingNote(null)
    })
  }

  const remove = (item: BoardItem) => {
    if (!b) return
    guard(async () => {
      await boardsApi.removeItem(b.id, item.id)
      board.setData((prev) => ({
        ...prev!,
        items: prev!.items.filter((i) => i.id !== item.id && i.parent !== item.id),
        connections: prev!.connections.filter((c) => c.source !== item.id && c.target !== item.id),
      }))
      setDeleting(null)
    })
  }

  /** Drop a note into a column at an index; persisted with one layout request. */
  const drop = (col: BoardItem, index: number) => (e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!b || dragged === null) return
    const moving = b.items.find((i) => i.id === dragged)
    setDragged(null)
    if (!moving) return
    const target = notesOf(col.id).filter((n) => n.id !== moving.id)
    target.splice(Math.min(index, target.length), 0, moving)
    const updates = target.map((n, i) => ({ id: n.id, parent: col.id, order: i }))
    if (moving.parent !== col.id) {
      notesOf(moving.parent ?? -1).filter((n) => n.id !== moving.id).forEach((n, i) => updates.push({ id: n.id, parent: moving.parent!, order: i }))
    }
    const previous = b
    board.setData((prev) => ({
      ...prev!, items: prev!.items.map((i) => { const u = updates.find((x) => x.id === i.id); return u ? { ...i, parent: u.parent, order: u.order } : i }),
    }))
    void boardsApi.layout(b.id, updates).then((fresh) => board.setData(fresh)).catch((err) => { board.setData(previous); notify(errorText(err), 'error') })
  }

  const linkClick = (note: BoardItem) => {
    if (!b) return
    if (linkFrom === null) { setLinkFrom(note.id); return }
    if (linkFrom === note.id) { setLinkFrom(null); return }
    const source = linkFrom
    setLinkFrom(null)
    guard(async () => {
      const conn = await boardsApi.connect(b.id, source, note.id)
      board.setData((prev) => ({ ...prev!, connections: [...prev!.connections, conn] }))
    })
  }

  if (board.loading && !b) return <><Header title={t('s.diary')} sub={t('di.sub')} /><Loading /></>
  return (
    <>
      <div className="page-head">
        <Header title={t('s.diary')} sub={t('di.sub')} />
        <button className="btn-ghost" onClick={addColumn} disabled={!b || busy}>+ {t('di.addColumn')}</button>
      </div>
      <ErrorState error={board.error} onRetry={board.reload} />
      {linkFrom !== null && <p className="hint">{t('di.linkHint')} «{titleOf(linkFrom)}»</p>}
      <div className="board">
        {columns.map((c) => (
          <div className="col" key={c.id} style={cssVars({ '--d': c.color || '#e0b36a' })}
            onDragOver={(e) => e.preventDefault()} onDrop={drop(c, notesOf(c.id).length)}>
            <h3>
              <i />
              {editingNote === c.id
                ? <input className="field inline" autoFocus defaultValue={c.text} onBlur={(e) => saveText(c, e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
                : <span onDoubleClick={() => setEditingNote(c.id)}>{c.text}</span>}
              <em>{notesOf(c.id).length}</em>
              <button className="icon-btn" onClick={() => setDeleting(c)} aria-label={t('ui.delete')}>×</button>
            </h3>
            {notesOf(c.id).map((n, index) => {
              const links = (b?.connections ?? []).filter((x) => x.source === n.id || x.target === n.id)
              return (
                <div key={n.id} className={'note' + (linkFrom === n.id ? ' linking' : '')} draggable={editingNote !== n.id}
                  onDragStart={() => setDragged(n.id)} onDragEnd={() => setDragged(null)}
                  onDragOver={(e) => e.preventDefault()} onDrop={drop(c, index)}>
                  {editingNote === n.id ? (
                    <textarea className="field" autoFocus value={noteText} onChange={(e) => setNoteText(e.target.value)}
                      onBlur={() => saveText(n, noteText)} />
                  ) : (
                    <span onDoubleClick={() => { setEditingNote(n.id); setNoteText(n.text) }}>{n.text}</span>
                  )}
                  {links.length > 0 && (
                    <div className="links">{links.map((l) => (
                      <span key={l.id} className="tag" title={t('di.unlink')}
                        onClick={() => guard(async () => { await boardsApi.disconnect(b!.id, l.id); board.setData((prev) => ({ ...prev!, connections: prev!.connections.filter((x) => x.id !== l.id) })) })}>
                        ↔ {titleOf(l.source === n.id ? l.target : l.source)}
                      </span>
                    ))}</div>
                  )}
                  <div className="note-acts">
                    <button className="link" onClick={() => linkClick(n)}>{linkFrom === n.id ? t('ui.cancel') : t('di.link')}</button>
                    <button className="link" onClick={() => setDeleting(n)}>{t('ui.delete')}</button>
                  </div>
                </div>
              )
            })}
            <div className="add-note">
              <textarea className="field" rows={2} placeholder={t('di.notePh')} value={drafts[c.id] ?? ''}
                onChange={(e) => setDrafts({ ...drafts, [c.id]: e.target.value })}
                onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) addNote(c) }} />
              <button className="btn-ghost" disabled={busy || !(drafts[c.id] ?? '').trim()} onClick={() => addNote(c)}>{t('ui.add')}</button>
            </div>
          </div>
        ))}
      </div>
      {deleting && (
        <Confirm title={t('ui.confirmDelete')} text={deleting.kind === 'column' ? t('di.deleteColumn') : deleting.text.slice(0, 120)}
          confirmLabel={t('ui.delete')} busy={busy} onCancel={() => setDeleting(null)} onConfirm={() => remove(deleting)} />
      )}
    </>
  )
}
