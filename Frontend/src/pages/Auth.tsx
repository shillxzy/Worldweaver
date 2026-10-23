import { useState } from 'react'
import type { FormEvent } from 'react'
import { authApi } from '../api/auth'
import { ApiError } from '../api/client'
import type { User } from '../api/types'
import { FieldError } from '../components/Ui'
import { useBusy } from '../hooks'
import { P } from '../icons'
import { useApp } from '../settings-context'

export default function Auth({ onEnter, notice }: { onEnter: (user: User) => void; notice?: string }) {
  const { t } = useApp()
  const [mode, setMode] = useState<'register' | 'login'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const { busy, run } = useBusy()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      setError(null)
      try {
        const user = mode === 'register'
          ? await authApi.register({ name: name.trim(), email: email.trim(), password })
          : await authApi.login({ email: email.trim(), password })
        onEnter(user)
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(0, 'client', String(err)))
      }
    })
  }

  const register = mode === 'register'
  return (
    <div className="auth">
      <div className="auth-art"><svg viewBox="0 0 24 24"><path d={P.logo} /></svg></div>
      <div className="auth-form">
        <form className="auth-box" onSubmit={submit} noValidate>
          <h1>{t(register ? 'auth.title' : 'auth.loginTitle')}</h1>
          <p>{t(register ? 'auth.sub' : 'auth.loginSub')}</p>
          {notice && <p className="auth-notice">{notice}</p>}
          {register && (
            <>
              <input className="field" placeholder={t('auth.name')} value={name} autoComplete="name" required onChange={(e) => setName(e.target.value)} />
              <FieldError text={error?.field('name')} />
            </>
          )}
          <input className="field" type="email" placeholder={t('auth.email')} value={email} autoComplete="email" required onChange={(e) => setEmail(e.target.value)} />
          <FieldError text={error?.field('email')} />
          <input
            className="field" type="password" placeholder={t('auth.password')} value={password} required
            autoComplete={register ? 'new-password' : 'current-password'} onChange={(e) => setPassword(e.target.value)}
          />
          <FieldError text={error?.field('password')} />
          {register && !error?.field('password') && <small className="muted">{t('auth.pwHint')}</small>}
          {error && !error.details && <p className="field-error">{error.message}</p>}
          <button className="btn" type="submit" disabled={busy}>{busy ? t('ui.loading') : t(register ? 'auth.create' : 'auth.enter')}</button>
          <button className="link" type="button" onClick={() => { setMode(register ? 'login' : 'register'); setError(null) }}>
            {t(register ? 'auth.have' : 'auth.noAccount')}
          </button>
        </form>
      </div>
    </div>
  )
}
