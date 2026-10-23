import { useState } from 'react'
import { charactersApi } from '../api/characters'
import { pagesApi } from '../api/pages'
import type { Book, Character } from '../api/types'
import Header from '../components/Header'
import { Lightbox } from '../components/ImageCropper'
import Icon from '../components/Icon'
import { Empty, ErrorState, Loading } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { navigate, pagePath } from '../router'
import { useApp } from '../settings-context'
import { cssVars } from '../utils'

const hue = (s: string) => [...s].reduce((a, c) => a + c.charCodeAt(0) * 7, 0) % 360
const HONORIFIC = /^(Доктор|Докторка|Капітан|Пан|Пані|Лорд|Леді|Сер)\s+/i

/** Gallery of characters. Each card opens the character's encyclopedia page (its own URL). */
export default function Characters({ book }: { book: Book }) {
  const { t, notify } = useApp()
  const worldId = book.world
  const [query, setQuery] = useState('')
  const [viewing, setViewing] = useState<Character | null>(null)
  const characters = useAsync<Character[]>((signal) => charactersApi.list(worldId, {}, signal), [worldId])
  const { busy, run } = useBusy()

  const openPage = (c: Character) => {
    if (c.page_id) { navigate(pagePath(book.id, c.page_id)); return }
    pagesApi.byEntity(worldId, 'character', c.id).then((p) => navigate(pagePath(book.id, p.id))).catch((err) => notify(errorText(err), 'error'))
  }
  const create = () => void run(async () => {
    try {
      const page = await pagesApi.create(worldId, { title: t('cf.new'), template: 'character' })
      navigate(pagePath(book.id, page.id))
    } catch (err) { notify(errorText(err), 'error') }
  })

  const q = query.trim().toLocaleLowerCase('uk')
  const list = (characters.data ?? []).filter((c) => !q || [c.name, ...c.aliases, c.summary].join(' ').toLocaleLowerCase('uk').includes(q))

  return (
    <>
      <div className="page-head">
        <Header title={t('s.characters')} sub={`${t('ch.sub')} «${book.title}».`} />
        <button className="btn" disabled={busy} onClick={create}>+ {t('cf.new')}</button>
      </div>
      <input className="field search-field" placeholder={t('ui.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
      <ErrorState error={characters.error} onRetry={characters.reload} />
      {characters.loading && !characters.data ? <Loading /> : characters.data?.length === 0 ? (
        <Empty title={t('chars.emptyTitle')} text={t('chars.emptyText')} action={<button className="btn" onClick={create}>+ {t('cf.new')}</button>} />
      ) : (
        <div className="grid">
          {list.map((c) => {
            const h = hue(c.name)
            return (
              <button className="char" key={c.id} onClick={() => openPage(c)}>
                <div className="banner" style={{ background: `linear-gradient(135deg, hsl(${h} 45% 32%), hsl(${h + 50} 45% 14%))` }} />
                <div className="char-body">
                  {c.has_portrait
                    ? <img className="av zoomable" src={charactersApi.portraitUrl(worldId, c)} alt={c.name}
                        onClick={(e) => { e.stopPropagation(); setViewing(c) }} />
                    : <div className="av" style={{ background: `hsl(${h} 45% 38%)` }}>{c.name.replace(HONORIFIC, '')[0]}</div>}
                  <h3>{c.name}</h3>
                  {c.status !== 'unknown' && <small className={'status ' + c.status}>{t('status.' + c.status)}</small>}
                  {c.summary && <p>{c.summary}</p>}
                  {c.memberships.map((m) => (
                    <span key={m.id} className="tag" style={cssVars({ '--t': m.faction_color })}><Icon n="shield" />{m.faction_name}</span>
                  ))}
                </div>
              </button>
            )
          })}
        </div>
      )}
      {viewing && <Lightbox src={charactersApi.portraitUrl(worldId, viewing)} alt={viewing.name} onClose={() => setViewing(null)} />}
    </>
  )
}
