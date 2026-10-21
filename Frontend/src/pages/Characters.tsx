import { useState } from 'react'
import { charactersApi } from '../api/characters'
import type { Book, Character } from '../api/types'
import { CharacterForm } from '../components/EntityForms'
import Header from '../components/Header'
import Icon from '../components/Icon'
import { Empty, ErrorState, Loading } from '../components/Ui'
import { useAsync } from '../hooks'
import { useApp } from '../settings-context'
import { cssVars } from '../utils'

const hue = (s: string) => [...s].reduce((a, c) => a + c.charCodeAt(0) * 7, 0) % 360
const HONORIFIC = /^(Доктор|Докторка|Капітан|Пан|Пані|Лорд|Леді|Сер)\s+/i

export default function Characters({ book, focus }: { book: Book; focus?: string }) {
  const { t } = useApp()
  const worldId = book.world
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<{ item?: Character } | null>(null)
  const [focusDismissed, setFocusDismissed] = useState(false)
  const characters = useAsync<Character[]>((signal) => charactersApi.list(worldId, {}, signal), [worldId])
  // A search result link (#…?focus=character:ID) opens that character once.
  const focused = !focusDismissed && focus?.startsWith('character:')
    ? characters.data?.find((x) => x.id === Number(focus.split(':')[1])) : undefined
  const editing = chosen ?? (focused ? { item: focused } : null)
  const setEditing = (value: { item?: Character } | null) => { setChosen(value); if (!value) setFocusDismissed(true) }

  const q = query.trim().toLocaleLowerCase('uk')
  const list = (characters.data ?? []).filter((c) => !q || [c.name, ...c.aliases, c.summary].join(' ').toLocaleLowerCase('uk').includes(q))

  return (
    <>
      <div className="page-head">
        <Header title={t('s.characters')} sub={`${t('ch.sub')} «${book.title}».`} />
        <button className="btn" onClick={() => setEditing({})}>+ {t('cf.new')}</button>
      </div>
      <input className="field search-field" placeholder={t('ui.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
      <ErrorState error={characters.error} onRetry={characters.reload} />
      {characters.loading && !characters.data ? <Loading /> : characters.data?.length === 0 ? (
        <Empty title={t('chars.emptyTitle')} text={t('chars.emptyText')} action={<button className="btn" onClick={() => setEditing({})}>+ {t('cf.new')}</button>} />
      ) : (
        <div className="grid">
          {list.map((c) => {
            const h = hue(c.name)
            return (
              <button className="char" key={c.id} onClick={() => setEditing({ item: c })}>
                <div className="banner" style={{ background: `linear-gradient(135deg, hsl(${h} 45% 32%), hsl(${h + 50} 45% 14%))` }} />
                <div className="char-body">
                  {c.has_portrait
                    ? <img className="av" src={charactersApi.portraitUrl(worldId, c)} alt={c.name} />
                    : <div className="av" style={{ background: `hsl(${h} 45% 38%)` }}>{c.name.replace(HONORIFIC, '')[0]}</div>}
                  <h3>{c.name}</h3>
                  {c.status !== 'unknown' && <small className={'status ' + c.status}>{t('status.' + c.status)}</small>}
                  <p>{c.summary || c.biography.slice(0, 120)}</p>
                  {c.memberships.map((m) => (
                    <span key={m.id} className="tag" style={cssVars({ '--t': m.faction_color })}><Icon n="shield" />{m.faction_name}</span>
                  ))}
                </div>
              </button>
            )
          })}
        </div>
      )}
      {editing && <CharacterForm worldId={worldId} character={editing.item} onClose={() => setEditing(null)} onSaved={characters.reload} />}
    </>
  )
}
