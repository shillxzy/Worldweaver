import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { charactersApi } from '../api/characters'
import { chaptersApi } from '../api/chapters'
import { ApiError } from '../api/client'
import { factionsApi } from '../api/factions'
import { loreApi } from '../api/lore'
import { timelineApi } from '../api/timeline'
import type { Book, ParticipantRole, Precision, TimelineEvent } from '../api/types'
import { TimeFields } from '../components/EntityForms'
import Header from '../components/Header'
import { Confirm, Empty, ErrorState, FieldError, Loading, Modal } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'

const ROLES: ParticipantRole[] = ['participant', 'mentioned', 'posthumous']
const num = (v: string | null) => (v === null ? '' : String(Number(v)))

function useWorldRefs(worldId: number, bookId: number) {
  return useAsync(async (signal) => {
    const [characters, factions, lore, chapters] = await Promise.all([
      charactersApi.list(worldId, {}, signal), factionsApi.list(worldId, signal), loreApi.list(worldId, {}, signal), chaptersApi.list(bookId, signal),
    ])
    return { characters, factions, lore, chapters }
  }, [worldId, bookId])
}

export default function Timeline({ book }: { book: Book }) {
  const { t } = useApp()
  const worldId = book.world
  const data = useAsync(async (signal) => {
    const [events, chronology, dependencies] = await Promise.all([
      timelineApi.list(worldId, signal), timelineApi.chronology(worldId, signal), timelineApi.dependencies(worldId, signal),
    ])
    return { events, chronology, dependencies }
  }, [worldId])
  const [editing, setEditing] = useState<{ event?: TimelineEvent } | null>(null)

  const ordered = useMemo(() => {
    if (!data.data) return []
    const byId = new Map(data.data.events.map((e) => [e.id, e]))
    return data.data.chronology.order.map((id) => byId.get(id)).filter((e): e is TimelineEvent => Boolean(e))
  }, [data.data])

  const label = (e: TimelineEvent) => {
    const start = e.start_label || (e.start_key !== null ? num(e.start_key) : '')
    const end = e.end_label || (e.end_key !== null ? num(e.end_key) : '')
    const approx = e.precision === 'approximate' ? '≈ ' : ''
    if (!start) return t('tl.undated')
    return approx + start + (end ? ` — ${end}` : '')
  }

  return (
    <>
      <div className="page-head">
        <Header title={t('s.timeline')} sub={t('tl.sub')} />
        <button className="btn" onClick={() => setEditing({})}>+ {t('tl.add')}</button>
      </div>
      <ErrorState error={data.error} onRetry={data.reload} />
      {data.data?.chronology.has_cycle && <p className="field-error">{t('tl.cycle')}</p>}
      {data.loading && !data.data ? <Loading /> : ordered.length === 0 ? (
        <Empty title={t('tl.emptyTitle')} text={t('tl.emptyText')} action={<button className="btn" onClick={() => setEditing({})}>+ {t('tl.add')}</button>} />
      ) : (
        <div className="timeline">
          {ordered.map((e) => {
            const after = data.data!.dependencies.filter((d) => d.after === e.id)
            return (
              <button className="ev" key={e.id} onClick={() => setEditing({ event: e })}>
                <small>{label(e)}</small>
                <h3>{e.title}</h3>
                {e.description && <p>{e.description}</p>}
                {e.participants.length > 0 && (
                  <div className="ev-tags">{e.participants.map((p) => (
                    <span key={p.character} className="tag">{p.character_name}{p.role !== 'participant' ? ` · ${t('role.' + p.role)}` : ''}</span>
                  ))}</div>
                )}
                {after.length > 0 && <p className="muted">{t('tl.after')}: {after.map((d) => d.before_title).join(', ')}</p>}
              </button>
            )
          })}
        </div>
      )}
      {editing && data.data && (
        <EventForm book={book} event={editing.event} events={data.data.events} dependencies={data.data.dependencies}
          onClose={() => setEditing(null)} onSaved={data.reload} />
      )}
    </>
  )
}

