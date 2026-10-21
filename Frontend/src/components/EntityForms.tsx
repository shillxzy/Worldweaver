import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { charactersApi } from '../api/characters'
import type { CharacterInput } from '../api/characters'
import { ApiError } from '../api/client'
import { factionsApi } from '../api/factions'
import { loreApi } from '../api/lore'
import { relationshipsApi } from '../api/relationships'
import type { Character, CharacterStatus, Faction, LoreCategory, LoreEntry, Precision, Relationship, RelationshipKind } from '../api/types'
import { LORE_CATEGORIES } from '../data/projects'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'
import { CropUpload, Lightbox } from './ImageCropper'
import { Confirm, FieldError, Modal } from './Ui'

const STATUSES: CharacterStatus[] = ['alive', 'dead', 'missing', 'unknown', 'other']
const PRECISIONS: Precision[] = ['exact', 'approximate', 'unknown']
const REL_KINDS: RelationshipKind[] = ['alliance', 'enmity', 'family', 'subordination', 'membership', 'acquaintance', 'mentorship', 'other']

const toErr = (err: unknown) => (err instanceof ApiError ? err : new ApiError(0, 'client', String(err)))
const keyOrNull = (v: string) => (v.trim() === '' ? null : v.trim())

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

function FormShell({ title, onClose, onSubmit, busy, error, onDelete, children, wide }: {
  title: string; onClose: () => void; onSubmit: (e: FormEvent) => void; busy: boolean; error: ApiError | null
  onDelete?: () => void; children: ReactNode; wide?: boolean
}) {
  const { t } = useApp()
  return (
    <Modal title={title} onClose={onClose} wide={wide}>
      <form className="form" onSubmit={onSubmit}>
        {children}
        {error && <p className="field-error">{error.details ? t('ui.checkFields') : error.message}</p>}
        <div className="acts">
          {onDelete && <button type="button" className="btn-ghost danger-text" onClick={onDelete}>{t('ui.delete')}</button>}
          <span className="spacer" />
          <button type="button" className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
          <button className="btn" disabled={busy}>{t('ui.save')}</button>
        </div>
      </form>
    </Modal>
  )
}

function useDelete(remove: () => Promise<unknown>, onDone: () => void) {
  const { t, notify } = useApp()
  const [asking, setAsking] = useState(false)
  const { busy, run } = useBusy()
  const dialog = asking ? (
    <Confirm title={t('ui.confirmDelete')} text={t('ui.deleteText')} confirmLabel={t('ui.delete')} busy={busy}
      onCancel={() => setAsking(false)}
      onConfirm={() => void run(async () => {
        try { await remove(); notify(t('ui.deleted')); onDone() } catch (err) { notify(errorText(err), 'error') }
      })} />
  ) : null
  return { ask: () => setAsking(true), dialog }
}

// ---------------------------------------------------------------------------------------------

