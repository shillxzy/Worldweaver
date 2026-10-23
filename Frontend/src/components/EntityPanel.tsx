import { useState } from 'react'
import type { ReactNode } from 'react'
import { useAccess } from '../access'
import { bannerBackground, charactersApi } from '../api/characters'
import { ApiError } from '../api/client'
import { factionsApi } from '../api/factions'
import { relationshipsApi } from '../api/relationships'
import type { Character, CharacterStatus, Faction, Membership, Precision, Relationship, RelationshipKind } from '../api/types'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'
import { describeParsed, parseWorldDate } from '../worldDate'
import { CropUpload, Lightbox } from './ImageCropper'
import { ErrorState, Loading } from './Ui'

const STATUSES: CharacterStatus[] = ['alive', 'dead', 'missing', 'unknown', 'other']
const REL_KINDS: RelationshipKind[] = ['family', 'alliance', 'enmity', 'mentorship', 'subordination', 'acquaintance', 'membership', 'other']
/** Statuses for which a date of death makes sense. */
const HAS_DEATH: CharacterStatus[] = ['dead', 'missing']

export type OpenEntity = (type: 'character' | 'faction', id: number) => void

/** Section header bar of the infobox ("Характеристики", "Фракції", …). */
export function InfoSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="info-section">
      <h4 className="info-bar">{title}</h4>
      {children}
    </section>
  )
}

export function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="info-row"><span className="info-label">{label}</span><div className="info-value">{children}</div></div>
}

/**
 * One free-text date field: the author types "19 жовтня 1999", "1999" or "212 рік"; the text is
 * kept as written and a comparable number is derived for consistency checks.
 */
function DateInput({ label, keyValue, onSave }: {
  label: string; keyValue: string | null
  onSave: (v: { label: string; key: string | null; precision: Precision }) => void
}) {
  const { t } = useApp()
  const { edit } = useAccess()
  const initial = label || (keyValue !== null ? String(Number(keyValue)) : '')
  const [text, setText] = useState(initial)
  const parsed = parseWorldDate(text)
  const save = () => {
    if (text.trim() === initial.trim()) return
    const p = parseWorldDate(text)
    onSave({ label: text.trim(), key: p.key === null ? null : String(p.key), precision: p.key === null ? 'unknown' : p.precision })
  }
  if (!edit) return <span>{initial || '—'}</span>
  return (
    <div className="date-input">
      <input className="prop-input" value={text} placeholder={t('date.ph')} onChange={(e) => setText(e.target.value)}
        onBlur={save} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />
      {text.trim() && (
        <small className={parsed.key === null ? 'warn' : 'muted'}>
          {parsed.key === null ? t('date.textOnly') : `✓ ${describeParsed(parsed)}`}
        </small>
      )}
    </div>
  )
}

