import { useState } from 'react'
import type { ReactNode } from 'react'
import { accessFor } from '../access'
import { appUrl, collabApi } from '../api/collab'
import type { PublicFlags } from '../api/collab'
import type { Book, Invite, Member, MembersInfo, PublicSettings, Role } from '../api/types'
import { errorText, useAsync, useBusy } from '../hooks'
import { joinPath, publicPath } from '../router'
import { useApp } from '../settings-context'
import Icon from './Icon'
import { Confirm, ErrorState, Loading, Modal } from './Ui'

const ROLES: Role[] = ['admin', 'editor', 'commenter', 'viewer']
const LINK_ROLES: Role[] = ['editor', 'commenter', 'viewer']

type Tab = 'members' | 'invites' | 'public'

/** Who works on the world (and all its books), invitations, and the public read-only site. */
export default function ShareDialog({ book, onClose, onAccessChanged }: { book: Book; onClose: () => void; onAccessChanged: (change: 'left' | 'transferred') => void }) {
  const { t } = useApp()
  const access = accessFor(book.my_role)
  const [tab, setTab] = useState<Tab>('members')
  const tabs: Tab[] = ['members', ...(access.manage ? ['invites' as const] : []), ...(access.own ? ['public' as const] : [])]

  return (
    <Modal title={t('sh.title')} onClose={onClose} wide>
      <p className="muted share-scope">{t('sh.scope').replace('{world}', book.world_name)}</p>
      {tabs.length > 1 && (
        <div className="seg share-tabs">
          {tabs.map((id) => <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>{t('sh.tab.' + id)}</button>)}
        </div>
      )}
      {tab === 'members' && <MembersTab book={book} onAccessChanged={onAccessChanged} />}
      {tab === 'invites' && <InvitesTab book={book} />}
      {tab === 'public' && <PublicTab book={book} />}
    </Modal>
  )
}

export function MemberAvatar({ worldId, person }: { worldId: number; person: { id: number; name: string; has_avatar: boolean } }) {
  return person.has_avatar
    ? <img className="av-sm" src={collabApi.memberAvatarUrl(worldId, person.id)} alt="" />
    : <span className="av-sm">{person.name[0]?.toUpperCase() ?? '?'}</span>
}