export function CharacterForm({ worldId, character, onClose, onSaved }: {
  worldId: number; character?: Character; onClose: () => void; onSaved: () => void
}) {
  const { t, notify } = useApp()
  const c = character
  const [form, setForm] = useState({
    name: c?.name ?? '', aliases: c?.aliases.join(', ') ?? '', summary: c?.summary ?? '', biography: c?.biography ?? '',
    personality: c?.personality ?? '', appearance: c?.appearance ?? '', goals: c?.goals ?? '', abilities: c?.abilities ?? '',
    age_text: c?.age_text ?? '', status: c?.status ?? 'unknown', notes: c?.notes ?? '',
    birth_key: c?.birth_key ? String(Number(c.birth_key)) : '', birth_label: c?.birth_label ?? '', birth_precision: c?.birth_precision ?? 'exact',
    death_key: c?.death_key ? String(Number(c.death_key)) : '', death_label: c?.death_label ?? '', death_precision: c?.death_precision ?? 'exact',
  })
  const [facts, setFacts] = useState(c?.facts ?? [])
  const [error, setError] = useState<ApiError | null>(null)
  const { busy, run } = useBusy()
  const factions = useAsync<Faction[]>((signal) => factionsApi.list(worldId, signal), [worldId])
  const [memberships, setMemberships] = useState(c?.memberships ?? [])
  const [newFaction, setNewFaction] = useState('')
  const [newRole, setNewRole] = useState('')
  const del = useDelete(() => charactersApi.remove(worldId, c!.id), () => { onSaved(); onClose() })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const data: CharacterInput = {
        ...form,
        status: form.status as CharacterStatus,
        birth_precision: form.birth_precision as Precision, death_precision: form.death_precision as Precision,
        aliases: form.aliases.split(',').map((a) => a.trim()).filter(Boolean),
        birth_key: keyOrNull(form.birth_key), death_key: keyOrNull(form.death_key),
        facts: facts.filter((f) => f.label.trim()),
      }
      try {
        if (c) await charactersApi.update(worldId, c.id, data)
        else await charactersApi.create(worldId, data)
        onSaved(); onClose()
      } catch (err) { setError(toErr(err)) }
    })
  }

  const [portrait, setPortrait] = useState({ has: c?.has_portrait ?? false, version: c?.updated_at ?? '' })
  const [viewing, setViewing] = useState(false)
  const portraitSrc = c ? charactersApi.portraitUrl(worldId, { id: c.id, updated_at: portrait.version }) : ''
  const upload = async (file: File) => {
    if (!c) return
    try {
      const saved = await charactersApi.uploadPortrait(worldId, c.id, file)
      setPortrait({ has: true, version: saved.updated_at })
      notify(t('ui.saved'))
      onSaved()
    } catch (err) { notify(errorText(err), 'error') }
  }

  const addMembership = () => {
    if (!c || !newFaction) return
    void run(async () => {
      try {
        const m = await factionsApi.addMembership(worldId, { character: c.id, faction: Number(newFaction), role: newRole })
        const f = factions.data?.find((x) => x.id === m.faction)
        setMemberships([...memberships, { ...m, faction_color: f?.color ?? '#e879a8' }])
        setNewFaction(''); setNewRole(''); onSaved()
      } catch (err) { notify(errorText(err), 'error') }
    })
  }

  const removeMembership = (id: number) => void run(async () => {
    try { await factionsApi.removeMembership(worldId, id); setMemberships(memberships.filter((m) => m.id !== id)); onSaved() } catch (err) { notify(errorText(err), 'error') }
  })

  const text = (k: keyof typeof form, multiline = false) => (
    <label>{t('cf.' + k)}
      {multiline ? <textarea className="field" value={form[k]} onChange={set(k)} /> : <input className="field" value={form[k]} onChange={set(k)} />}
      <FieldError text={error?.field(k)} />
    </label>
  )

  return (
    <FormShell title={c ? c.name : t('cf.new')} onClose={onClose} onSubmit={submit} busy={busy} error={error} onDelete={c ? del.ask : undefined} wide>
      {c && (
        <div className="portrait-row">
          {portrait.has
            ? <button type="button" className="av big av-btn" onClick={() => setViewing(true)} aria-label={t('cf.viewPortrait')}><img src={portraitSrc} alt={c.name} /></button>
            : <div className="av big">{c.name[0]}</div>}
          <div className="cover-acts">
            <CropUpload aspect={1} outputWidth={768} round onUpload={upload}>{portrait.has ? t('cf.changePortrait') : t('cf.uploadPortrait')}</CropUpload>
            {portrait.has && <button type="button" className="link" onClick={() => void run(async () => {
              try { await charactersApi.removePortrait(worldId, c.id); setPortrait({ has: false, version: '' }); onSaved() } catch (err) { notify(errorText(err), 'error') }
            })}>{t('cf.removePortrait')}</button>}
          </div>
          {viewing && <Lightbox src={portraitSrc} alt={c.name} onClose={() => setViewing(false)} />}
        </div>
      )}
      <div className="row2">
        <label>{t('cf.name')}<input className="field" required value={form.name} onChange={set('name')} autoFocus /><FieldError text={error?.field('name')} /></label>
        <label>{t('cf.status')}
          <select className="field" value={form.status} onChange={set('status')}>
            {STATUSES.map((s) => <option key={s} value={s}>{t('status.' + s)}</option>)}
          </select>
        </label>
      </div>
      <label>{t('cf.aliases')}<input className="field" placeholder={t('cf.aliasesPh')} value={form.aliases} onChange={set('aliases')} /></label>
      {text('summary')}
      {text('biography', true)}
      <div className="row2">{text('personality', true)}{text('appearance', true)}</div>
      <div className="row2">{text('goals', true)}{text('abilities', true)}</div>
      {text('age_text')}
      <div className="row2">
        <TimeFields label={t('cf.birth')} keyValue={form.birth_key} labelValue={form.birth_label} precision={form.birth_precision as Precision}
          error={error?.field('birth_key')}
          onChange={(p) => setForm({ ...form, birth_key: p.key ?? form.birth_key, birth_label: p.label ?? form.birth_label, birth_precision: p.precision ?? form.birth_precision })} />
        <TimeFields label={t('cf.death')} keyValue={form.death_key} labelValue={form.death_label} precision={form.death_precision as Precision}
          error={error?.field('death_key')}
          onChange={(p) => setForm({ ...form, death_key: p.key ?? form.death_key, death_label: p.label ?? form.death_label, death_precision: p.precision ?? form.death_precision })} />
      </div>
      <fieldset className="facts">
        <legend>{t('cf.facts')}</legend>
        {facts.map((f, i) => (
          <div className="fact-row" key={i}>
            <input className="field" placeholder={t('cf.factLabel')} value={f.label} onChange={(e) => setFacts(facts.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <input className="field" placeholder={t('cf.factValue')} value={f.value} onChange={(e) => setFacts(facts.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
            <button type="button" className="icon-btn" onClick={() => setFacts(facts.filter((_, j) => j !== i))} aria-label="remove">×</button>
          </div>
        ))}
        <button type="button" className="link" onClick={() => setFacts([...facts, { label: '', value: '' }])}>+ {t('cf.addFact')}</button>
      </fieldset>
      {text('notes', true)}
      {c && (
        <>
          <fieldset>
            <legend>{t('cf.factions')}</legend>
            {memberships.map((m) => (
              <div className="fact-row" key={m.id}>
                <span className="tag" style={{ ['--t' as string]: m.faction_color }}>{m.faction_name}</span>
                <span className="muted">{m.role}</span>
                <button type="button" className="icon-btn" onClick={() => removeMembership(m.id)} aria-label="remove">×</button>
              </div>
            ))}
            <div className="fact-row">
              <select className="field" value={newFaction} onChange={(e) => setNewFaction(e.target.value)}>
                <option value="">{t('cf.chooseFaction')}</option>
                {factions.data?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
              <input className="field" placeholder={t('cf.role')} value={newRole} onChange={(e) => setNewRole(e.target.value)} />
              <button type="button" className="btn-ghost" disabled={!newFaction} onClick={addMembership}>{t('ui.add')}</button>
            </div>
          </fieldset>
          <RelationshipsEditor worldId={worldId} entity={{ type: 'character', id: c.id }} />
        </>
      )}
      {del.dialog}
    </FormShell>
  )
}

// ---------------------------------------------------------------------------------------------

export function FactionForm({ worldId, faction, onClose, onSaved }: { worldId: number; faction?: Faction; onClose: () => void; onSaved: () => void }) {
  const { t } = useApp()
  const [form, setForm] = useState({
    name: faction?.name ?? '', description: faction?.description ?? '', goals: faction?.goals ?? '',
    ideology: faction?.ideology ?? '', color: faction?.color ?? '#e879a8', emblem: faction?.emblem ?? '',
  })
  const [error, setError] = useState<ApiError | null>(null)
  const { busy, run } = useBusy()
  const del = useDelete(() => factionsApi.remove(worldId, faction!.id), () => { onSaved(); onClose() })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      try {
        if (faction) await factionsApi.update(worldId, faction.id, form)
        else await factionsApi.create(worldId, form)
        onSaved(); onClose()
      } catch (err) { setError(toErr(err)) }
    })
  }
  return (
    <FormShell title={faction ? faction.name : t('ff.new')} onClose={onClose} onSubmit={submit} busy={busy} error={error} onDelete={faction ? del.ask : undefined}>
      <label>{t('ui.title')}<input className="field" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus /></label>
      <label>{t('ui.description')}<textarea className="field" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
      <label>{t('ff.goals')}<textarea className="field" value={form.goals} onChange={(e) => setForm({ ...form, goals: e.target.value })} /></label>
      <label>{t('ff.ideology')}<textarea className="field" value={form.ideology} onChange={(e) => setForm({ ...form, ideology: e.target.value })} /></label>
      <div className="row2">
        <label>{t('ui.color')}<input className="field color" type="color" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} /><FieldError text={error?.field('color')} /></label>
        <label>{t('ff.emblem')}<input className="field" maxLength={8} value={form.emblem} onChange={(e) => setForm({ ...form, emblem: e.target.value })} /></label>
      </div>
      {faction && <RelationshipsEditor worldId={worldId} entity={{ type: 'faction', id: faction.id }} />}
      {del.dialog}
    </FormShell>
  )
}

