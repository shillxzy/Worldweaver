import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { AccessContext, accessFor } from './access'
import { authApi } from './api/auth'
import { booksApi } from './api/books'
import { ApiError } from './api/client'
import type { Book, User } from './api/types'
import Sidebar from './components/Sidebar'
import { Loading, Toasts } from './components/Ui'
import { dict } from './i18n'
import { navigate, parseHash } from './router'
import type { Route } from './router'
import { AppContext } from './settings-context'
import type { Lang, Theme, Toast, ToastKind } from './settings-context'
import { accentVars } from './utils'
import Analysis from './pages/Analysis'
import Auth from './pages/Auth'
import BookPage from './pages/Book'
import Characters from './pages/Characters'
import Diary from './pages/Diary'
import Encyclopedia from './pages/Encyclopedia'
import Join from './pages/Join'
import Library from './pages/Library'
import Overview from './pages/Overview'
import Profile from './pages/Profile'
import PublicSite from './pages/PublicSite'
import Settings from './pages/Settings'
import Timeline from './pages/Timeline'

// The graph canvas (React Flow) is loaded only when the graph section is opened.
const Graph = lazy(() => import('./pages/Graph'))

const EMPTY_USER: User = { id: 0, name: '', email: '', bio: '', has_avatar: false, avatar_version: 0, date_joined: '' }

function stored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null
    return v && allowed.includes(v) ? v : fallback
  } catch {
    return fallback
  }
}

function remember(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* storage unavailable: preference stays in memory */ }
}

function renderRoute(route: Route, book: Book | undefined): ReactNode {
  switch (route.page) {
    case 'profile': return <Profile />
    case 'settings': return <Settings />
    case 'library': return <Library />
    case 'join': return <Join token={route.token} />
    case 'public': return null
    case 'project': {
      if (!book) return null
      switch (route.section) {
        case 'overview': return <Overview book={book} />
        case 'encyclopedia': return <Encyclopedia key={book.id} book={book} focus={route.focus} pageId={route.pageId} />
        case 'characters': return <Characters book={book} />
        case 'graph': return <Suspense fallback={<Loading />}><Graph book={book} /></Suspense>
        case 'diary': return <Diary book={book} />
        case 'book': return <BookPage book={book} focus={route.focus} />
        case 'timeline': return <Timeline book={book} />
        case 'analysis': return <Analysis book={book} />
      }
    }
  }
}

type AuthState = 'checking' | 'anonymous' | 'authed' | 'unreachable'

