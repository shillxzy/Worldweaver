import { useState } from 'react'
import { useAccess } from '../access'
import { booksApi } from '../api/books'
import type { Book, World } from '../api/types'
import { worldsApi } from '../api/worlds'
import BookForm from '../components/BookForm'
import CoverArt from '../components/CoverArt'
import Icon from '../components/Icon'
import { Confirm, ErrorState } from '../components/Ui'
import WorldForm from '../components/WorldForm'
import { SECTIONS } from '../data/projects'
import { errorText, useAsync, useBusy } from '../hooks'
import { navigate, projectPath } from '../router'
import { useApp } from '../settings-context'

export default function Overview({ book }: { book: Book }) {
  const { t, refreshBooks, notify } = useApp()
  const access = useAccess()
  const world = useAsync<World>((signal) => worldsApi.get(book.world, signal), [book.world])
  const [editing, setEditing] = useState<'book' | 'world' | null>(null)
  const [deleting, setDeleting] = useState(false)
  const { busy, run } = useBusy()
  const w = world.data

  const remove = () => run(async () => {
    try {
      await booksApi.remove(book.id)
      notify(t('ui.deleted'))
      await refreshBooks()
      navigate('/')
    } catch (err) {
      notify(errorText(err), 'error')
    }
  })

  return (
    <>
      <div className="hero">
        <div className="cover-art"><CoverArt p={book} /></div>
        <div className="hero-body">
          <span className="tag">{book.genre || t('bookStatus.' + book.status)}</span>
          <h1 style={{ marginTop: 10 }}>{book.title}</h1>
          <p className="sub">{book.description || t('ov.noDescription')}</p>
          <div className="stats">
            <div><b>{w?.characters_count ?? '—'}</b><span>{t('ov.chars')}</span></div>
            <div><b>{w ? w.characters_count + w.factions_count + w.lore_count : '—'}</b><span>{t('ov.entries')}</span></div>
            <div><b>{w?.events_count ?? '—'}</b><span>{t('ov.events')}</span></div>
            <div><b>{book.word_count ?? 0}</b><span>{t('ov.words')}</span></div>
          </div>
          <div className="hero-acts">
            {access.edit && <button className="btn-ghost" onClick={() => setEditing('book')}><Icon n="pen" />{t('ov.edit')}</button>}
            {access.edit && <button className="btn-ghost" onClick={() => setEditing('world')} disabled={!w}><Icon n="globe" />{t('ov.world')}: {w?.name ?? '…'}</button>}
            {access.manage && <button className="btn-ghost danger-text" onClick={() => setDeleting(true)}><Icon n="trash" />{t('ov.delete')}</button>}
            {!access.edit && <span className="muted">{t('ro.notice').replace('{role}', t('role.' + access.role))}</span>}
          </div>
        </div>
      </div>
      <ErrorState error={world.error} onRetry={world.reload} />
      <div className="bento">
        {SECTIONS.slice(1).map((s, i) => (
          <button key={s.id} className={'tile' + (i === 0 || i === 4 ? ' wide' : '')} onClick={() => navigate(projectPath(book.id, s.id))}>
            <div className="chip"><Icon n={s.icon} /></div>
            <h3>{t('s.' + s.id)}</h3>
            <p>{t('d.' + s.id)}</p>
          </button>
        ))}
      </div>
      {editing === 'book' && (
        <BookForm book={book} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); notify(t('ui.saved')); void refreshBooks() }} />
      )}
      {editing === 'world' && w && (
        <WorldForm world={w} onClose={() => setEditing(null)} onSaved={(nw) => { setEditing(null); world.setData(nw); notify(t('ui.saved')); void refreshBooks() }} />
      )}
      {deleting && (
        <Confirm title={t('ov.delete')} text={t('ov.deleteText')} confirmLabel={t('st.confirm')} busy={busy}
          onCancel={() => setDeleting(false)} onConfirm={() => void remove()} />
      )}
    </>
  )
}