// ---------------------------------------------------------------------------------------------

export function LoreForm({ worldId, entry, defaultCategory, onClose, onSaved }: {
  worldId: number; entry?: LoreEntry; defaultCategory?: LoreCategory; onClose: () => void; onSaved: () => void
}) {
  const { t } = useApp()
  const [form, setForm] = useState({
    title: entry?.title ?? '', content: entry?.content ?? '', category: entry?.category ?? defaultCategory ?? 'history',
    custom_category: entry?.custom_category ?? '', tags: entry?.tags.join(', ') ?? '',
  })
  const [error, setError] = useState<ApiError | null>(null)
  const { busy, run } = useBusy()
  const del = useDelete(() => loreApi.remove(worldId, entry!.id), () => { onSaved(); onClose() })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const data = { ...form, category: form.category as LoreCategory, tags: form.tags.split(',').map((x) => x.trim()).filter(Boolean) }
      try {
        if (entry) await loreApi.update(worldId, entry.id, data)
        else await loreApi.create(worldId, data)
        onSaved(); onClose()
      } catch (err) { setError(toErr(err)) }
    })
  }
  return (
    <FormShell title={entry ? entry.title : t('lf.new')} onClose={onClose} onSubmit={submit} busy={busy} error={error} onDelete={entry ? del.ask : undefined} wide>
      <label>{t('ui.title')}<input className="field" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} autoFocus /></label>
      <div className="row2">
        <label>{t('lf.category')}
          <select className="field" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as LoreCategory })}>
            {LORE_CATEGORIES.map((cat) => <option key={cat} value={cat}>{t('cat.' + cat)}</option>)}
          </select>
        </label>
        {form.category === 'custom' && (
          <label>{t('lf.custom')}<input className="field" value={form.custom_category} onChange={(e) => setForm({ ...form, custom_category: e.target.value })} />
            <FieldError text={error?.field('custom_category')} /></label>
        )}
      </div>
      <label>{t('lf.content')}<textarea className="field tall" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} /></label>
      <label>{t('lf.tags')}<input className="field" placeholder={t('lf.tagsPh')} value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></label>
      {entry && <RelationshipsEditor worldId={worldId} entity={{ type: 'lore', id: entry.id }} />}
      {del.dialog}
    </FormShell>
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
