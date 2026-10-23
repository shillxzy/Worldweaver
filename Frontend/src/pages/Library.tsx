import { useState } from 'react'
import BookForm from '../components/BookForm'
import CoverArt from '../components/CoverArt'
import Header from '../components/Header'
import Icon from '../components/Icon'
import { Empty, Loading } from '../components/Ui'
import { navigate, projectPath } from '../router'
import { useApp } from '../settings-context'
import { InvitesInbox } from './Join'
import { accentVars } from '../utils'

export default function Library() {
  const { t, books, booksLoading, refreshBooks, notify } = useApp()
  const [creating, setCreating] = useState(false)

  return (
    <>
      <div className="page-head">
        <Header title={t('lib.title')} sub={t('lib.sub')} />
        <button className="btn" onClick={() => setCreating(true)}>+ {t('lib.new')}</button>
      </div>
      <InvitesInbox />
      {booksLoading && books.length === 0 ? <Loading /> : books.length === 0 ? (
        <Empty title={t('lib.emptyTitle')} text={t('lib.emptyText')}
          action={<button className="btn" onClick={() => setCreating(true)}>+ {t('lib.new')}</button>} />
      ) : (
        <div className="books">
          {books.map((p) => (
            <button key={p.id} className="bk" style={accentVars(p.accent)} onClick={() => navigate(projectPath(p.id))}>
              <div className="cover-art"><CoverArt p={p} /></div>
              <div className="bk-info">
                <h3 className="bk-title">{p.title}</h3>
                <span className="bk-genre">{p.genre || p.world_name}</span>
                {p.my_role !== 'owner' && (
                  <span className="bk-shared" title={t('sh.ownerIs').replace('{name}', p.owner_name)}>
                    <Icon n="users" />{t('lib.sharedBy').replace('{name}', p.owner_name)} · {t('role.' + p.my_role)}
                  </span>
                )}
                <div className="meta">
                  <span><Icon n="read" />{p.chapters_count} {t('bk.chapters')}</span>
                  <span><Icon n="pen" />{(p.word_count ?? 0).toLocaleString()} {t('ov.words')}</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
      {creating && (
        <BookForm onClose={() => setCreating(false)} onSaved={(b) => {
          setCreating(false)
          notify(t('ui.saved'))
          void refreshBooks().then(() => navigate(projectPath(b.id)))
        }} />
      )}
    </>
  )
}