function MembersTab({ book, onAccessChanged }: { book: Book; onAccessChanged: (change: 'left' | 'transferred') => void }) {
  const { t, user, notify } = useApp()
  const info = useAsync<MembersInfo>((signal) => collabApi.members(book.world, signal), [book.world])
  const { busy, run } = useBusy()
  const [confirm, setConfirm] = useState<{ kind: 'remove' | 'leave' | 'transfer'; member: Member } | null>(null)
  if (info.loading && !info.data) return <Loading />
  if (info.error) return <ErrorState error={info.error} onRetry={info.reload} />
  const data = info.data!
  const me = accessFor(data.my_role)

  // Admins manage editors, commenters and viewers; only the owner appoints or removes admins.
  const canManage = (m: Member) => me.manage && m.role !== 'owner' && m.id !== user.id && (m.role !== 'admin' || me.own)
  const setRole = (m: Member, role: Role) => void run(async () => {
    try { info.setData(await collabApi.setRole(book.world, m.id, role)); notify(t('ui.saved')) } catch (err) { notify(errorText(err), 'error') }
  })
  const confirmed = () => {
    if (!confirm) return
    const { kind, member } = confirm
    void run(async () => {
      try {
        if (kind === 'transfer') {
          info.setData(await collabApi.transfer(book.world, member.id))
          notify(t('sh.transferred'))
          onAccessChanged('transferred')
        } else {
          await collabApi.removeMember(book.world, member.id)
          if (kind === 'leave') { onAccessChanged('left'); return }
          info.reload()
        }
      } catch (err) { notify(errorText(err), 'error') }
      setConfirm(null)
    })
  }

  return (
    <div className="share-section">
      <ul className="member-list">
        {data.members.map((m) => (
          <li key={m.id} className="member-row">
            <MemberAvatar worldId={book.world} person={m} />
            <span className="member-name">
              <b>{m.name}{m.id === user.id && <small className="muted"> · {t('sh.you')}</small>}</b>
              {m.email && <small className="muted">{m.email}</small>}
            </span>
            {canManage(m) ? (
              <select className="field narrow-select" value={m.role} disabled={busy} onChange={(e) => setRole(m, e.target.value as Role)}>
                {ROLES.filter((r) => r !== 'admin' || me.own).map((r) => <option key={r} value={r}>{t('role.' + r)}</option>)}
              </select>
            ) : <span className={'role-pill role-' + m.role}>{t('role.' + m.role)}</span>}
            <span className="member-acts">
              {me.own && m.role !== 'owner' && (
                <button className="link" disabled={busy} onClick={() => setConfirm({ kind: 'transfer', member: m })}>{t('sh.makeOwner')}</button>
              )}
              {canManage(m) && (
                <button className="icon-btn" title={t('sh.remove')} aria-label={t('sh.remove')} disabled={busy}
                  onClick={() => setConfirm({ kind: 'remove', member: m })}>×</button>
              )}
              {m.id === user.id && m.role !== 'owner' && (
                <button className="link danger-text" disabled={busy} onClick={() => setConfirm({ kind: 'leave', member: m })}>{t('sh.leave')}</button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {data.members.length === 1 && <p className="muted">{me.manage ? t('sh.aloneManage') : t('sh.alone')}</p>}
      <RoleLegend />
      {confirm && (
        <Confirm busy={busy} onCancel={() => setConfirm(null)} onConfirm={confirmed}
          title={t('sh.confirm.' + confirm.kind)} confirmLabel={t('st.confirm')}
          text={t('sh.confirmText.' + confirm.kind).replace('{name}', confirm.member.name)} />
      )}
    </div>
  )
}

function RoleLegend() {
  const { t } = useApp()
  return (
    <details className="role-legend">
      <summary>{t('sh.rolesHelp')}</summary>
      <dl>
        {(['owner', ...ROLES] as Role[]).map((r) => (
          <div key={r}><dt>{t('role.' + r)}</dt><dd>{t('roleHelp.' + r)}</dd></div>
        ))}
      </dl>
    </details>
  )
}

function CopyField({ value }: { value: string }) {
  const { t, notify } = useApp()
  const copy = () => {
    navigator.clipboard.writeText(value).then(() => notify(t('sh.copied')), () => notify(t('sh.copyFailed'), 'error'))
  }
  return (
    <span className="copy-field">
      <input className="field" readOnly value={value} onFocus={(e) => e.currentTarget.select()} />
      <button className="btn-ghost small" onClick={copy}><Icon n="link" />{t('sh.copy')}</button>
    </span>
  )
}

function InvitesTab({ book }: { book: Book }) {
  const { t, notify } = useApp()
  const access = accessFor(book.my_role)
  const invites = useAsync<Invite[]>((signal) => collabApi.invites(book.world, signal), [book.world])
  const { busy, run } = useBusy()
  const [email, setEmail] = useState('')
  const [emailRole, setEmailRole] = useState<Role>('editor')
  const [linkRole, setLinkRole] = useState<Role>('viewer')
  const [days, setDays] = useState('7')
  const [uses, setUses] = useState('')
  const [fresh, setFresh] = useState<Invite | null>(null)

  const create = (data: Parameters<typeof collabApi.createInvite>[1]) => void run(async () => {
    try {
      const invite = await collabApi.createInvite(book.world, data)
      setFresh(invite)
      setEmail('')
      invites.reload()
    } catch (err) { notify(errorText(err), 'error') }
  })
  const revoke = (invite: Invite) => void run(async () => {
    try {
      await collabApi.revokeInvite(book.world, invite.id)
      if (fresh?.id === invite.id) setFresh(null)
      invites.reload()
    } catch (err) { notify(errorText(err), 'error') }
  })
  const active = (invites.data ?? []).filter((i) => i.status === 'active')

  return (
    <div className="share-section">
      <section className="share-card">
        <h4>{t('sh.byEmail')}</h4>
        <form className="invite-form" onSubmit={(e) => { e.preventDefault(); if (email.trim()) create({ email: email.trim(), role: emailRole, expires_in_days: 30 }) }}>
          <input className="field" type="email" required placeholder="name@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          <select className="field narrow-select" value={emailRole} onChange={(e) => setEmailRole(e.target.value as Role)}>
            {ROLES.filter((r) => r !== 'admin' || access.own).map((r) => <option key={r} value={r}>{t('role.' + r)}</option>)}
          </select>
          <button className="btn" disabled={busy || !email.trim()}>{t('sh.invite')}</button>
        </form>
        <small className="muted">{t('sh.byEmailHint')}</small>
      </section>

      <section className="share-card">
        <h4>{t('sh.byLink')}</h4>
        <div className="invite-form">
          <label className="inline-field">{t('sh.role')}
            <select className="field narrow-select" value={linkRole} onChange={(e) => setLinkRole(e.target.value as Role)}>
              {LINK_ROLES.map((r) => <option key={r} value={r}>{t('role.' + r)}</option>)}
            </select>
          </label>
          <label className="inline-field">{t('sh.expires')}
            <select className="field narrow-select" value={days} onChange={(e) => setDays(e.target.value)}>
              {['1', '7', '30', ''].map((d) => <option key={d} value={d}>{d ? t('sh.days').replace('{n}', d) : t('sh.never')}</option>)}
            </select>
          </label>
          <label className="inline-field">{t('sh.uses')}
            <select className="field narrow-select" value={uses} onChange={(e) => setUses(e.target.value)}>
              {['1', '5', '10', '25', ''].map((u) => <option key={u} value={u}>{u || t('sh.unlimited')}</option>)}
            </select>
          </label>
          <button className="btn" disabled={busy} onClick={() => create({ role: linkRole, expires_in_days: days ? Number(days) : null, max_uses: uses ? Number(uses) : null })}>
            {t('sh.createLink')}
          </button>
        </div>
        <small className="muted">{t('sh.byLinkHint')}</small>
      </section>

      {fresh && (
        <div className="share-fresh">
          <b>{fresh.kind === 'email' ? t('sh.freshEmail').replace('{email}', fresh.email) : t('sh.freshLink')}</b>
          <CopyField value={appUrl(joinPath(fresh.token))} />
        </div>
      )}

      <h4 className="share-subtitle">{t('sh.active')}</h4>
      {invites.loading && !invites.data ? <Loading /> : active.length === 0 ? <p className="muted">{t('sh.noInvites')}</p> : (
        <ul className="invite-list">
          {active.map((i) => (
            <li key={i.id}>
              <span className="invite-what">
                <b>{i.kind === 'email' ? i.email : t('sh.link')}</b>
                <small className="muted">
                  {t('role.' + i.role)}
                  {' · '}{i.expires_at ? t('sh.until').replace('{date}', new Date(i.expires_at).toLocaleDateString()) : t('sh.never')}
                  {i.kind === 'link' && ` · ${i.uses}/${i.max_uses ?? '∞'}`}
                  {i.created_by_name && ` · ${i.created_by_name}`}
                </small>
              </span>
              <button className="btn-ghost small" onClick={() => setFresh(i)}><Icon n="link" />{t('sh.show')}</button>
              <button className="link danger-text" disabled={busy} onClick={() => revoke(i)}>{t('sh.revoke')}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Switch({ checked, disabled, onChange, children }: { checked: boolean; disabled?: boolean; onChange: (v: boolean) => void; children?: ReactNode }) {
  return (
    <label className="switch-row">
      <span className="switch"><input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /><span /></span>
      {children}
    </label>
  )
}

function PublicTab({ book }: { book: Book }) {
  const { t, notify } = useApp()
  const settings = useAsync<PublicSettings>((signal) => collabApi.publicSettings(book.world, signal), [book.world])
  const { busy, run } = useBusy()
  const apply = (flags: PublicFlags) => void run(async () => {
    try { settings.setData(await collabApi.updatePublic(book.world, flags)) } catch (err) { notify(errorText(err), 'error') }
  })
  if (settings.loading && !settings.data) return <Loading />
  if (settings.error) return <ErrorState error={settings.error} onRetry={settings.reload} />
  const s = settings.data!
  const all = (ids: number[], value: boolean) => Object.fromEntries(ids.map((id) => [id, value]))
  const publicPages = s.pages.filter((p) => p.is_public).length

  return (
    <div className="share-section">
      <Switch checked={s.enabled} disabled={busy} onChange={(v) => apply({ enabled: v })}>
        <span><b>{t('pub.enable')}</b><small className="muted">{t('pub.enableHint')}</small></span>
      </Switch>
      {s.enabled && s.token && (
        <div className="share-fresh">
          <CopyField value={appUrl(publicPath(s.token))} />
          <button className="link" disabled={busy} onClick={() => apply({ regenerate: true })}>{t('pub.regenerate')}</button>
        </div>
      )}
      <p className="muted">{t('pub.nothingByDefault')}</p>

      <h4 className="share-subtitle">{t('pub.books')}</h4>
      {s.books.map((b) => (
        <section key={b.id} className="share-card">
          <Switch checked={b.is_public} disabled={busy} onChange={(v) => apply({ books: { [b.id]: v } })}><b>{b.title}</b></Switch>
          {b.is_public && (
            <div className="pub-list">
              <div className="pub-bulk">
                <small className="muted">{t('pub.chaptersShown').replace('{n}', String(b.chapters.filter((c) => c.is_public).length)).replace('{total}', String(b.chapters.length))}</small>
                <button className="link" disabled={busy} onClick={() => apply({ chapters: all(b.chapters.map((c) => c.id), true) })}>{t('pub.all')}</button>
                <button className="link" disabled={busy} onClick={() => apply({ chapters: all(b.chapters.filter((c) => c.status === 'done').map((c) => c.id), true) })}>{t('pub.done')}</button>
                <button className="link" disabled={busy} onClick={() => apply({ chapters: all(b.chapters.map((c) => c.id), false) })}>{t('pub.none')}</button>
              </div>
              {b.chapters.map((c) => (
                <label key={c.id} className="check">
                  <input type="checkbox" checked={c.is_public} disabled={busy} onChange={(e) => apply({ chapters: { [c.id]: e.target.checked } })} />
                  {c.title}<small className="muted"> · {t('chStatus.' + c.status)}</small>
                </label>
              ))}
            </div>
          )}
        </section>
      ))}

      <h4 className="share-subtitle">{t('pub.pages')}</h4>
      <section className="share-card">
        <div className="pub-bulk">
          <small className="muted">{t('pub.pagesShown').replace('{n}', String(publicPages)).replace('{total}', String(s.pages.length))}</small>
          <button className="link" disabled={busy} onClick={() => apply({ pages: all(s.pages.map((p) => p.id), true) })}>{t('pub.all')}</button>
          <button className="link" disabled={busy} onClick={() => apply({ pages: all(s.pages.map((p) => p.id), false) })}>{t('pub.none')}</button>
        </div>
        <div className="pub-list">
          <PageChecks pages={s.pages} parent={null} depth={0} busy={busy} onToggle={(id, v) => apply({ pages: { [id]: v } })} />
        </div>
      </section>
    </div>
  )
}

function PageChecks({ pages, parent, depth, busy, onToggle }: {
  pages: PublicSettings['pages']; parent: number | null; depth: number; busy: boolean; onToggle: (id: number, value: boolean) => void
}) {
  return (
    <>
      {pages.filter((p) => p.parent === parent).map((p) => (
        <div key={p.id}>
          <label className="check" style={{ paddingLeft: depth * 18 }}>
            <input type="checkbox" checked={p.is_public} disabled={busy} onChange={(e) => onToggle(p.id, e.target.checked)} />
            <span className="tree-icon">{p.icon || '·'}</span>{p.title}
          </label>
          {depth < 8 && <PageChecks pages={pages} parent={p.id} depth={depth + 1} busy={busy} onToggle={onToggle} />}
        </div>
      ))}
    </>
  )
}
