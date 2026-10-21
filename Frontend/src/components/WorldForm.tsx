import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../api/client'
import type { World } from '../api/types'
import { worldsApi } from '../api/worlds'
import { useBusy } from '../hooks'
import { useApp } from '../settings-context'
import { FieldError, Modal } from './Ui'

const FIELDS = ['name', 'genre', 'description', 'rules', 'tech_level', 'magic_system', 'time_unit_label', 'calendar_notes'] as const
type Field = (typeof FIELDS)[number]
const MULTILINE: Field[] = ['description', 'rules', 'magic_system', 'calendar_notes']

export default function WorldForm({ world, onClose, onSaved }: { world: World; onClose: () => void; onSaved: (w: World) => void }) {
  const { t } = useApp()
  const [form, setForm] = useState<Record<Field, string>>(() => Object.fromEntries(FIELDS.map((f) => [f, world[f] ?? ''])) as Record<Field, string>)
  const [error, setError] = useState<ApiError | null>(null)
  const { busy, run } = useBusy()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      try {
        onSaved(await worldsApi.update(world.id, form))
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(0, 'client', String(err)))
      }
    })
  }

  return (
    <Modal title={t('wf.title')} onClose={onClose} wide>
      <form className="form" onSubmit={submit}>
        {FIELDS.map((f) => (
          <label key={f}>{t('wf.' + f)}
            {MULTILINE.includes(f)
              ? <textarea className="field" value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
              : <input className="field" value={form[f]} required={f === 'name'} onChange={(e) => setForm({ ...form, [f]: e.target.value })} />}
            <FieldError text={error?.field(f)} />
          </label>
        ))}
        {error && !error.details && <p className="field-error">{error.message}</p>}
        <div className="acts">
          <button type="button" className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
          <button className="btn" disabled={busy}>{t('ui.save')}</button>
        </div>
      </form>
    </Modal>
  )
}
