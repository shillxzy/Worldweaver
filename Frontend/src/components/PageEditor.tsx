import { EditorContent, useEditor } from '@tiptap/react'
import type { Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { pagesApi } from '../api/pages'
import type { DocNode, PageDetail } from '../api/types'
import { errorText } from '../hooks'
import { useApp } from '../settings-context'
import LinkPicker from './LinkPicker'

export type SaveState = 'saved' | 'dirty' | 'saving' | 'error' | 'conflict'
type Draft = { revision: number; content: DocNode; savedAt: number }

const SAVE_DELAY = 1200
const draftKey = (id: number) => `ww-page-draft-${id}`
const sameDoc = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const PAGE_HREF = /^page:(\d+)$/

function readDraft(id: number): Draft | null {
  try { const raw = localStorage.getItem(draftKey(id)); return raw ? (JSON.parse(raw) as Draft) : null } catch { return null }
}
function writeDraft(id: number, draft: Draft | null) {
  try { if (draft) localStorage.setItem(draftKey(id), JSON.stringify(draft)); else localStorage.removeItem(draftKey(id)) } catch { /* server copy stays authoritative */ }
}

type BlockItem = { id: string; label: string; hint: string; run: (e: Editor) => void }

/**
 * Free-form page text: Tiptap with headings, lists, quotes, dividers and links to other pages.
 * Blocks are added with the "+" button or by typing "/" at the start of a line.
 * Autosaves after a pause with optimistic locking (409 → compare with the server).
 */
export default function PageEditor({ worldId, page, onSaved, onState, onOpenPage }: {
  worldId: number; page: PageDetail; onSaved: (p: PageDetail) => void; onState: (s: SaveState) => void; onOpenPage: (id: number) => void
}) {
  const { t, notify } = useApp()
  const [state, setStateRaw] = useState<SaveState>('saved')
  const [recoverable, setRecoverable] = useState<Draft | null>(() => {
    const d = readDraft(page.id)
    return d && d.revision === page.revision && !sameDoc(d.content, page.content) ? d : null
  })
  const [slash, setSlash] = useState<{ query: string; from: number; to: number; left: number; top: number } | null>(null)
  const [slashIndex, setSlashIndex] = useState(0)
  const [picker, setPicker] = useState<{ initial: string } | null>(null)
  const revision = useRef(page.revision)
  const latest = useRef<DocNode>(page.content)
  const dirty = useRef(false)
  const saving = useRef(false)
  const pending = useRef(false)
  const timer = useRef<number | undefined>(undefined)
  const retry = useRef(2000)
  const saveRef = useRef<(force?: boolean) => Promise<void>>(async () => undefined)
  const slashRef = useRef(slash)
  const slashIndexRef = useRef(slashIndex)
  const itemsRef = useRef<BlockItem[]>([])

  const setState = useCallback((s: SaveState) => { setStateRaw(s); onState(s) }, [onState])

  const save = useCallback(async (force = false) => {
    window.clearTimeout(timer.current)
    if (saving.current) { pending.current = true; return }
    saving.current = true
    setState('saving')
    const content = latest.current
    try {
      const saved = await pagesApi.update(worldId, page.id, { content, base_revision: force ? undefined : revision.current })
      revision.current = saved.revision
      retry.current = 2000
      if (sameDoc(latest.current, content)) { dirty.current = false; writeDraft(page.id, null); setState(pending.current ? 'dirty' : 'saved') }
      onSaved(saved)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        try {
          const server = await pagesApi.get(worldId, page.id)
          if (sameDoc(server.content, content)) { dirty.current = false; revision.current = server.revision; writeDraft(page.id, null); setState('saved') } else setState('conflict')
        } catch { setState('conflict') }
      } else if (err instanceof ApiError && err.status === 400) {
        setState('error'); notify(errorText(err), 'error')
      } else {
        setState('error')
        timer.current = window.setTimeout(() => void saveRef.current(), retry.current)
        retry.current = Math.min(retry.current * 2, 60000)
      }
    } finally {
      saving.current = false
      if (pending.current) { pending.current = false; timer.current = window.setTimeout(() => void saveRef.current(), 300) }
    }
  }, [worldId, page.id, notify, onSaved, setState])
  useEffect(() => { saveRef.current = save }, [save])

  const openSlash = (ed: Editor) => {
    const { $from, from, empty } = ed.state.selection
    if (!empty) { setSlash(null); return }
    const before = $from.parent.textBetween(0, $from.parentOffset, undefined, '\n')
    const m = /(?:^|\s)\/([\p{L}\d]*)$/u.exec(before)
    if (!m) { setSlash(null); return }
    const coords = ed.view.coordsAtPos(from)
    // keep the highlighted item while the query is unchanged (selection updates, fast typing)
    if (slashRef.current?.query !== m[1]) setSlashIndex(0)
    setSlash({ query: m[1], from: from - m[1].length - 1, to: from, left: coords.left, top: coords.bottom })
  }

  const editor = useEditor({
    extensions: [StarterKit.configure({
      code: false, codeBlock: false, heading: { levels: [1, 2, 3] },
      link: {
        openOnClick: false, autolink: true, protocols: ['page'], defaultProtocol: 'https',
        isAllowedUri: (url) => /^(page:\d+|https?:\/\/|mailto:)/.test(url),
      },
    })],
    content: page.content,
    editorProps: {
      attributes: { class: 'prose page-prose', 'aria-label': t('enc.textAria') },
      handleKeyDown: (_view, event) => {
        const s = slashRef.current
        if (!s) return false
        const items = itemsRef.current
        if (event.key === 'ArrowDown') { setSlashIndex((i) => Math.min(i + 1, items.length - 1)); return true }
        if (event.key === 'ArrowUp') { setSlashIndex((i) => Math.max(i - 1, 0)); return true }
        if (event.key === 'Escape') { setSlash(null); return true }
        if (event.key === 'Enter') { const item = items[slashIndexRef.current]; if (item) { runItemRef.current(item); return true } }
        return false
      },
      handleClick: (_view, _pos, event) => {
        const anchor = (event.target as HTMLElement).closest('a')
        const href = anchor?.getAttribute('href') ?? ''
        const m = PAGE_HREF.exec(href)
        if (m) { event.preventDefault(); onOpenPage(Number(m[1])); return true }
        if (anchor && (event.ctrlKey || event.metaKey)) { window.open(href, '_blank', 'noopener,noreferrer'); return true }
        return false
      },
    },
    onUpdate: ({ editor: ed }) => {
      latest.current = ed.getJSON() as DocNode
      dirty.current = true
      setState('dirty')
      writeDraft(page.id, { revision: revision.current, content: latest.current, savedAt: Date.now() })
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => void saveRef.current(), SAVE_DELAY)
      openSlash(ed)
    },
    onSelectionUpdate: ({ editor: ed }) => { if (slashRef.current) openSlash(ed) },
  })

  const items: BlockItem[] = [
    { id: 'p', label: t('blk.text'), hint: t('blk.textHint'), run: (e) => e.chain().focus().setParagraph().run() },
    { id: 'h1', label: t('blk.h1'), hint: '#', run: (e) => e.chain().focus().setHeading({ level: 1 }).run() },
    { id: 'h2', label: t('blk.h2'), hint: '##', run: (e) => e.chain().focus().setHeading({ level: 2 }).run() },
    { id: 'h3', label: t('blk.h3'), hint: '###', run: (e) => e.chain().focus().setHeading({ level: 3 }).run() },
    { id: 'ul', label: t('blk.bullet'), hint: '-', run: (e) => e.chain().focus().toggleBulletList().run() },
    { id: 'ol', label: t('blk.ordered'), hint: '1.', run: (e) => e.chain().focus().toggleOrderedList().run() },
    { id: 'quote', label: t('blk.quote'), hint: '>', run: (e) => e.chain().focus().toggleBlockquote().run() },
    { id: 'hr', label: t('blk.divider'), hint: '---', run: (e) => e.chain().focus().setHorizontalRule().run() },
    { id: 'link', label: t('blk.pageLink'), hint: t('blk.pageLinkHint'), run: () => setPicker({ initial: '' }) },
  ]
  const shown = slash ? items.filter((i) => !slash.query || i.label.toLocaleLowerCase('uk').includes(slash.query.toLocaleLowerCase('uk'))) : items
  useEffect(() => { slashRef.current = slash; slashIndexRef.current = slashIndex; itemsRef.current = shown })

  const runItem = (item: BlockItem) => {
    if (!editor) return
    const s = slashRef.current
    if (s) editor.chain().focus().deleteRange({ from: s.from, to: s.to }).run()
    setSlash(null)
    item.run(editor)
  }
  const runItemRef = useRef(runItem)
  useEffect(() => { runItemRef.current = runItem })

  const plusMenu = () => {
    if (!editor) return
    const coords = editor.view.coordsAtPos(editor.state.selection.from)
    setSlash({ query: '', from: editor.state.selection.from, to: editor.state.selection.from, left: coords.left, top: coords.bottom })
    setSlashIndex(0)
  }

  const insertLink = (target: { id: number; title: string }) => {
    setPicker(null)
    if (!editor) return
    const href = `page:${target.id}`
    if (editor.state.selection.empty) {
      editor.chain().focus().insertContent([
        { type: 'text', text: target.title, marks: [{ type: 'link', attrs: { href } }] }, { type: 'text', text: ' ' },
      ]).run()
    } else {
      editor.chain().focus().extendMarkRange('link').setLink({ href }).run()
    }
  }

  // Mount: drop a stale draft; unmount: flush unsaved text. Save on reconnect; warn before leaving.
  useEffect(() => {
    const d = readDraft(page.id)
    if (d && (d.revision !== page.revision || sameDoc(d.content, page.content))) writeDraft(page.id, null)
    return () => {
      window.clearTimeout(timer.current)
      if (dirty.current && !saving.current) void saveRef.current()
    }
  }, [page.id, page.revision, page.content])
  useEffect(() => {
    const onOnline = () => { if (dirty.current) void saveRef.current() }
    const warn = (e: BeforeUnloadEvent) => { if (dirty.current) e.preventDefault() }
    window.addEventListener('online', onOnline)
    window.addEventListener('beforeunload', warn)
    return () => { window.removeEventListener('online', onOnline); window.removeEventListener('beforeunload', warn) }
  }, [])

  const reloadServer = () => {
    pagesApi.get(worldId, page.id).then((fresh) => {
      revision.current = fresh.revision
      latest.current = fresh.content
      dirty.current = false
      writeDraft(page.id, null)
      editor?.commands.setContent(fresh.content, { emitUpdate: false })
      setState('saved')
      onSaved(fresh)
    }).catch((err) => notify(errorText(err), 'error'))
  }

  return (
    <div className="page-editor">
      {editor && (
        <div className="format-bar page-format">
          <button onClick={plusMenu} title={t('blk.add')} aria-label={t('blk.add')}>+</button>
          <button className={editor.isActive('bold') ? 'on' : ''} onClick={() => editor.chain().focus().toggleBold().run()} title="Ctrl+B"><b>Ж</b></button>
          <button className={editor.isActive('italic') ? 'on' : ''} onClick={() => editor.chain().focus().toggleItalic().run()} title="Ctrl+I"><i>К</i></button>
          <button className={editor.isActive('heading', { level: 2 }) ? 'on' : ''} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>H2</button>
          <button className={editor.isActive('bulletList') ? 'on' : ''} onClick={() => editor.chain().focus().toggleBulletList().run()}>•</button>
          <button className={editor.isActive('blockquote') ? 'on' : ''} onClick={() => editor.chain().focus().toggleBlockquote().run()}>❝</button>
          <button className={editor.isActive('link') ? 'on' : ''} onClick={() => {
            if (editor.isActive('link')) editor.chain().focus().extendMarkRange('link').unsetLink().run()
            else setPicker({ initial: editor.state.doc.textBetween(editor.state.selection.from, editor.state.selection.to) })
          }} title={t('blk.pageLink')}>🔗</button>
          <button onClick={() => {
            const url = window.prompt(t('enc.externalUrl'), 'https://')
            if (url && /^(https?:\/\/|mailto:)/.test(url)) editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run()
          }} title={t('enc.externalLink')}>↗</button>
          <span className="spacer" />
          <small className="muted">{t('enc.slashHint')}</small>
        </div>
      )}
      {recoverable && (
        <div className="notice">
          {t('ed.draftFound')} ({new Date(recoverable.savedAt).toLocaleString()})
          <button className="btn-ghost" onClick={() => { editor?.commands.setContent(recoverable.content, { emitUpdate: true }); setRecoverable(null) }}>{t('ed.restoreDraft')}</button>
          <button className="link" onClick={() => { writeDraft(page.id, null); setRecoverable(null) }}>{t('ed.discardDraft')}</button>
        </div>
      )}
      {state === 'conflict' && (
        <div className="notice danger">
          {t('enc.conflict')}
          <button className="btn-ghost" onClick={reloadServer}>{t('ed.loadServer')}</button>
          <button className="btn-ghost" onClick={() => void save(true)}>{t('ed.overwrite')}</button>
        </div>
      )}
      <EditorContent editor={editor} />
      {slash && shown.length > 0 && (
        <div className="slash-menu" style={{ left: slash.left, top: slash.top + 6 }} role="listbox">
          {shown.map((item, i) => (
            <button key={item.id} role="option" aria-selected={i === slashIndex} className={i === slashIndex ? 'on' : ''}
              onMouseDown={(e) => { e.preventDefault(); runItem(item) }} onMouseEnter={() => setSlashIndex(i)}>
              <span>{item.label}</span><small>{item.hint}</small>
            </button>
          ))}
        </div>
      )}
      {picker && <LinkPicker worldId={worldId} initial={picker.initial} exclude={[page.id]} onClose={() => setPicker(null)} onPick={insertLink} />}
    </div>
  )
}
