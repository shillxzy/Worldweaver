import { useEffect, useRef, useState } from 'react'
import { collabApi } from '../api/collab'
import type { CommentTarget } from '../api/collab'
import type { Comment } from '../api/types'
import { errorText, useAsync, useBusy } from '../hooks'
import type { AsyncState } from '../hooks'
import { useApp } from '../settings-context'
import { MemberAvatar } from './ShareDialog'
import { ErrorState, Loading } from './Ui'

/**
 * Discussion next to a chapter or a page. Comments never change the text; a thread can be
 * closed by its author or an editor. ``quote`` is the text selected in the editor (optional) and
 * ``occurrence`` says which of its occurrences it was, so the passage can be highlighted later.
 * ``state`` lets the page own the list (it highlights the passages); ``focusId`` is the thread to show.
 */
export default function CommentsPanel({ worldId, target, quote, occurrence = 0, state, focusId, onFocus, onQuoteUsed, onClose, onCount }: {
  worldId: number; target: CommentTarget; quote?: string; occurrence?: number; state?: AsyncState<Comment[]>
  focusId?: number | null; onFocus?: (id: number) => void
  onQuoteUsed?: () => void; onClose: () => void; onCount?: (open: number) => void
}) {
  const { t, notify } = useApp()
  const key = 'chapter' in target ? `c${target.chapter}` : `p${target.page}`
  const own = useAsync<Comment[]>(async (signal) => {
    if (state) return []
    const list = await collabApi.comments(worldId, target, signal)
    onCount?.(list.filter((c) => !c.parent && !c.resolved).length)
    return list
  }, [worldId, key, !!state])
  const comments = state ?? own
  const input = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { if (quote) input.current?.focus() }, [quote])
  const { busy, run } = useBusy()
  const [body, setBody] = useState('')
  const [dismissed, setDismissed] = useState('')
  const shownQuote = quote && quote !== dismissed ? quote : ''
  const [showResolved, setShowResolved] = useState(false)

  const act = (fn: () => Promise<unknown>) => void run(async () => {
    try { await fn(); comments.reload() } catch (err) { notify(errorText(err), 'error') }
  })
  const add = () => {
    if (!body.trim()) return
    act(async () => {
      await collabApi.addComment(worldId, { ...target, body: body.trim(), quote: shownQuote.slice(0, 500), quote_occurrence: shownQuote ? occurrence : 0 })
      setBody('')
      onQuoteUsed?.()
    })
  }

  const all = comments.data ?? []
  const threads = all.filter((c) => !c.parent && (showResolved || !c.resolved))
  const resolvedCount = all.filter((c) => !c.parent && c.resolved).length

  return (
    <aside className="comments-panel">
      <div className="comments-head">
        <b>{t('cm.title')}</b>
        <button className="icon-btn" onClick={onClose} aria-label={t('ui.close')}>×</button>
      </div>
      <div className="comment-new">
        {shownQuote && (
          <blockquote className="comment-quote">
            {shownQuote.slice(0, 200)}{shownQuote.length > 200 ? '…' : ''}
            <button className="link" onClick={() => setDismissed(shownQuote)}>{t('cm.noQuote')}</button>
          </blockquote>
        )}
        <textarea ref={input} className="field" rows={3} maxLength={4000} placeholder={shownQuote ? t('cm.aboutSelection') : t('cm.placeholder')}
          value={body} onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) add() }} />
        <button className="btn small" disabled={busy || !body.trim()} onClick={add}>{t('cm.add')}</button>
        {!shownQuote && <small className="muted">{t('cm.selectHint')}</small>}
      </div>
      <ErrorState error={comments.error} onRetry={comments.reload} />
      {comments.loading && !comments.data ? <Loading /> : (
        <div className="comment-threads">
          {threads.length === 0 && <p className="muted">{t('cm.empty')}</p>}
          {threads.map((c) => (
            <Thread key={c.id} worldId={worldId} comment={c} replies={all.filter((r) => r.parent === c.id)} busy={busy} act={act}
              focused={c.id === focusId} onFocus={onFocus} />
          ))}
          {resolvedCount > 0 && (
            <button className="link" onClick={() => setShowResolved((v) => !v)}>
              {showResolved ? t('cm.hideResolved') : t('cm.showResolved').replace('{n}', String(resolvedCount))}
            </button>
          )}
        </div>
      )}
    </aside>
  )
}