/** Infobox of a character page: portrait, characteristics, factions, relationships. */
export function CharacterInfo({ worldId, characterId, onOpenEntity, children }: {
  worldId: number; characterId: number; onOpenEntity: OpenEntity; children?: ReactNode
}) {
  const { t, notify } = useApp()
  const data = useAsync(async (signal) => {
    const [character, factions] = await Promise.all([
      charactersApi.get(worldId, characterId).catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) return undefined // the record was deleted elsewhere
        throw err
      }),
      factionsApi.list(worldId, signal),
    ])
    return { character, factions }
  }, [worldId, characterId])
  const [viewing, setViewing] = useState(false)
  const { busy, run } = useBusy()
  const { edit } = useAccess()
  const c = data.data?.character

  const setCharacter = (saved: Character) => data.setData((prev) => ({ ...prev!, character: saved }))
  const patch = (body: Parameters<typeof charactersApi.update>[2]) => void run(async () => {
    try { setCharacter(await charactersApi.update(worldId, characterId, body)) } catch (err) { notify(errorText(err), 'error') }
  })

  if (data.loading && !data.data) return <Loading />
  if (data.error) return <ErrorState error={data.error} onRetry={data.reload} />
  if (!c) return <p className="muted">{t('enc.entityMissing')}</p>

  const changeStatus = (status: CharacterStatus) => {
    // A living (or unknown) character has no date of death: clear it so checks stay consistent.
    const clearDeath = !HAS_DEATH.includes(status) && (c.death_key !== null || c.death_label)
    patch(clearDeath ? { status, death_key: null, death_label: '', death_precision: 'unknown' } : { status })
  }
  const portrait = charactersApi.portraitUrl(worldId, c)

  return (
    <>
      <div className="info-portrait">
        {c.has_portrait
          ? <button type="button" className="portrait-btn" onClick={() => setViewing(true)} aria-label={t('cf.viewPortrait')}><img src={portrait} alt={c.name} /></button>
          : <div className="portrait-empty">{c.name[0]}</div>}
        {edit && <div className="portrait-acts">
          <CropUpload aspect={1} outputWidth={900} className="link" onUpload={async (file) => {
            try { setCharacter(await charactersApi.uploadPortrait(worldId, c.id, file)) } catch (err) { notify(errorText(err), 'error') }
          }}>{c.has_portrait ? t('cf.changePortrait') : t('cf.uploadPortrait')}</CropUpload>
          {c.has_portrait && <button className="link" onClick={() => void run(async () => {
            try { await charactersApi.removePortrait(worldId, c.id); setCharacter({ ...c, has_portrait: false }) } catch (err) { notify(errorText(err), 'error') }
          })}>{t('cf.removePortrait')}</button>}
        </div>}
        {viewing && <Lightbox src={portrait} alt={c.name} onClose={() => setViewing(false)} />}
      </div>

      <InfoSection title={t('info.characteristics')}>
        <InfoRow label={t('cf.status')}>
          <select className="info-select" value={c.status} disabled={busy || !edit} onChange={(e) => changeStatus(e.target.value as CharacterStatus)}>
            {STATUSES.map((s) => <option key={s} value={s}>{t('status.' + s)}</option>)}
          </select>
        </InfoRow>
        <InfoRow label={t('info.birth')}>
          <DateInput key={`b-${c.updated_at}`} label={c.birth_label} keyValue={c.birth_key}
            onSave={(v) => patch({ birth_label: v.label, birth_key: v.key, birth_precision: v.precision })} />
        </InfoRow>
        {HAS_DEATH.includes(c.status) && (
          <InfoRow label={c.status === 'dead' ? t('info.death') : t('info.deathIfKnown')}>
            <DateInput key={`d-${c.updated_at}`} label={c.death_label} keyValue={c.death_key}
              onSave={(v) => patch({ death_label: v.label, death_key: v.key, death_precision: v.precision })} />
          </InfoRow>
        )}
        {children}
      </InfoSection>

      <InfoSection title={t('cf.factions')}>
        <div className="prop-tags">
          {c.memberships.map((m) => (
            <span key={m.id} className="tag" style={{ ['--t' as string]: m.faction_color }}>
              <button className="link tag-link" onClick={() => onOpenEntity('faction', m.faction)}>{m.faction_name}</button>{m.role ? ` · ${m.role}` : ''}
              {edit && <button className="icon-btn" aria-label={t('ui.delete')} onClick={() => void run(async () => {
                try { await factionsApi.removeMembership(worldId, m.id); setCharacter({ ...c, memberships: c.memberships.filter((x) => x.id !== m.id) }) } catch (err) { notify(errorText(err), 'error') }
              })}>×</button>}
            </span>
          ))}
          {c.memberships.length === 0 && !edit && <span className="muted">—</span>}
          {edit && <select className="info-select add" value="" onChange={(e) => {
            const id = Number(e.target.value)
            if (!id) return
            void run(async () => {
              try {
                const m: Membership = await factionsApi.addMembership(worldId, { character: c.id, faction: id })
                const f = data.data?.factions.find((x) => x.id === id)
                setCharacter({ ...c, memberships: [...c.memberships, { ...m, faction_color: f?.color ?? '#e879a8' }] })
              } catch (err) { notify(errorText(err), 'error') }
            })
          }}>
            <option value="">+ {t('info.addFaction')}</option>
            {data.data?.factions.filter((f) => !c.memberships.some((m) => m.faction === f.id)).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>}
        </div>
      </InfoSection>

      <InfoRelations worldId={worldId} entity={{ type: 'character', id: c.id }} onOpenEntity={onOpenEntity} />
    </>
  )
}

