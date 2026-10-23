import { useState } from 'react'
import { pagesApi } from '../api/pages'
import type { DateValue, PageProperty, PageSummary, PropertyKind } from '../api/types'
import { errorText } from '../hooks'
import { useApp } from '../settings-context'
import LinkPicker from './LinkPicker'

const KINDS: PropertyKind[] = ['text', 'number', 'date', 'checkbox', 'tags', 'page', 'pages']

/**
 * Optional, free-form page properties. Every property can be renamed, retyped, reordered,
 * removed or left empty; new ones can be added at any time.
 */
export default function PropertyList({ worldId, pageId, properties, pages, onChange, onOpenPage }: {
  worldId: number; pageId: number; properties: PageProperty[]; pages: PageSummary[]
  onChange: (props: PageProperty[]) => void; onOpenPage: (id: number) => void
}) {
  const { t, notify } = useApp()
  const [adding, setAdding] = useState(false)
  const [label, setLabel] = useState('')
  const [kind, setKind] = useState<PropertyKind>('text')
  const [menu, setMenu] = useState<number | null>(null)
  const [picking, setPicking] = useState<PageProperty | null>(null)
  const titleOf = (id: number) => pages.find((p) => p.id === id)

  const update = (prop: PageProperty, data: Partial<Pick<PageProperty, 'label' | 'kind' | 'value'>>) =>
    pagesApi.updateProperty(worldId, pageId, prop.id, data)
      .then((saved) => onChange(properties.map((p) => (p.id === saved.id ? saved : p))))
      .catch((err) => notify(errorText(err), 'error'))

  const remove = (prop: PageProperty) => {
    setMenu(null)
    pagesApi.removeProperty(worldId, pageId, prop.id)
      .then(() => onChange(properties.filter((p) => p.id !== prop.id)))
      .catch((err) => notify(errorText(err), 'error'))
  }

  const shift = (prop: PageProperty, delta: number) => {
    setMenu(null)
    const ids = properties.map((p) => p.id)
    const i = ids.indexOf(prop.id)
    const j = i + delta
    if (j < 0 || j >= ids.length) return
    ;[ids[i], ids[j]] = [ids[j], ids[i]]
    pagesApi.reorderProperties(worldId, pageId, ids).then(onChange).catch((err) => notify(errorText(err), 'error'))
  }

  const add = () => {
    if (!label.trim()) return
    pagesApi.addProperty(worldId, pageId, { label: label.trim(), kind })
      .then((p) => { onChange([...properties, p]); setLabel(''); setKind('text'); setAdding(false) })
      .catch((err) => notify(errorText(err), 'error'))
  }

  const pageChip = (id: number, onRemove: () => void) => {
    const p = titleOf(id)
    return (
      <span key={id} className="tag page-chip">
        <button className="link" onClick={() => onOpenPage(id)}>{p?.icon} {p?.title ?? `#${id}`}</button>
        <button className="icon-btn" onClick={onRemove} aria-label={t('ui.delete')}>×</button>
      </span>
    )
  }

  const valueEditor = (prop: PageProperty) => {
    switch (prop.kind) {
      case 'checkbox':
        return <input type="checkbox" checked={prop.value === true} onChange={(e) => void update(prop, { value: e.target.checked })} />
      case 'number':
        return <input className="prop-input" type="number" defaultValue={typeof prop.value === 'number' ? prop.value : ''} placeholder={t('enc.empty')}
          onBlur={(e) => { const v = e.target.value.trim(); const n = v === '' ? null : Number(v); if (n !== prop.value && (n === null || Number.isFinite(n))) void update(prop, { value: n }) }} />
      case 'date': {
        const d = (prop.value as DateValue | null) ?? { label: '', key: null }
        return (
          <span className="prop-date">
            <input className="prop-input" defaultValue={d.label} placeholder={t('time.label')}
              onBlur={(e) => { if (e.target.value !== d.label) void update(prop, { value: { ...d, label: e.target.value } }) }} />
            <input className="prop-input narrow" type="number" defaultValue={d.key ?? ''} placeholder={t('enc.dateKey')} title={t('enc.dateKeyHint')}
              onBlur={(e) => { const k = e.target.value === '' ? null : Number(e.target.value); if (k !== d.key) void update(prop, { value: { ...d, key: k } }) }} />
          </span>
        )
      }
      case 'tags': {
        const tags = Array.isArray(prop.value) ? (prop.value as string[]) : []
        return (
          <span className="prop-tags">
            {tags.map((tag) => (
              <span key={tag} className="tag">{tag}
                <button className="icon-btn" aria-label={t('ui.delete')} onClick={() => void update(prop, { value: tags.filter((x) => x !== tag) })}>×</button>
              </span>
            ))}
            <input className="prop-input narrow" placeholder="+" onKeyDown={(e) => {
              const v = e.currentTarget.value.trim()
              if (e.key === 'Enter' && v) { e.preventDefault(); e.currentTarget.value = ''; void update(prop, { value: [...tags, v] }) }
            }} />
          </span>
        )
      }
      case 'page': {
        const id = typeof prop.value === 'number' ? prop.value : null
        return id ? pageChip(id, () => void update(prop, { value: null }))
          : <button className="link" onClick={() => setPicking(prop)}>{t('enc.choosePage')}</button>
      }
      case 'pages': {
        const ids = Array.isArray(prop.value) ? (prop.value as number[]) : []
        return (
          <span className="prop-tags">
            {ids.map((id) => pageChip(id, () => void update(prop, { value: ids.filter((x) => x !== id) })))}
            <button className="link" onClick={() => setPicking(prop)}>+</button>
          </span>
        )
      }
      default:
        return <textarea className="prop-input" rows={1} defaultValue={typeof prop.value === 'string' ? prop.value : ''} placeholder={t('enc.empty')}
          onInput={(e) => { e.currentTarget.style.height = 'auto'; e.currentTarget.style.height = e.currentTarget.scrollHeight + 'px' }}
          onBlur={(e) => { const v = e.target.value; if (v !== (prop.value ?? '')) void update(prop, { value: v || null }) }} />
    }
  }

  return (
    <div className="props">
      {properties.map((prop) => (
        <div key={prop.id} className="prop-row">
          <input className="prop-label" defaultValue={prop.label} aria-label={t('enc.propName')}
            onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== prop.label) void update(prop, { label: v }); else e.target.value = prop.label }} />
          <div className="prop-value">{valueEditor(prop)}</div>
          <div className="prop-menu-wrap">
            <button className="icon-btn" onClick={() => setMenu(menu === prop.id ? null : prop.id)} aria-label={t('enc.more')}>⋯</button>
            {menu === prop.id && (
              <div className="menu prop-menu" onMouseLeave={() => setMenu(null)}>
                <label className="menu-select">{t('enc.propKind')}
                  <select className="field" value={prop.kind} onChange={(e) => { setMenu(null); void update(prop, { kind: e.target.value as PropertyKind }) }}>
                    {KINDS.map((k) => <option key={k} value={k}>{t('kind.' + k)}</option>)}
                  </select>
                </label>
                <button onClick={() => shift(prop, -1)}>{t('enc.moveUp')}</button>
                <button onClick={() => shift(prop, 1)}>{t('enc.moveDown')}</button>
                <button className="danger-text" onClick={() => remove(prop)}>{t('ui.delete')}</button>
              </div>
            )}
          </div>
        </div>
      ))}
      {adding ? (
        <div className="prop-row adding">
          <input className="prop-label" autoFocus placeholder={t('enc.propName')} value={label} onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') add(); if (e.key === 'Escape') setAdding(false) }} />
          <select className="field prop-kind" value={kind} onChange={(e) => setKind(e.target.value as PropertyKind)}>
            {KINDS.map((k) => <option key={k} value={k}>{t('kind.' + k)}</option>)}
          </select>
          <button className="btn-ghost" disabled={!label.trim()} onClick={add}>{t('ui.add')}</button>
          <button className="link" onClick={() => setAdding(false)}>{t('ui.cancel')}</button>
        </div>
      ) : (
        <button className="link add-prop" onClick={() => setAdding(true)}>+ {t('enc.addProp')}</button>
      )}
      {picking && (
        <LinkPicker worldId={worldId} exclude={[pageId]} title={picking.label} onClose={() => setPicking(null)} onPick={(p) => {
          const prop = picking
          setPicking(null)
          if (prop.kind === 'pages') {
            const ids = Array.isArray(prop.value) ? (prop.value as number[]) : []
            if (!ids.includes(p.id)) void update(prop, { value: [...ids, p.id] })
          } else void update(prop, { value: p.id })
        }} />
      )}
    </div>
  )
}