export default function App() {
  const [auth, setAuth] = useState<AuthState>('checking')
  const [user, setUser] = useState<User>(EMPTY_USER)
  const [theme, setThemeState] = useState<Theme>(() => stored('ww-theme', ['dark', 'light'], 'dark'))
  const [lang, setLangState] = useState<Lang>(() => stored('ww-lang', ['uk', 'en'], 'uk'))
  const [route, setRoute] = useState<Route>(parseHash)
  const [books, setBooks] = useState<Book[]>([])
  const [booksLoading, setBooksLoading] = useState(true)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [online, setOnline] = useState(() => navigator.onLine)
  const toastId = useRef(0)

  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  useEffect(() => { document.documentElement.lang = lang }, [lang])
  // Browser tab: "<book> · Worldweaver" inside a project, the app name elsewhere.
  const titledBook = route.page === 'project' ? books.find((b) => b.id === route.bookId)?.title : undefined
  useEffect(() => { document.title = titledBook ? `${titledBook} · Worldweaver` : 'Worldweaver' }, [titledBook])
  useEffect(() => {
    const read = () => setRoute(parseHash())
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('hashchange', read)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      window.removeEventListener('hashchange', read)
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [])

  const notify = useCallback((text: string, kind: ToastKind = 'ok') => {
    const id = ++toastId.current
    setToasts((list) => [...list, { id, kind, text }])
    setTimeout(() => setToasts((list) => list.filter((x) => x.id !== id)), kind === 'error' ? 6000 : 2600)
  }, [])

  // booksLoading starts as true and only covers the first load; later refreshes update in place.
  const refreshBooks = useCallback(async () => {
    try {
      setBooks(await booksApi.list())
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setAuth('anonymous')
      else notify(err instanceof ApiError ? err.message : String(err), 'error')
    } finally {
      setBooksLoading(false)
    }
  }, [notify])

  const onSession = useCallback(async (me: User) => {
    setUser(me)
    setAuth('authed')
    void refreshBooks()
    try {
      const prefs = await authApi.settings()
      setThemeState(prefs.theme); remember('ww-theme', prefs.theme)
      setLangState(prefs.language); remember('ww-lang', prefs.language)
    } catch { /* preferences are optional; local values stay */ }
  }, [refreshBooks])

  const onSessionError = useCallback((err: unknown) => {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setAuth('anonymous')
    else setAuth('unreachable')
  }, [])

  const checkSession = useCallback(() => authApi.me().then(onSession, onSessionError), [onSession, onSessionError])

  useEffect(() => {
    // Initial session check: state changes only in the promise callbacks.
    let cancelled = false
    authApi.me().then(
      (me) => { if (!cancelled) void onSession(me) },
      (err: unknown) => { if (!cancelled) onSessionError(err) },
    )
    return () => { cancelled = true }
  }, [onSession, onSessionError])


  const savePref = useCallback((data: { theme?: Theme; language?: Lang }) => {
    if (auth === 'authed') authApi.updateSettings(data).catch(() => notify(dict[lang]['ui.offline'], 'error'))
  }, [auth, lang, notify])

  const setTheme = useCallback((v: Theme) => { setThemeState(v); remember('ww-theme', v); savePref({ theme: v }) }, [savePref])
  const setLang = useCallback((v: Lang) => { setLangState(v); remember('ww-lang', v); savePref({ language: v }) }, [savePref])
  const t = useCallback((key: string) => dict[lang][key] ?? dict.uk[key] ?? key, [lang])

  const logout = useCallback(() => {
    authApi.logout().catch(() => undefined).finally(() => {
      setUser(EMPTY_USER); setBooks([]); setAuth('anonymous'); navigate('/')
    })
  }, [])
  const accountDeleted = useCallback(() => { setUser(EMPTY_USER); setBooks([]); setAuth('anonymous'); navigate('/') }, [])

  const ctx = useMemo(() => ({
    theme, setTheme, lang, setLang, t, user, setUser, logout, accountDeleted,
    books, booksLoading, refreshBooks, notify, online,
  }), [theme, setTheme, lang, setLang, t, user, logout, accountDeleted, books, booksLoading, refreshBooks, notify, online])

  // The public site is for everyone: no account, no session check, no app chrome.
  if (route.page === 'public') {
    return (
      <AppContext.Provider value={ctx}>
        <PublicSite token={route.token} chapterId={route.chapterId} pageId={route.pageId} />
        <Toasts toasts={toasts} />
      </AppContext.Provider>
    )
  }

  if (auth === 'checking') {
    return <AppContext.Provider value={ctx}><div className="boot"><Loading /></div></AppContext.Provider>
  }
  if (auth === 'unreachable') {
    return (
      <AppContext.Provider value={ctx}>
        <div className="boot">
          <div className="state error">
            <p>{t('ui.offline')}</p>
            <button className="btn" onClick={() => { setAuth('checking'); void checkSession() }}>{t('ui.retry')}</button>
          </div>
        </div>
      </AppContext.Provider>
    )
  }
  if (auth === 'anonymous') {
    return (
      <AppContext.Provider value={ctx}>
        {/* After signing in the hash is unchanged, so an invitation link continues to its join page. */}
        <Auth notice={route.page === 'join' ? t('join.signInFirst') : undefined}
          onEnter={(me) => { setUser(me); setAuth('authed'); void refreshBooks() }} />
        <Toasts toasts={toasts} />
      </AppContext.Provider>
    )
  }

  const book = route.page === 'project' ? books.find((b) => b.id === route.bookId) : undefined
  const missingBook = route.page === 'project' && !book && !booksLoading
  // Encyclopedia keeps one mounted layout while switching pages (the tree should not re-animate).
  const pageKey = route.page === 'project' ? `${route.bookId}${route.section}` : route.page

  return (
    <AppContext.Provider value={ctx}>
      <div className="app" style={book ? accentVars(book.accent) : undefined}>
        <Sidebar route={route} />
        <main className="main">
          {!online && <div className="offline-banner">{t('ui.offlineBanner')}</div>}
          <div className="page" key={pageKey}>
            {route.page === 'project' && !book && booksLoading && <Loading />}
            {missingBook ? <Library /> : (
              <AccessContext.Provider value={accessFor(book?.my_role)}>{renderRoute(route, book)}</AccessContext.Provider>
            )}
          </div>
        </main>
      </div>
      <Toasts toasts={toasts} />
    </AppContext.Provider>
  )
}