function EventForm({ book, event, events, dependencies, onClose, onSaved }: {
  book: Book; event?: TimelineEvent; events: TimelineEvent[]; dependencies: { id: number; before: number; after: number; before_title: string }[]
  onClose: () => void; onSaved: () => void
}) {
  const { t, notify } = useApp()
  const worldId = book.world
  const refs = useWorldRefs(worldId, book.id)
  const [form, setForm] = useState({
    title: event?.title ?? '', description: event?.description ?? '',
    start_key: num(event?.start_key ?? null), start_label: event?.start_label ?? '',
    end_key: num(event?.end_key ?? null), end_label: event?.end_label ?? '',
    precision: event?.precision ?? 'exact' as Precision, uncertainty: event ? String(Number(event.uncertainty)) : '0',
  })
  const [participants, setParticipants] = useState(event?.participants.map((p) => ({ character: p.character, role: p.role })) ?? [])
  const [factions, setFactions] = useState<number[]>(event?.factions ?? [])
  const [lore, setLore] = useState<number[]>(event?.lore_entries ?? [])
  const [chapters, setChapters] = useState<number[]>(event?.chapters ?? [])
  const [newDep, setNewDep] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [deleting, setDeleting] = useState(false)
  const { busy, run } = useBusy()
  const prerequisites = event ? dependencies.filter((d) => d.after === event.id) : []

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const data = {
        ...form, start_key: form.start_key.trim() || null, end_key: form.end_key.trim() || null, uncertainty: form.uncertainty || '0',
        participants, factions, lore_entries: lore, chapters,
      }
      try {
        if (event) await timelineApi.update(worldId, event.id, data)
        else await timelineApi.create(worldId, data)
        onSaved(); onClose()
      } catch (err) { setError(err instanceof ApiError ? err : new ApiError(0, 'client', String(err))) }
    })
  }

  const addDependency = () => {
    if (!event || !newDep) return
    void run(async () => {
      try { await timelineApi.addDependency(worldId, { before: Number(newDep), after: event.id }); setNewDep(''); onSaved() } catch (err) { notify(errorText(err), 'error') }
    })
  }

  const toggle = (list: number[], set: (v: number[]) => void, id: number) => set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id])

  return (
    <Modal title={event ? event.title : t('tl.add')} onClose={onClose} wide>
      <form className="form" onSubmit={submit}>
        <label>{t('ui.title')}<input className="field" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} autoFocus /></label>
        <label>{t('ui.description')}<textarea className="field" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
        <div className="row2">
          <TimeFields label={t('tl.start')} keyValue={form.start_key} labelValue={form.start_label} precision={form.precision}
            error={error?.field('start_key')}
            onChange={(p) => setForm({ ...form, start_key: p.key ?? form.start_key, start_label: p.label ?? form.start_label, precision: p.precision ?? form.precision })} />
          <TimeFields label={t('tl.end')} keyValue={form.end_key} labelValue={form.end_label} error={error?.field('end_key')}
            onChange={(p) => setForm({ ...form, end_key: p.key ?? form.end_key, end_label: p.label ?? form.end_label })} />
        </div>
        {form.precision === 'approximate' && (
          <label>{t('tl.uncertainty')}<input className="field" inputMode="decimal" value={form.uncertainty} onChange={(e) => setForm({ ...form, uncertainty: e.target.value })} />
            <FieldError text={error?.field('uncertainty')} /></label>
        )}
        <small className="muted">{t('tl.keyHint')}</small>
        {refs.loading && !refs.data ? <Loading /> : refs.data && (
          <>
            <fieldset>
              <legend>{t('tl.participants')}</legend>
              {participants.map((p, i) => (
                <div className="fact-row" key={p.character}>
                  <span>{refs.data!.characters.find((c) => c.id === p.character)?.name}</span>
                  <select className="field" value={p.role} onChange={(e) => setParticipants(participants.map((x, j) => (j === i ? { ...x, role: e.target.value as ParticipantRole } : x)))}>
                    {ROLES.map((r) => <option key={r} value={r}>{t('role.' + r)}</option>)}
                  </select>
                  <button type="button" className="icon-btn" onClick={() => setParticipants(participants.filter((_, j) => j !== i))} aria-label="remove">×</button>
                </div>
              ))}
              <select className="field" value="" onChange={(e) => e.target.value && setParticipants([...participants, { character: Number(e.target.value), role: 'participant' }])}>
                <option value="">+ {t('tl.addParticipant')}</option>
                {refs.data.characters.filter((c) => !participants.some((p) => p.character === c.id)).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <FieldError text={error?.field('participants')} />
            </fieldset>
            <fieldset className="chips">
              <legend>{t('tl.links')}</legend>
              {refs.data.factions.map((f) => <button type="button" key={'f' + f.id} className={'tab' + (factions.includes(f.id) ? ' on' : '')} onClick={() => toggle(factions, setFactions, f.id)}>{f.name}</button>)}
              {refs.data.lore.map((l) => <button type="button" key={'l' + l.id} className={'tab' + (lore.includes(l.id) ? ' on' : '')} onClick={() => toggle(lore, setLore, l.id)}>{l.title}</button>)}
              {refs.data.chapters.map((c) => <button type="button" key={'c' + c.id} className={'tab' + (chapters.includes(c.id) ? ' on' : '')} onClick={() => toggle(chapters, setChapters, c.id)}>📖 {c.title}</button>)}
            </fieldset>
          </>
        )}
        {event && (
          <fieldset>
            <legend>{t('tl.after')}</legend>
            {prerequisites.map((d) => (
              <div className="fact-row" key={d.id}>
                <span>{d.before_title}</span>
                <button type="button" className="icon-btn" aria-label="remove" onClick={() => void run(async () => {
                  try { await timelineApi.removeDependency(worldId, d.id); onSaved() } catch (err) { notify(errorText(err), 'error') }
                })}>×</button>
              </div>
            ))}
            <div className="fact-row">
              <select className="field" value={newDep} onChange={(e) => setNewDep(e.target.value)}>
                <option value="">{t('tl.chooseBefore')}</option>
                {events.filter((x) => x.id !== event.id && !prerequisites.some((d) => d.before === x.id)).map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
              </select>
              <button type="button" className="btn-ghost" disabled={!newDep || busy} onClick={addDependency}>{t('ui.add')}</button>
            </div>
          </fieldset>
        )}
        {error && <p className="field-error">{error.details ? t('ui.checkFields') : error.message}</p>}
        <div className="acts">
          {event && <button type="button" className="btn-ghost danger-text" onClick={() => setDeleting(true)}>{t('ui.delete')}</button>}
          <span className="spacer" />
          <button type="button" className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
          <button className="btn" disabled={busy}>{t('ui.save')}</button>
        </div>
      </form>
      {deleting && event && (
        <Confirm title={t('ui.confirmDelete')} text={event.title} confirmLabel={t('ui.delete')} busy={busy} onCancel={() => setDeleting(false)}
          onConfirm={() => void run(async () => {
            try { await timelineApi.remove(worldId, event.id); onSaved(); onClose() } catch (err) { notify(errorText(err), 'error') }
          })} />
      )}
    </Modal>
  )
}
