import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode, WheelEvent as ReactWheelEvent } from 'react'
import { useBusy } from '../hooks'
import { useApp } from '../settings-context'
import { Modal } from './Ui'

const FRAME_MAX = 360
const MAX_ZOOM = 5

type Props = {
  file: File
  /** width / height of the result (3/4 for covers, 1 for avatars). */
  aspect: number
  /** width of the produced image in pixels. */
  outputWidth: number
  round?: boolean
  onCancel: () => void
  onDone: (file: File) => Promise<void> | void
}

/**
 * Crop dialog: the user drags the picture and zooms it inside a fixed frame;
 * the visible part of the frame is rendered to a canvas and returned as a JPEG file.
 */
export default function ImageCropper({ file, aspect, outputWidth, round, onCancel, onDone }: Props) {
  const { t } = useApp()
  const frameW = aspect >= 1 ? FRAME_MAX : Math.round(FRAME_MAX * aspect)
  const frameH = Math.round(frameW / aspect)
  const [url, setUrl] = useState<string | null>(null)
  const [img, setImg] = useState<HTMLImageElement | null>(null)
  const [error, setError] = useState('')
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null)
  const { busy, run } = useBusy()

  // A data URL (not an object URL) survives React StrictMode's double mount in development.
  useEffect(() => {
    const reader = new FileReader()
    reader.onload = () => setUrl(typeof reader.result === 'string' ? reader.result : null)
    reader.onerror = () => setError(t('crop.badFile'))
    reader.readAsDataURL(file)
    return () => reader.abort()
  }, [file, t])

  const base = img ? Math.max(frameW / img.naturalWidth, frameH / img.naturalHeight) : 1
  const scale = base * zoom

  /** Keep the image covering the whole frame. */
  const clamp = (x: number, y: number, s = scale) => {
    if (!img) return { x, y }
    const w = img.naturalWidth * s
    const h = img.naturalHeight * s
    return { x: Math.min(0, Math.max(frameW - w, x)), y: Math.min(0, Math.max(frameH - h, y)) }
  }

  const onLoad = (e: { currentTarget: HTMLImageElement }) => {
    const el = e.currentTarget
    const s = Math.max(frameW / el.naturalWidth, frameH / el.naturalHeight)
    setImg(el)
    setOffset({ x: (frameW - el.naturalWidth * s) / 2, y: (frameH - el.naturalHeight * s) / 2 })
  }

  const setZoomAround = (next: number) => {
    const z = Math.min(MAX_ZOOM, Math.max(1, next))
    // keep the frame centre pointing at the same spot of the image
    const cx = (frameW / 2 - offset.x) / scale
    const cy = (frameH / 2 - offset.y) / scale
    const s = base * z
    setZoom(z)
    setOffset(clamp(frameW / 2 - cx * s, frameH / 2 - cy * s, s))
  }

  const down = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y }
  }
  const move = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (d) setOffset(clamp(d.ox + e.clientX - d.x, d.oy + e.clientY - d.y))
  }
  const up = () => { drag.current = null }
  const wheel = (e: ReactWheelEvent<HTMLDivElement>) => setZoomAround(zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1))

  const save = () => void run(async () => {
    if (!img) return
    const canvas = document.createElement('canvas')
    canvas.width = outputWidth
    canvas.height = Math.round(outputWidth / aspect)
    const ctx = canvas.getContext('2d')
    if (!ctx) { setError(t('crop.failed')); return }
    ctx.imageSmoothingQuality = 'high'
    ctx.drawImage(img, -offset.x / scale, -offset.y / scale, frameW / scale, frameH / scale, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.9))
    if (!blob) { setError(t('crop.failed')); return }
    await onDone(new File([blob], 'image.jpg', { type: 'image/jpeg' }))
  })

  return (
    <Modal title={t('crop.title')} onClose={onCancel} footer={<>
      <button type="button" className="btn-ghost" onClick={onCancel}>{t('ui.cancel')}</button>
      <button type="button" className="btn" disabled={!img || busy} onClick={save}>{busy ? t('ui.loading') : t('crop.apply')}</button>
    </>}>
      <p className="muted">{t('crop.hint')}</p>
      <div className={'crop-frame' + (round ? ' round' : '')} style={{ width: frameW, height: frameH }}
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onWheel={wheel}>
        {url && <img src={url} alt="" draggable={false} onLoad={onLoad} onError={() => setError(t('crop.badFile'))}
          style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }} />}
      </div>
      <label className="crop-zoom">{t('crop.zoom')}
        <input type="range" min={1} max={MAX_ZOOM} step={0.01} value={zoom} onChange={(e) => setZoomAround(Number(e.target.value))} />
      </label>
      {error && <p className="field-error">{error}</p>}
    </Modal>
  )
}

/** A button that opens a file picker, then the crop dialog, then calls `onUpload`. */
export function CropUpload({ aspect, outputWidth, round, onUpload, children, className = 'btn-ghost' }: {
  aspect: number; outputWidth: number; round?: boolean; onUpload: (file: File) => Promise<void>; children: ReactNode; className?: string
}) {
  const { t, notify } = useApp()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  return (
    <>
      <button type="button" className={className} onClick={() => input.current?.click()}>{children}</button>
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => {
        const f = e.target.files?.[0]
        e.target.value = ''
        if (!f) return
        if (f.size > 20 * 1024 * 1024) { notify(t('crop.tooLarge'), 'error'); return }
        setFile(f)
      }} />
      {file && (
        <ImageCropper file={file} aspect={aspect} outputWidth={outputWidth} round={round} onCancel={() => setFile(null)}
          onDone={async (cropped) => { await onUpload(cropped); setFile(null) }} />
      )}
    </>
  )
}

/** Full-screen image viewer: click anywhere or press Esc to close. */
export function Lightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="lightbox" role="dialog" aria-label={alt} onClick={onClose}>
      <img src={src} alt={alt} />
      <button type="button" className="lightbox-close" aria-label="close">×</button>
    </div>
  )
}
