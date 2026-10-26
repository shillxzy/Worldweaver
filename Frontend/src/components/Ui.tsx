import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'
import type { ApiError } from '../api/client'
import { useApp } from '../settings-context'
import Icon from './Icon'

export function Loading({ label }: { label?: string }) {
  const { t } = useApp()
  return <div className="state"><span className="spinner" />{label ?? t('ui.loading')}</div>
}

export function ErrorState({ error, onRetry }: { error: ApiError | null; onRetry?: () => void }) {
  const { t } = useApp()
  if (!error) return null
  return (
    <div className="state error">
      <p>{error.isNetwork ? t('ui.offline') : error.message}</p>
      {onRetry && <button type="button" className="btn-ghost" onClick={onRetry}>{t('ui.retry')}</button>}
    </div>
  )
}

export function Empty({ title, text, action }: { title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <Icon n="logo" />
      <h3>{title}</h3>
      {text && <p>{text}</p>}
      {action}
    </div>
  )
}

export function Modal({ title, onClose, children, wide, footer }: {
  title: string; onClose: () => void; children: ReactNode; wide?: boolean; footer?: ReactNode
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  // Rendered into <body>: a modal opened from the sticky sidebar must not stay under page content.
  return createPortal(
    <div className="modal-back" onMouseDown={onClose}>
      <div className={'modal' + (wide ? ' wide' : '')} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head"><h3>{title}</h3><button type="button" className="icon-btn" onClick={onClose} aria-label="close">×</button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="acts">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

export function Confirm({ title, text, confirmLabel, onConfirm, onCancel, busy }: {
  title: string; text: string; confirmLabel: string; onConfirm: () => void; onCancel: () => void; busy?: boolean
}) {
  const { t } = useApp()
  return (
    <Modal title={title} onClose={onCancel} footer={<>
      <button type="button" className="btn-ghost" onClick={onCancel}>{t('st.cancel')}</button>
      <button type="button" className="btn-danger" disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
    </>}>
      <p>{text}</p>
    </Modal>
  )
}

export function FieldError({ text }: { text?: string }) {
  return text ? <span className="field-error">{text}</span> : null
}

export function Toasts({ toasts }: { toasts: { id: number; kind: string; text: string }[] }) {
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((toast) => <div key={toast.id} className={'toast ' + toast.kind}>{toast.text}</div>)}
    </div>
  )
}
