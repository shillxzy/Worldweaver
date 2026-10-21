import { useMemo, useState } from 'react'
import { charactersApi } from '../api/characters'
import { factionsApi } from '../api/factions'
import { loreApi } from '../api/lore'
import type { Book, Character, Faction, LoreEntry } from '../api/types'
import { CharacterForm, FactionForm, LoreForm } from '../components/EntityForms'
import Header from '../components/Header'
import Icon from '../components/Icon'
import { Empty, ErrorState, Loading } from '../components/Ui'
import { CATEGORY_BY_KIND, KIND_BY_CATEGORY, TYPES, TYPE_META } from '../data/projects'
import { useAsync } from '../hooks'
import { useApp } from '../settings-context'
import type { EntryKind } from '../types'
import { cssVars } from '../utils'

type Row = { key: string; kind: EntryKind; name: string; desc: string; extra?: string; open: () => void }
type Editing =
  | { kind: 'character'; item?: Character }
  | { kind: 'faction'; item?: Faction }
  | { kind: 'lore'; item?: LoreEntry; category?: EntryKind }
  | null

export default function Encyclopedia({ book, focus }: { book: Book; focus?: string }) {
  const { t } = useApp()
  const worldId = book.world
  const [type, setType] = useState<'Усе' | EntryKind>('Усе')
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<Editing>(null)
  const [focusDismissed, setFocusDismissed] = useState(false)
  const [adding, setAdding] = useState(false)
  const data = useAsync(async (signal) => {
    const [characters, factions, lore] = await Promise.all([
      charactersApi.list(worldId, {}, signal), factionsApi.list(worldId, signal), loreApi.list(worldId, {}, signal),
    ])
    return { characters, factions, lore }
  }, [worldId])

  // A search result link (#…?focus=faction:ID / lore:ID) opens that entry once.
  const focused = useMemo<Editing>(() => {
    if (!focus || focusDismissed || !data.data) return null
    const [kind, id] = focus.split(':')
    const n = Number(id)
    const f = kind === 'faction' ? data.data.factions.find((x) => x.id === n) : undefined
    if (f) return { kind: 'faction', item: f }
    const l = kind === 'lore' ? data.data.lore.find((x) => x.id === n) : undefined
    return l ? { kind: 'lore', item: l } : null
  }, [focus, focusDismissed, data.data])
  const editing = chosen ?? focused
  const setEditing = (value: Editing) => { setChosen(value); if (!value) setFocusDismissed(true) }

  const rows = useMemo<Row[]>(() => {
    if (!data.data) return []
    const { characters, factions, lore } = data.data
    return [
      ...characters.map((c) => ({
        key: 'c' + c.id, kind: 'Персонаж' as EntryKind, name: c.name, desc: c.summary || c.biography.slice(0, 140),
        extra: [c.aliases.join(', '), c.biography, c.abilities].join(' '), open: () => setEditing({ kind: 'character', item: c }),
      })),
      ...factions.map((f) => ({
        key: 'f' + f.id, kind: 'Фракція' as EntryKind, name: f.name, desc: f.description.slice(0, 160),
        extra: f.goals + ' ' + f.ideology, open: () => setEditing({ kind: 'faction', item: f }),
      })),
      ...lore.map((l) => ({
        key: 'l' + l.id, kind: KIND_BY_CATEGORY[l.category] ?? ('Лор' as EntryKind), name: l.title,
        desc: l.content.slice(0, 160), extra: l.tags.join(' ') + ' ' + l.content, open: () => setEditing({ kind: 'lore', item: l }),
      })),
    ].sort((a, b) => a.name.localeCompare(b.name, 'uk'))
  }, [data.data])

  const q = query.trim().toLocaleLowerCase('uk')
  const list = rows.filter((r) => (type === 'Усе' || r.kind === type) && (!q || (r.name + ' ' + r.desc + ' ' + (r.extra ?? '')).toLocaleLowerCase('uk').includes(q)))
  const label = (k: string) => t(k === 'Усе' ? 'type.all' : 'type.' + k)

  const startAdd = (kind: EntryKind) => {
    setAdding(false)
    if (kind === 'Персонаж') setEditing({ kind: 'character' })
    else if (kind === 'Фракція') setEditing({ kind: 'faction' })
    else setEditing({ kind: 'lore', category: kind })
  }
  const saved = () => data.reload()

  return (
    <>
      <div className="page-head">
        <Header title={t('s.encyclopedia')} sub={`${t('enc.sub')} «${book.world_name}».`} />
        <div className="menu-wrap">
          <button className="btn" onClick={() => setAdding(!adding)}>+ {t('ui.add')}</button>
          {adding && (
            <div className="menu">
              {TYPES.slice(1).map((k) => <button key={k} onClick={() => startAdd(k as EntryKind)}><Icon n={TYPE_META[k as EntryKind].icon} />{label(k)}</button>)}
            </div>
          )}
        </div>
      </div>
      <div className="toolbar">
        <div className="tabs">
          {TYPES.map((k) => <button key={k} className={'tab' + (k === type ? ' on' : '')} onClick={() => setType(k)}>{label(k)}</button>)}
        </div>
        <input className="field search-field" placeholder={t('ui.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <ErrorState error={data.error} onRetry={data.reload} />
      {data.loading && !data.data ? <Loading /> : rows.length === 0 ? (
        <Empty title={t('enc.emptyTitle')} text={t('enc.emptyText')} action={<button className="btn" onClick={() => setAdding(true)}>+ {t('ui.add')}</button>} />
      ) : list.length === 0 ? <p className="muted">{t('ui.nothing')}</p> : (
        <div>
          {list.map((e) => {
            const m = TYPE_META[e.kind]
            return (
              <button className="row" key={e.key} style={cssVars({ '--t': m.color })} onClick={e.open}>
                <div className="chip"><Icon n={m.icon} /></div>
                <h3>{e.name}</h3>
                <span className="tag">{label(e.kind)}</span>
                <p>{e.desc}</p>
              </button>
            )
          })}
        </div>
      )}
      {editing?.kind === 'character' && <CharacterForm worldId={worldId} character={editing.item} onClose={() => setEditing(null)} onSaved={saved} />}
      {editing?.kind === 'faction' && <FactionForm worldId={worldId} faction={editing.item} onClose={() => setEditing(null)} onSaved={saved} />}
      {editing?.kind === 'lore' && (
        <LoreForm worldId={worldId} entry={editing.item} defaultCategory={editing.category ? CATEGORY_BY_KIND[editing.category] : undefined}
          onClose={() => setEditing(null)} onSaved={saved} />
      )}
    </>
  )
}