function Thread({ worldId, comment, replies, busy, act, focused, onFocus }: {
  worldId: number; comment: Comment; replies: Comment[]; busy: boolean; act: (fn: () => Promise<unknown>) => void
  focused?: boolean; onFocus?: (id: number) => void
}) {
  const { t } = useApp()
  const [replying, setReplying] = useState(false)
  const [reply, setReply] = useState('')
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { if (focused) box.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [focused])
  return (
    <div ref={box} className={'comment-thread' + (comment.resolved ? ' resolved' : '') + (focused ? ' focused' : '')}>
      {comment.quote && (
        onFocus && !comment.resolved
          ? <blockquote className="comment-quote linked" onClick={() => onFocus(comment.id)} title={t('cm.showInText')}>{comment.quote}</blockquote>
          : <blockquote className="comment-quote">{comment.quote}</blockquote>
      )}
      <CommentItem worldId={worldId} comment={comment} busy={busy} act={act} />
      {replies.map((r) => <CommentItem key={r.id} worldId={worldId} comment={r} busy={busy} act={act} reply />)}
      {comment.resolved && <small className="muted">✓ {t('cm.resolvedBy').replace('{name}', comment.resolved_by_name)}</small>}
      <div className="comment-acts">
        {!comment.resolved && <button className="link" onClick={() => setReplying((v) => !v)}>{t('cm.reply')}</button>}
        {comment.can_resolve && (
          <button className="link" disabled={busy} onClick={() => act(() => collabApi.updateComment(worldId, comment.id, { resolved: !comment.resolved }))}>
            {comment.resolved ? t('cm.reopen') : t('cm.resolve')}
          </button>
        )}
      </div>
      {replying && (
        <div className="comment-new">
          <textarea className="field" rows={2} maxLength={4000} autoFocus value={reply} onChange={(e) => setReply(e.target.value)} />
          <button className="btn small" disabled={busy || !reply.trim()} onClick={() => act(async () => {
            await collabApi.addComment(worldId, { parent: comment.id, body: reply.trim() })
            setReply(''); setReplying(false)
          })}>{t('cm.send')}</button>
        </div>
      )}
    </div>
  )
}

function CommentItem({ worldId, comment, busy, act, reply }: {
  worldId: number; comment: Comment; busy: boolean; act: (fn: () => Promise<unknown>) => void; reply?: boolean
}) {
  const { t } = useApp()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(comment.body)
  const author = comment.author ?? { id: 0, name: t('cm.deletedUser'), has_avatar: false }
  return (
    <div className={'comment' + (reply ? ' reply' : '')}>
      <div className="comment-meta">
        <MemberAvatar worldId={worldId} person={author} />
        <b>{author.name}</b>
        <small className="muted">{new Date(comment.created_at).toLocaleString()}</small>
      </div>
      {editing ? (
        <div className="comment-new">
          <textarea className="field" rows={2} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} />
          <span className="comment-acts">
            <button className="btn small" disabled={busy || !text.trim()} onClick={() => act(async () => {
              await collabApi.updateComment(worldId, comment.id, { body: text.trim() }); setEditing(false)
            })}>{t('ui.save')}</button>
            <button className="link" onClick={() => { setEditing(false); setText(comment.body) }}>{t('ui.cancel')}</button>
          </span>
        </div>
      ) : <p className="comment-body">{comment.body}</p>}
      {!editing && (comment.can_edit || comment.can_delete) && (
        <span className="comment-acts small">
          {comment.can_edit && <button className="link" onClick={() => setEditing(true)}>{t('ui.edit')}</button>}
          {comment.can_delete && <button className="link danger-text" disabled={busy} onClick={() => act(() => collabApi.removeComment(worldId, comment.id))}>{t('ui.delete')}</button>}
        </span>
      )}
    </div>
  )
}