/** Infobox of a faction page: colour, members, relationships. */
export function FactionInfo({ worldId, factionId, onOpenEntity, children }: {
  worldId: number; factionId: number; onOpenEntity: OpenEntity; children?: ReactNode
}) {
  const { t, notify } = useApp()
  const data = useAsync(async (signal) => {
    const [factions, members] = await Promise.all([factionsApi.list(worldId, signal), factionsApi.memberships(worldId, { faction: factionId })])
    return { faction: factions.find((f) => f.id === factionId), members }
  }, [worldId, factionId])
  const f: Faction | undefined = data.data?.faction
  const { edit } = useAccess()
  if (data.loading && !data.data) return <Loading />
  if (data.error) return <ErrorState error={data.error} onRetry={data.reload} />
  if (!f) return <p className="muted">{t('enc.entityMissing')}</p>
  const patch = (body: Partial<Pick<Faction, 'color' | 'emblem'>>) =>
    factionsApi.update(worldId, f.id, body).then((saved) => data.setData((prev) => ({ ...prev!, faction: saved }))).catch((err) => notify(errorText(err), 'error'))
  return (
    <>
      <InfoSection title={t('info.characteristics')}>
        <InfoRow label={t('ui.color')}>
          <input className="info-color" type="color" defaultValue={f.color} disabled={!edit} onBlur={(e) => { if (e.target.value !== f.color) void patch({ color: e.target.value }) }} />
        </InfoRow>
        {children}
      </InfoSection>
      <InfoSection title={t('info.members')}>
        <div className="prop-tags">
          {data.data?.members.length === 0 && <span className="muted">—</span>}
          {data.data?.members.map((m) => (
            <span key={m.id} className="tag"><button className="link tag-link" onClick={() => onOpenEntity('character', m.character)}>{m.character_name}</button>{m.role ? ` · ${m.role}` : ''}</span>
          ))}
        </div>
      </InfoSection>
      <InfoRelations worldId={worldId} entity={{ type: 'faction', id: f.id }} onOpenEntity={onOpenEntity} />
    </>
  )
}

