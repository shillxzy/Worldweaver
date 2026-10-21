import { useState } from 'react'
import type { FormEvent } from 'react'
import { booksApi } from '../api/books'
import type { BookInput } from '../api/books'
import { ApiError } from '../api/client'
import type { Book, BookStatus, ManuscriptFormat, World } from '../api/types'
import { worldsApi } from '../api/worlds'
import { ACCENTS } from '../data/projects'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'
import CoverArt from './CoverArt'
import { CropUpload } from './ImageCropper'
import { FieldError, Modal } from './Ui'

const STATUSES: BookStatus[] = ['idea', 'drafting', 'revising', 'finished']
const FORMATS: ManuscriptFormat[] = ['novel', 'novella', 'short_story', 'screenplay', 'other']

/** Create or edit a book. A new book goes into an existing world or creates a new one. */
export default function BookForm({ book, onClose, onSaved }: { book?: Book; onClose: () => void; onSaved: (b: Book) => void }) {
  const { t, notify, refreshBooks } = useApp()
  const [current, setCurrent] = useState(book)
  const [pendingCover, setPendingCover] = useState<File | null>(null)
  const [pendingPreview, setPendingPreview] = useState<string | null>(null)
  const worlds = useAsync<World[]>((signal) => worldsApi.list(signal), [])
  const [form, setForm] = useState(() => ({
    title: book?.title ?? '', genre: book?.genre ?? '', description: book?.description ?? '',
    accent: book?.accent ?? ACCENTS[Math.floor(Math.random() * ACCENTS.length)],
    status: book?.status ?? 'drafting', manuscript_format: book?.manuscript_format ?? 'novel',
    world: book ? String(book.world) : 'new', new_world_name: '',
  }))
  const [error, setError] = useState<ApiError | null>(null)
  const { busy, run } = useBusy()
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      setError(null)
      const data: BookInput = {
        title: form.title.trim(), genre: form.genre.trim(), description: form.description, accent: form.accent,
        status: form.status as BookStatus, manuscript_format: form.manuscript_format as ManuscriptFormat,
      }
      if (!book) {
        if (form.world === 'new') data.new_world_name = (form.new_world_name || form.title).trim()
        else data.world = Number(form.world)
      }
      try {
        let saved = book ? await booksApi.update(book.id, data) : await booksApi.create(data)
        if (!book && pendingCover) {
          try { saved = await booksApi.uploadCover(saved.id, pendingCover) } catch (err) { notify(errorText(err), 'error') }
        }
        onSaved(saved)
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(0, 'client', String(err)))
      }
    })
  }

  return (
    <Modal title={book ? t('ov.edit') : t('lib.new')} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>{t('ui.title')}<input className="field" required maxLength={200} value={form.title} onChange={set('title')} autoFocus /></label>
        <FieldError text={error?.field('title')} />
        <label>{t('ui.genre')}<input className="field" maxLength={120} value={form.genre} onChange={set('genre')} /></label>
        <label>{t('ui.description')}<textarea className="field" value={form.description} onChange={set('description')} /></label>
        {!book && (
          <label>{t('ov.world')}
            <select className="field" value={form.world} onChange={set('world')}>
              <option value="new">{t('bf.newWorld')}</option>
              {worlds.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </label>
        )}
        {!book && form.world === 'new' && (
          <label>{t('bf.worldName')}<input className="field" maxLength={200} placeholder={form.title} value={form.new_world_name} onChange={set('new_world_name')} /></label>
        )}
        <FieldError text={error?.field('world')} />
        <div className="row2">
          <label>{t('bf.status')}
            <select className="field" value={form.status} onChange={set('status')}>
              {STATUSES.map((s) => <option key={s} value={s}>{t('bookStatus.' + s)}</option>)}
            </select>
          </label>
          <label>{t('bf.format')}
            <select className="field" value={form.manuscript_format} onChange={set('manuscript_format')}>
              {FORMATS.map((s) => <option key={s} value={s}>{t('format.' + s)}</option>)}
            </select>
          </label>
        </div>
        <fieldset className="cover-field">
          <legend>{t('bf.cover')}</legend>
          <div className="cover-preview">
            {pendingPreview ? <img className="cover-img" src={pendingPreview} alt="" />
              : <CoverArt p={current ?? { id: 0, title: form.title, accent: form.accent }} />}
          </div>
          <div className="cover-acts">
            <CropUpload aspect={3 / 4} outputWidth={900} onUpload={async (file) => {
              if (current) {
                try {
                  setCurrent(await booksApi.uploadCover(current.id, file))
                  notify(t('ui.saved'))
                  void refreshBooks()
                } catch (err) { notify(errorText(err), 'error') }
              } else {
                setPendingCover(file)
                setPendingPreview((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(file) })
              }
            }}>{t('bf.uploadCover')}</CropUpload>
            {(current?.has_cover || pendingCover) && (
              <button type="button" className="link" onClick={() => {
                if (pendingCover) { setPendingCover(null); setPendingPreview(null); return }
                if (!current) return
                booksApi.removeCover(current.id)
                  .then(() => { setCurrent({ ...current, has_cover: false }); void refreshBooks() })
                  .catch((err) => notify(errorText(err), 'error'))
              }}>{t('bf.removeCover')}</button>
            )}
            <small className="muted">{t('bf.coverHint')}</small>
          </div>
        </fieldset>
        <label>{t('ui.color')}
          <div className="swatches">
            {ACCENTS.map((c) => (
              <button type="button" key={c} className={'swatch' + (form.accent === c ? ' on' : '')} style={{ background: c }}
                aria-label={c} onClick={() => setForm({ ...form, accent: c })} />
            ))}
          </div>
        </label>
        {error && !error.details && <p className="field-error">{error.message}</p>}
        <div className="acts">
          <button type="button" className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
          <button className="btn" disabled={busy || !form.title.trim()}>{book ? t('ui.save') : t('ui.create')}</button>
        </div>
      </form>
    </Modal>
  )
}
