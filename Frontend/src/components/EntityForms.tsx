import { useState } from 'react'
import { charactersApi } from '../api/characters'
import { factionsApi } from '../api/factions'
import { relationshipsApi } from '../api/relationships'
import type { Precision, Relationship, RelationshipKind } from '../api/types'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'
import { FieldError } from './Ui'

const PRECISIONS: Precision[] = ['exact', 'approximate', 'unknown']
const REL_KINDS: RelationshipKind[] = ['alliance', 'enmity', 'family', 'subordination', 'membership', 'acquaintance', 'mentorship', 'other']

/** A world-time point: comparable number + display label + precision. */
export function TimeFields({ label, keyValue, labelValue, precision, onChange, error }: {
  label: string; keyValue: string; labelValue: string; precision?: Precision; error?: string
  onChange: (patch: { key?: string; label?: string; precision?: Precision }) => void
}) {
  const { t } = useApp()
  return (
    <fieldset className="timefields">
      <legend>{label}</legend>
      <input className="field" inputMode="decimal" placeholder={t('time.key')} value={keyValue}
        onChange={(e) => onChange({ key: e.target.value.replace(',', '.') })} />
      <input className="field" placeholder={t('time.label')} value={labelValue} onChange={(e) => onChange({ label: e.target.value })} />
      {precision !== undefined && (
        <select className="field" value={precision} onChange={(e) => onChange({ precision: e.target.value as Precision })}>
          {PRECISIONS.map((p) => <option key={p} value={p}>{t('precision.' + p)}</option>)}
        </select>
      )}
      <FieldError text={error} />
    </fieldset>
  )
}

// ---------------------------------------------------------------------------------------------

/** Typed relationships of one entity (character / faction / lore) with other world entities. */
export function RelationshipsEditor({ worldId, entity }: { worldId: number; entity: { type: 'character' | 'faction' | 'lore'; id: number } }) {
  const { t, notify } = useApp()
  const rels = useAsync<Relationship[]>(() => relationshipsApi.list(worldId, { entity_type: entity.type, entity_id: entity.id }), [worldId, entity.type, entity.id])
  const others = useAsync<{ type: 'character' | 'faction'; id: number; label: string }[]>(async (signal) => {
    const [cs, fs] = await Promise.all([charactersApi.list(worldId, {}, signal), factionsApi.list(worldId, signal)])
    return [
      ...cs.map((c) => ({ type: 'character' as const, id: c.id, label: c.name })),
      ...fs.map((f) => ({ type: 'faction' as const, id: f.id, label: f.name })),
    ].filter((o) => !(o.type === entity.type && o.id === entity.id))
  }, [worldId, entity.type, entity.id])
  const [kind, setKind] = useState<RelationshipKind>('alliance')
  const [target, setTarget] = useState('')
  const [description, setDescription] = useState('')
  const { busy, run } = useBusy()

  const add = () => void run(async () => {
    const [type, id] = target.split(':')
    try {
      await relationshipsApi.create(worldId, { kind, source: entity, target: { type: type as 'character' | 'faction', id: Number(id) }, description })
      setTarget(''); setDescription(''); rels.reload()
    } catch (err) { notify(errorText(err), 'error') }
  })

  return (
    <fieldset>
      <legend>{t('rel.title')}</legend>
      {rels.data?.map((r) => {
        const outgoing = r.source.type === entity.type && r.source.id === entity.id
        const other = outgoing ? r.target : r.source
        return (
          <div className="fact-row" key={r.id}>
            <span className="tag">{t('relKind.' + r.kind)}</span>
            <span>{outgoing ? '→' : '←'} {other.label}</span>
            <span className="muted">{r.description}</span>
            <button type="button" className="icon-btn" aria-label="remove"
              onClick={() => void run(async () => { try { await relationshipsApi.remove(worldId, r.id); rels.reload() } catch (err) { notify(errorText(err), 'error') } })}>×</button>
          </div>
        )
      })}
      <div className="fact-row">
        <select className="field" value={kind} onChange={(e) => setKind(e.target.value as RelationshipKind)}>
          {REL_KINDS.map((k) => <option key={k} value={k}>{t('relKind.' + k)}</option>)}
        </select>
        <select className="field" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">{t('rel.choose')}</option>
          {others.data?.map((o) => <option key={`${o.type}:${o.id}`} value={`${o.type}:${o.id}`}>{o.label}</option>)}
        </select>
        <input className="field" placeholder={t('ui.description')} value={description} onChange={(e) => setDescription(e.target.value)} />
        <button type="button" className="btn-ghost" disabled={!target || busy} onClick={add}>{t('ui.add')}</button>
      </div>
    </fieldset>
  )
}
