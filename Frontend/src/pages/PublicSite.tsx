import type { ReactNode } from 'react'
import { publicApi } from '../api/collab'
import type { PublicChapter, PublicPage, PublicSite as Site } from '../api/types'
import DocView from '../components/DocView'
import Icon from '../components/Icon'
import { ErrorState, Loading } from '../components/Ui'
import { useAsync } from '../hooks'
import { navigate, publicPath } from '../router'
import { useApp } from '../settings-context'

/** Anonymous, read-only site of a world: only the books, chapters and pages its owner published. */
export default function PublicSite({ token, chapterId, pageId }: { token: string; chapterId?: number; pageId?: number }) {
  const { t } = useApp()
  const site = useAsync<Site>((signal) => publicApi.site(token, signal), [token])
  if (site.loading && !site.data) return <div className="boot"><Loading /></div>
  if (site.error) {
    return (
      <div className="boot">
        <div className="state">
          <h2>{t('pub.unavailable')}</h2>
          <p className="muted">{t('pub.unavailableText')}</p>
        </div>
      </div>
    )
  }
  const s = site.data!
  const openPage = (id: number) => navigate(publicPath(token, 'page', id))

  return (
    <div className="pub-site">
      <header className="pub-head">
        <button className="link pub-brand" onClick={() => navigate(publicPath(token))}><Icon n="logo" />{s.world.name}</button>
        <span className="muted">{t('pub.readOnly')}</span>
      </header>
      <div className="pub-layout">
        <nav className="pub-nav">
          {s.books.map((b) => (
            <section key={b.id}>
              <p className="label">{b.title}</p>
              {b.chapters.map((c) => (
                <button key={c.id} className={'nav' + (chapterId === c.id ? ' on' : '')} onClick={() => navigate(publicPath(token, 'chapter', c.id))}>
                  <span className="nav-text">{c.title}</span>
                </button>
              ))}
              {b.chapters.length === 0 && <small className="muted">{t('pub.noChapters')}</small>}
            </section>
          ))}
          {s.pages.length > 0 && (
            <section>
              <p className="label">{t('s.encyclopedia')}</p>
              <PublicTree pages={s.pages} parent={null} depth={0} current={pageId} onOpen={openPage} />
            </section>
          )}
        </nav>
        <main className="pub-main">
          {chapterId ? <ChapterView token={token} id={chapterId} onPageLink={openPage} />
            : pageId ? <PageView token={token} id={pageId} onPageLink={openPage} />
              : <Home site={s} token={token} />}
        </main>
      </div>
    </div>
  )
}

function PublicTree({ pages, parent, depth, current, onOpen }: {
  pages: Site['pages']; parent: number | null; depth: number; current?: number; onOpen: (id: number) => void
}) {
  return (
    <>
      {pages.filter((p) => p.parent === parent).map((p) => (
        <div key={p.id}>
          <button className={'nav' + (current === p.id ? ' on' : '')} style={{ paddingLeft: 10 + depth * 14 }} onClick={() => onOpen(p.id)}>
            <span className="tree-icon">{p.icon || '·'}</span><span className="nav-text">{p.title}</span>
          </button>
          {depth < 8 && <PublicTree pages={pages} parent={p.id} depth={depth + 1} current={current} onOpen={onOpen} />}
        </div>
      ))}
    </>
  )
}

function Home({ site, token }: { site: Site; token: string }) {
  const { t } = useApp()
  return (
    <div className="pub-home">
      <h1>{site.world.name}</h1>
      {site.world.genre && <span className="tag">{site.world.genre}</span>}
      {site.world.description && <p className="sub">{site.world.description}</p>}
      <div className="pub-books">
        {site.books.map((b) => (
          <article key={b.id} className="pub-book">
            {b.has_cover
              ? <img src={publicApi.imageUrl(token, 'book-cover', b.id, b.updated_at)} alt={b.title} />
              : <div className="pub-cover" style={{ background: `linear-gradient(160deg, ${b.accent}, #111)` }}>{b.title}</div>}
            <div>
              <h3>{b.title}</h3>
              {b.description && <p className="muted">{b.description}</p>}
              {b.chapters[0] && <button className="btn" onClick={() => navigate(publicPath(token, 'chapter', b.chapters[0].id))}>{t('pub.startReading')}</button>}
            </div>
          </article>
        ))}
      </div>
      {site.books.length === 0 && site.pages.length === 0 && <p className="muted">{t('pub.empty')}</p>}
    </div>
  )
}

