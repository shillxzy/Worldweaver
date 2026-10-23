import { useEffect, useState } from 'react'
import { authApi } from '../api/auth'
import { ApiError } from '../api/client'
import type { SearchResult } from '../api/types'
import { worldsApi } from '../api/worlds'
import { SECTIONS } from '../data/projects'
import { navigate, projectPath } from '../router'
import type { Route } from '../router'
import { useApp } from '../settings-context'
import type { Section } from '../types'
import CoverArt from './CoverArt'
import Icon from './Icon'
import ShareDialog from './ShareDialog'

const SECTION_FOR: Record<SearchResult['type'], Section> = {
  book: 'overview', page: 'encyclopedia', character: 'encyclopedia', faction: 'encyclopedia', lore: 'encyclopedia', event: 'timeline', chapter: 'book',
}

function GlobalSearch() {
  const { t, books } = useApp()
  const [q, setQ] = useState('')
  const [results, setResults] = useState<SearchResult[] | null>(null)
  const [error, setError] = useState('')

  const query = q.trim()
  useEffect(() => {
    if (query.length < 2) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      worldsApi.globalSearch(query, controller.signal)
        .then((r) => { setResults(r.results); setError('') })
        .catch((err: unknown) => { if (!(err instanceof ApiError && err.isAborted)) setError(err instanceof ApiError ? err.message : String(err)) })
    }, 300)
    return () => { clearTimeout(timer); controller.abort() }
  }, [query])
  const shown = query.length >= 2 ? results : null

  const open = (r: SearchResult) => {
    const bookId = r.type === 'book' ? r.id : r.type === 'chapter' ? r.book : books.find((b) => b.world === r.world)?.id
    if (!bookId) return
    setQ('')
    const focus = r.type === 'book' ? undefined : `${r.type}:${r.id}`
    navigate(projectPath(bookId, SECTION_FOR[r.type], focus))
  }

  return (
    <div className="search">
      <Icon n="search" />
      <input className="field" placeholder={t('nav.search')} value={q} onChange={(e) => setQ(e.target.value)} />
      {(shown || (error && query.length >= 2)) && (
        <div className="search-pop">
          {error && <p className="field-error">{error}</p>}
          {shown?.length === 0 && <p className="muted">{t('ui.nothing')}</p>}
          {shown?.map((r) => (
            <button key={`${r.type}${r.id}`} onClick={() => open(r)}>
              <b>{r.title}</b><small>{t('search.' + r.type)}{r.snippet ? ' · ' + r.snippet.slice(0, 60) : ''}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Sidebar({ route }: { route: Route }) {
  const { t, user, logout, books, refreshBooks } = useApp()
  const project = route.page === 'project' ? books.find((b) => b.id === route.bookId) : undefined
  const [sharing, setSharing] = useState(false)

  return (
    <aside className="sidebar">
      <div className="ws"><Icon n="logo" />Worldweaver</div>
      <GlobalSearch />

      <p className="label">{t('nav.books')}</p>
      <button className={'nav' + (route.page === 'library' ? ' on' : '')} onClick={() => navigate('/')}>
        <Icon n="library" />{t('nav.allBooks')}
      </button>
      {books.map((b) => (
        <button key={b.id} className={'nav' + (project?.id === b.id ? ' on' : '')} onClick={() => navigate(projectPath(b.id))}>
          <span className="cv"><CoverArt p={b} /></span><span className="nav-text">{b.title}</span>
        </button>
      ))}

      {project && (
        <>
          <p className="label project-label">
            <span>{project.title}</span>
            {project.my_role !== 'owner' && <span className={'role-pill role-' + project.my_role} title={t('sh.ownerIs').replace('{name}', project.owner_name)}>{t('role.' + project.my_role)}</span>}
          </p>
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className={'nav' + (route.page === 'project' && route.section === s.id ? ' on' : '')}
              onClick={() => navigate(projectPath(project.id, s.id))}
            >
              <Icon n={s.icon} />{t('s.' + s.id)}
            </button>
          ))}
          <button className="nav" onClick={() => setSharing(true)}><Icon n="share" />{t('sh.open')}</button>
          {sharing && (
            <ShareDialog book={project} onClose={() => setSharing(false)} onAccessChanged={(change) => {
              setSharing(false)
              // After leaving, the project is gone from this account; after a handover the role changes.
              void refreshBooks().then(() => { if (change === 'left') navigate('/') })
            }} />
          )}
        </>
      )}

      <div className="spacer" />
      <button className={'nav' + (route.page === 'settings' ? ' on' : '')} onClick={() => navigate('/settings')}>
        <Icon n="settings" />{t('nav.settings')}
      </button>
      <button className={'userchip' + (route.page === 'profile' ? ' on' : '')} onClick={() => navigate('/profile')}>
        {user.has_avatar
          ? <img className="av-sm" src={authApi.avatarUrl(user)} alt="" />
          : <span className="av-sm">{user.name[0]?.toUpperCase()}</span>}
        <span className="uc-text"><b>{user.name}</b><small>{user.email}</small></span>
      </button>
      <button className="nav" onClick={logout}><Icon n="logout" />{t('nav.logout')}</button>
    </aside>
  )
}
