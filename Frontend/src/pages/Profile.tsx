import { useState } from 'react'
import type { FormEvent } from 'react'
import { authApi } from '../api/auth'
import { ApiError } from '../api/client'
import type { World } from '../api/types'
import { worldsApi } from '../api/worlds'
import Header from '../components/Header'
import Icon from '../components/Icon'
import { FieldError } from '../components/Ui'
import { useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'

export default function Profile() {
  const { t, user, setUser, books } = useApp()
  const [form, setForm] = useState({ name: user.name, email: user.email, bio: user.bio })
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const { busy, run } = useBusy()
  const worlds = useAsync<World[]>((signal) => worldsApi.list(signal), [])

  const chars = worlds.data?.reduce((n, w) => n + w.characters_count, 0)
  const entries = worlds.data?.reduce((n, w) => n + w.characters_count + w.factions_count + w.lore_count, 0)

  const save = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      setError(null)
      try {
        setUser(await authApi.updateMe({ name: form.name.trim() || user.name, email: form.email.trim(), bio: form.bio }))
        setSaved(true)
        setTimeout(() => setSaved(false), 1800)
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(0, 'client', String(err)))
      }
    })
  }

  return (
    <>
      <Header title={t('pr.title')} sub={t('pr.sub')} />
      <div className="me">
        <div className="av big">{user.name[0]?.toUpperCase()}</div>
        <div>
          <h3 style={{ fontSize: 20 }}>{user.name}</h3>
          <p>{user.email}</p>
          <div className="stats">
            <div><b>{books.length}</b><span>{t('pr.books')}</span></div>
            <div><b>{chars ?? '—'}</b><span>{t('pr.chars')}</span></div>
            <div><b>{entries ?? '—'}</b><span>{t('pr.entries')}</span></div>
          </div>
        </div>
      </div>
      <form className="form" onSubmit={save}>
        <label>{t('pr.name')}<input className="field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /><FieldError text={error?.field('name')} /></label>
        <label>{t('pr.email')}<input className="field" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /><FieldError text={error?.field('email')} /></label>
        <label>{t('pr.bio')}<textarea className="field" placeholder={t('pr.bioPh')} value={form.bio} onChange={(e) => setForm({ ...form, bio: e.target.value })} /></label>
        {error && !error.details && <p className="field-error">{error.message}</p>}
        <div className="save-row">
          <button className="btn" disabled={busy}>{t('pr.save')}</button>
          {saved && <span className="ok"><Icon n="check" />{t('pr.saved')}</span>}
        </div>
      </form>
    </>
  )
}
