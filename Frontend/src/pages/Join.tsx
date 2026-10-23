import { collabApi } from '../api/collab'
import type { InvitePreview } from '../api/types'
import { ErrorState, Loading } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { navigate, projectPath } from '../router'
import { useApp } from '../settings-context'

/** Landing page of an invitation link: what the project is, which role it gives, and "Join". */
export default function Join({ token }: { token: string }) {
  const { t, notify, refreshBooks, books } = useApp()
  const invite = useAsync<InvitePreview>((signal) => collabApi.previewInvite(token, signal), [token])
  const { busy, run } = useBusy()

  const open = (bookId: number | null) => navigate(bookId ? projectPath(bookId) : '/')
  const accept = () => void run(async () => {
    try {
      const joined = await collabApi.acceptInvite(token)
      await refreshBooks()
      notify(t('join.done'))
      open(joined.book)
    } catch (err) { notify(errorText(err), 'error') }
  })

  if (invite.loading && !invite.data) return <Loading />
  if (invite.error) return <ErrorState error={invite.error} />
  const i = invite.data!
  const existing = books.find((b) => b.world === i.world.id)

  return (
    <div className="join">
      <div className="join-card">
        <p className="label">{t('join.invited')}</p>
        <h1>{i.world.name}</h1>
        {i.books.length > 0 && <p className="muted">{t('join.books')}: {i.books.map((b) => b.title).join(', ')}</p>}
        <p>
          {i.invited_by && <>{t('join.from')} <b>{i.invited_by.name}</b> · </>}
          {t('join.role')}: <span className={'role-pill role-' + i.role}>{t('role.' + i.role)}</span>
        </p>
        <p className="muted">{t('roleHelp.' + i.role)}</p>
        {i.problem ? <p className="field-error">{i.problem}</p>
          : i.my_role ? (
            <>
              <p>{t('join.already').replace('{role}', t('role.' + i.my_role))}</p>
              <button className="btn" onClick={() => open(existing?.id ?? null)}>{t('join.open')}</button>
            </>
          ) : (
            <div className="join-acts">
              <button className="btn" disabled={busy} onClick={accept}>{busy ? t('ui.loading') : t('join.accept')}</button>
              <button className="btn-ghost" onClick={() => navigate('/')}>{t('ui.cancel')}</button>
            </div>
          )}
      </div>
    </div>
  )
}

/** Personal invitations waiting for the signed-in user (shown on the library page). */
export function InvitesInbox() {
  const { t, notify, refreshBooks } = useApp()
  const invites = useAsync<InvitePreview[]>((signal) => collabApi.myInvites(signal), [])
  const { busy, run } = useBusy()
  if (!invites.data?.length) return null

  const act = (token: string, accept: boolean) => void run(async () => {
    try {
      if (accept) {
        const joined = await collabApi.acceptInvite(token)
        await refreshBooks()
        notify(t('join.done'))
        if (joined.book) navigate(projectPath(joined.book))
      } else {
        await collabApi.declineInvite(token)
      }
      invites.reload()
    } catch (err) { notify(errorText(err), 'error') }
  })

  return (
    <section className="inbox">
      <h3>{t('join.inbox')}</h3>
      {invites.data.map((i) => (
        <div key={i.token} className="inbox-row">
          <span>
            <b>{i.world.name}</b>
            <small className="muted"> · {i.invited_by?.name} · {t('role.' + i.role)}</small>
          </span>
          <button className="btn small" disabled={busy} onClick={() => act(i.token!, true)}>{t('join.accept')}</button>
          <button className="link" disabled={busy} onClick={() => act(i.token!, false)}>{t('join.decline')}</button>
        </div>
      ))}
    </section>
  )
}