/** Relationships grouped by kind ("Родина: …", "Союзники: …") with a compact add row. */
function InfoRelations({ worldId, entity, onOpenEntity }: { worldId: number; entity: { type: 'character' | 'faction'; id: number }; onOpenEntity: OpenEntity }) {
  const { t, notify } = useApp()
  const rels = useAsync<Relationship[]>(() => relationshipsApi.list(worldId, { entity_type: entity.type, entity_id: entity.id }), [worldId, entity.type, entity.id])
  const options = useAsync(async (signal) => {
    const [cs, fs] = await Promise.all([charactersApi.list(worldId, {}, signal), factionsApi.list(worldId, signal)])
    return [
      ...cs.map((c) => ({ key: `character:${c.id}`, label: c.name })),
      ...fs.map((f) => ({ key: `faction:${f.id}`, label: f.name })),
    ].filter((o) => o.key !== `${entity.type}:${entity.id}`)
  }, [worldId, entity.type, entity.id])
  const { edit } = useAccess()
  const [adding, setAdding] = useState(false)
  const [kind, setKind] = useState<RelationshipKind>('family')
  const [target, setTarget] = useState('')
  const { busy, run } = useBusy()

  const groups = new Map<RelationshipKind, { rel: Relationship; other: Relationship['source'] }[]>()
  for (const r of rels.data ?? []) {
    const outgoing = r.source.type === entity.type && r.source.id === entity.id
    groups.set(r.kind, [...(groups.get(r.kind) ?? []), { rel: r, other: outgoing ? r.target : r.source }])
  }

  const add = () => void run(async () => {
    const [type, id] = target.split(':')
    try {
      await relationshipsApi.create(worldId, { kind, source: entity, target: { type: type as 'character' | 'faction', id: Number(id) } })
      setTarget(''); setAdding(false); rels.reload()
    } catch (err) { notify(errorText(err), 'error') }
  })

  return (
    <InfoSection title={t('rel.title')}>
      {groups.size === 0 && !adding && <p className="muted">{t('info.noRelations')}</p>}
      {[...groups.entries()].map(([k, items]) => (
        <InfoRow key={k} label={t('relGroup.' + k)}>
          <span className="prop-tags">
            {items.map(({ rel, other }) => (
              <span key={rel.id} className="tag" title={rel.description || undefined}>
                {other.type === 'character' || other.type === 'faction'
                  ? <button className="link tag-link" onClick={() => onOpenEntity(other.type as 'character' | 'faction', other.id)}>{other.label}</button>
                  : other.label}
                {edit && <button className="icon-btn" aria-label={t('ui.delete')} onClick={() => void run(async () => {
                  try { await relationshipsApi.remove(worldId, rel.id); rels.reload() } catch (err) { notify(errorText(err), 'error') }
                })}>×</button>}
              </span>
            ))}
          </span>
        </InfoRow>
      ))}
      {adding ? (
        <div className="info-add">
          <select className="info-select" value={kind} onChange={(e) => setKind(e.target.value as RelationshipKind)}>
            {REL_KINDS.map((k) => <option key={k} value={k}>{t('relKind.' + k)}</option>)}
          </select>
          <select className="info-select" value={target} onChange={(e) => setTarget(e.target.value)} autoFocus>
            <option value="">{t('rel.choose')}</option>
            {options.data?.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
          <button className="btn-ghost small" disabled={!target || busy} onClick={add}>{t('ui.add')}</button>
          <button className="link" onClick={() => setAdding(false)}>{t('ui.cancel')}</button>
        </div>
      ) : edit && (
        <button className="link add-prop" onClick={() => setAdding(true)}>+ {t('info.addRelation')}</button>
      )}
    </InfoSection>
  )
}

/**
 * Wide banner across the top of a character page (also used on the character's card): an uploaded
 * image, else the chosen colour, else a colour derived from the name. Editors change it on hover.
 */
export function CharacterBanner({ worldId, characterId }: { worldId: number; characterId: number }) {
  const { t, notify } = useApp()
  const { edit } = useAccess()
  const data = useAsync<Character>(() => charactersApi.get(worldId, characterId), [worldId, characterId])
  const { busy, run } = useBusy()
  const c = data.data
  if (!c) return <div className="page-banner" />

  const save = (action: () => Promise<Character>) => void run(async () => {
    try { data.setData(await action()) } catch (err) { notify(errorText(err), 'error') }
  })
  return (
    <div className="page-banner" style={{ background: bannerBackground(worldId, c) }}>
      {edit && (
        <div className="banner-tools">
          {!c.has_banner && (
            <label className="banner-tool" title={t('banner.color')}>
              <input type="color" value={c.banner_color || '#7a3b8f'} disabled={busy}
                onChange={(e) => data.setData({ ...c, banner_color: e.target.value })}
                onBlur={(e) => save(() => charactersApi.update(worldId, c.id, { banner_color: e.target.value }))} />
              {t('banner.color')}
            </label>
          )}
          {c.banner_color && !c.has_banner && (
            <button className="banner-tool" disabled={busy} onClick={() => save(() => charactersApi.update(worldId, c.id, { banner_color: '' }))}>
              {t('banner.resetColor')}
            </button>
          )}
          <CropUpload aspect={5} outputWidth={1600} className="banner-tool" onUpload={async (file) => {
            try { data.setData(await charactersApi.uploadBanner(worldId, c.id, file)) } catch (err) { notify(errorText(err), 'error') }
          }}>{c.has_banner ? t('banner.change') : t('banner.upload')}</CropUpload>
          {c.has_banner && (
            <button className="banner-tool" disabled={busy} onClick={() => save(async () => {
              await charactersApi.removeBanner(worldId, c.id)
              return { ...c, has_banner: false }
            })}>{t('banner.remove')}</button>
          )}
        </div>
      )}
    </div>
  )
}