function ChapterView({ token, id, onPageLink }: { token: string; id: number; onPageLink: (id: number) => void }) {
  const { t } = useApp()
  const chapter = useAsync<PublicChapter>((signal) => publicApi.chapter(token, id, signal), [token, id])
  if (chapter.loading && !chapter.data) return <Loading />
  if (chapter.error) return <ErrorState error={chapter.error} />
  const c = chapter.data!
  return (
    <article className="paper reader pub-reader">
      <small className="muted">{c.book.title}</small>
      <h2>{c.title}</h2>
      <DocView doc={c.content} onPageLink={onPageLink} />
      <div className="pager">
        <button className="link" disabled={!c.prev} onClick={() => c.prev && navigate(publicPath(token, 'chapter', c.prev))}>{t('bk.prev')}</button>
        <button className="link" disabled={!c.next} onClick={() => c.next && navigate(publicPath(token, 'chapter', c.next))}>{t('bk.next')}</button>
      </div>
    </article>
  )
}

function PageView({ token, id, onPageLink }: { token: string; id: number; onPageLink: (id: number) => void }) {
  const { t } = useApp()
  const page = useAsync<PublicPage>((signal) => publicApi.page(token, id, signal), [token, id])
  if (page.loading && !page.data) return <Loading />
  if (page.error) return <ErrorState error={page.error} />
  const p = page.data!
  const shown = (v: unknown): string => {
    if (Array.isArray(v)) return v.map((x) => (typeof x === 'object' && x && 'title' in x ? String((x as { title: string }).title) : String(x))).join(', ')
    if (typeof v === 'object' && v && 'label' in v) return String((v as { label: string }).label)
    if (typeof v === 'boolean') return v ? '✓' : '—'
    return String(v)
  }
  return (
    <article className="page-view pub-page">
      {p.has_cover && <div className="page-cover"><img src={publicApi.imageUrl(token, 'page-cover', p.id, p.updated_at)} alt="" /></div>}
      <div className="page-header"><span className="page-icon">{p.icon}</span><h1 className="page-title">{p.title}</h1></div>
      <div className="page-columns">
        <div className="page-main"><DocView doc={p.content} onPageLink={onPageLink} className="page-prose" /></div>
        <aside className="infobox">
          {p.character?.has_portrait && <img className="pub-portrait" src={publicApi.imageUrl(token, 'portrait', p.id, p.updated_at)} alt={p.title} />}
          {(p.character || p.properties.length > 0 || p.aliases.length > 0) && (
            <section className="info-section">
              <h4 className="info-bar">{t('info.characteristics')}</h4>
              {p.character && p.character.status !== 'unknown' && <Row label={t('cf.status')}>{t('status.' + p.character.status)}</Row>}
              {p.character?.birth_label && <Row label={t('cf.birth')}>{p.character.birth_label}</Row>}
              {p.character?.death_label && <Row label={t('cf.death')}>{p.character.death_label}</Row>}
              {p.aliases.length > 0 && <Row label={t('info.aliases')}>{p.aliases.join(', ')}</Row>}
              {p.properties.map((prop, i) => (
                <Row key={i} label={prop.label}>
                  {(prop.kind === 'page' || prop.kind === 'pages') && Array.isArray(prop.value)
                    ? (prop.value as { id: number; title: string }[]).map((x) => <button key={x.id} className="link tag-link" onClick={() => onPageLink(x.id)}>{x.title} </button>)
                    : shown(prop.value)}
                </Row>
              ))}
            </section>
          )}
          {p.children.length > 0 && (
            <section className="info-section">
              <h4 className="info-bar">{t('enc.subpages')}</h4>
              {p.children.map((c) => <button key={c.id} className="page-link-row" onClick={() => onPageLink(c.id)}>{c.icon} {c.title}</button>)}
            </section>
          )}
        </aside>
      </div>
    </article>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="info-row"><span className="info-label">{label}</span><div className="info-value">{children}</div></div>
}
