import { useState } from 'react'
import { analysisApi } from '../api/analysis'
import { authApi } from '../api/auth'
import { ApiError } from '../api/client'
import { languageApi } from '../api/language'
import type { UserSettings } from '../api/types'
import Header from '../components/Header'
import Icon from '../components/Icon'
import { FieldError, Modal } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'
import type { Lang, Theme } from '../settings-context'

export default function Settings() {
  const { t, theme, setTheme, lang, setLang, accountDeleted, notify } = useApp()
  const [confirm, setConfirm] = useState(false)
  const [password, setPassword] = useState('')
  const [deleteError, setDeleteError] = useState('')
  const [pw, setPw] = useState({ old: '', next: '' })
  const [pwError, setPwError] = useState<ApiError | null>(null)
  const { busy, run } = useBusy()
  const prefs = useAsync<UserSettings>(() => authApi.settings(), [])
  const words = useAsync(() => languageApi.words(), [])
  const ai = useAsync((signal) => analysisApi.aiStatus(signal), [])
  const spell = useAsync(() => languageApi.status(), [])

  const themes: { id: Theme; icon: 'moon' | 'sun' }[] = [{ id: 'dark', icon: 'moon' }, { id: 'light', icon: 'sun' }]
  const langs: { id: Lang; label: string }[] = [{ id: 'uk', label: 'Українська' }, { id: 'en', label: 'English' }]

  const toggle = (key: 'quick_checks_enabled' | 'spellcheck_enabled') => void run(async () => {
    if (!prefs.data) return
    try { prefs.setData(await authApi.updateSettings({ [key]: !prefs.data[key] })) } catch (err) { notify(errorText(err), 'error') }
  })

  const deleteAccount = () => void run(async () => {
    try { await authApi.deleteAccount(password); accountDeleted() } catch (err) { setDeleteError(errorText(err)) }
  })

  const changePassword = () => void run(async () => {
    setPwError(null)
    try {
      await authApi.changePassword(pw.old, pw.next)
      setPw({ old: '', next: '' })
      notify(t('ui.saved'))
    } catch (err) { setPwError(err instanceof ApiError ? err : new ApiError(0, 'client', String(err))) }
  })

  return (
    <>
      <Header title={t('st.title')} sub={t('st.sub')} />

      <section>
        <p className="label first">{t('st.appearance')}</p>
        <div className="panel">
          <div className="set-row">
            <div><h3>{t('st.theme')}</h3><p>{t('st.themeDesc')}</p></div>
            <div className="seg">
              {themes.map((o) => (
                <button key={o.id} className={theme === o.id ? 'on' : ''} onClick={() => setTheme(o.id)}>
                  <Icon n={o.icon} />{t('st.' + o.id)}
                </button>
              ))}
            </div>
          </div>
          <div className="set-row">
            <div><h3>{t('st.language')}</h3><p>{t('st.langDesc')}</p></div>
            <div className="seg">
              {langs.map((o) => (
                <button key={o.id} className={lang === o.id ? 'on' : ''} onClick={() => setLang(o.id)}>
                  {o.id === lang && <Icon n="globe" />}{o.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section>
        <p className="label first">{t('st.writing')}</p>
        <div className="panel">
          <div className="set-row">
            <div><h3>{t('st.quick')}</h3><p>{t('st.quickDesc')}</p></div>
            <label className="switch"><input type="checkbox" checked={prefs.data?.quick_checks_enabled ?? true} disabled={!prefs.data || busy} onChange={() => toggle('quick_checks_enabled')} /><span /></label>
          </div>
          <div className="set-row">
            <div>
              <h3>{t('st.spell')}</h3><p>{t('st.spellDesc')}</p>
              {spell.data && !spell.data.available && <p className="warn">{spell.data.error}</p>}
            </div>
            <label className="switch"><input type="checkbox" checked={prefs.data?.spellcheck_enabled ?? true} disabled={!prefs.data || busy} onChange={() => toggle('spellcheck_enabled')} /><span /></label>
          </div>
          <div className="set-row">
            <div>
              <h3>{t('st.dictionary')}</h3>
              {words.data?.length === 0 && <p>{t('st.dictionaryEmpty')}</p>}
              <div className="chips">
                {words.data?.map((w) => (
                  <span key={w.id} className="tag">{w.word}
                    <button className="icon-btn" aria-label={t('ui.delete')} onClick={() => void languageApi.removeWord(w.id).then(words.reload).catch((err) => notify(errorText(err), 'error'))}>×</button>
                  </span>
                ))}
              </div>
            </div>
          </div>
          <div className="set-row">
            <div>
              <h3>{t('st.ai')}</h3><p>{t('st.aiDesc')}</p>
              {ai.data && (ai.data.available
                ? <p className="ok"><Icon n="check" />{t('an.aiReady')}: {ai.data.model}</p>
                : <p className="warn">{ai.data.server ? `${t('an.modelMissing')}: ${ai.data.model}` : t('an.aiOffline')}</p>)}
            </div>
          </div>
        </div>
      </section>

      <section>
        <p className="label first">{t('st.account')}</p>
        <div className="panel">
          <div className="set-row">
            <div className="form">
              <h3>{t('st.password')}</h3>
              <input className="field" type="password" autoComplete="current-password" placeholder={t('st.oldPw')} value={pw.old} onChange={(e) => setPw({ ...pw, old: e.target.value })} />
              <FieldError text={pwError?.field('old_password')} />
              <input className="field" type="password" autoComplete="new-password" placeholder={t('st.newPw')} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
              <FieldError text={pwError?.field('new_password')} />
              <button className="btn-ghost" disabled={busy || !pw.old || !pw.next} onClick={changePassword}>{t('ui.save')}</button>
            </div>
          </div>
        </div>
        <div className="panel danger" style={{ marginTop: 12 }}>
          <div className="set-row">
            <div><h3>{t('st.delete')}</h3><p>{t('st.deleteDesc')}</p></div>
            <button className="btn-danger" onClick={() => setConfirm(true)}><Icon n="trash" />{t('st.delete')}</button>
          </div>
        </div>
      </section>

      {confirm && (
        <Modal title={t('st.deleteTitle')} onClose={() => setConfirm(false)} footer={<>
          <button className="btn-ghost" onClick={() => setConfirm(false)}>{t('st.cancel')}</button>
          <button className="btn-danger" disabled={busy || !password} onClick={deleteAccount}>{t('st.confirm')}</button>
        </>}>
          <p>{t('st.deleteText')}</p>
          <input className="field" type="password" autoComplete="current-password" placeholder={t('auth.password')} value={password}
            onChange={(e) => { setPassword(e.target.value); setDeleteError('') }} />
          {deleteError && <p className="field-error">{deleteError}</p>}
        </Modal>
      )}
    </>
  )
}
