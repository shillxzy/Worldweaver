import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import type { Editor } from '@tiptap/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { analysisApi } from '../api/analysis'
import { chaptersApi } from '../api/chapters'
import { ApiError } from '../api/client'
import { languageApi } from '../api/language'
import type { Chapter, ChapterStatus, ChapterVersion, DocNode, QuickIssue, SpellIssue, StyleIssue } from '../api/types'
import { errorText, useBusy } from '../hooks'
import { useApp } from '../settings-context'
import Icon from './Icon'
import { buildTextMap, fragmentAround, offsetToPos } from './textmap'
import { Modal } from './Ui'

type SaveState = 'saved' | 'dirty' | 'saving' | 'error' | 'conflict'
type Draft = { revision: number; content: DocNode; savedAt: number }

const SAVE_DELAY = 1500
const QUICK_DELAY = 2000
const draftKey = (id: number) => `ww-draft-${id}`

function readDraft(id: number): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(id))
    return raw ? (JSON.parse(raw) as Draft) : null
  } catch {
    return null
  }
}
function writeDraft(id: number, draft: Draft | null) {
  try {
    if (draft) localStorage.setItem(draftKey(id), JSON.stringify(draft))
    else localStorage.removeItem(draftKey(id))
  } catch { /* storage full or disabled: the server copy is still authoritative */ }
}

const sameDoc = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export default function ChapterEditor({ bookId, worldId, chapter: initial, onMetaSaved, quickEnabled, spellEnabled }: {
  bookId: number; worldId: number; chapter: Chapter; onMetaSaved: (c: Chapter) => void
  quickEnabled: boolean; spellEnabled: boolean
}) {
  const { t, notify, online } = useApp()
  const [chapter, setChapter] = useState(initial)
  const [state, setState] = useState<SaveState>('saved')
  const [words, setWords] = useState(initial.word_count)
  // Offer to restore an unsaved local draft from a previous session / crash.
  const [recoverable, setRecoverable] = useState<Draft | null>(() => {
    const draft = readDraft(initial.id)
    return draft && draft.revision === initial.revision && !sameDoc(draft.content, initial.content) ? draft : null
  })
  const [issues, setIssues] = useState<QuickIssue[]>([])
  const [spell, setSpell] = useState<{ spelling: SpellIssue[]; style: StyleIssue[] } | null>(null)
  const [suggestions, setSuggestions] = useState<Record<string, string[]>>({})
  const [panel, setPanel] = useState<'hints' | 'spell' | 'meta' | null>('hints')
  const [versions, setVersions] = useState<ChapterVersion[] | null>(null)
  const [preview, setPreview] = useState<{ id: number; text: string } | null>(null)
  const { busy, run } = useBusy()

  const revision = useRef(initial.revision)
  const latest = useRef<DocNode>(initial.content)
  const saving = useRef(false)
  const pending = useRef(false)
  const saveTimer = useRef<number | undefined>(undefined)
  const quickTimer = useRef<number | undefined>(undefined)
  const quickAbort = useRef<AbortController | null>(null)
  const retryDelay = useRef(2000)
  const dirty = useRef(false)
  const saveRef = useRef<(opts?: { snapshot?: boolean; force?: boolean }) => Promise<void>>(async () => undefined)

  const save = useCallback(async (opts: { snapshot?: boolean; force?: boolean } = {}) => {
    window.clearTimeout(saveTimer.current)
    if (saving.current) { pending.current = true; return }
    saving.current = true
    setState('saving')
    const content = latest.current
    try {
      const saved = await chaptersApi.update(bookId, chapter.id, {
        content, snapshot: opts.snapshot, base_revision: opts.force ? undefined : revision.current,
      })
      revision.current = saved.revision
      setWords(saved.word_count)
      retryDelay.current = 2000
      if (sameDoc(latest.current, content)) {
        dirty.current = false
        writeDraft(chapter.id, null)
        setState(pending.current ? 'dirty' : 'saved')
      }
      if (opts.snapshot) notify(t('ed.snapshot'))
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // The previous request may have succeeded with the response lost: compare with the server.
        try {
          const server = await chaptersApi.get(bookId, chapter.id)
          if (sameDoc(server.content, content)) {
            dirty.current = false
            revision.current = server.revision
            writeDraft(chapter.id, null)
            setState('saved')
          } else {
            setState('conflict')
          }
        } catch {
          setState('conflict')
        }
      } else if (err instanceof ApiError && err.status === 400) {
        setState('error')
        notify(errorText(err), 'error')
      } else {
        setState('error')
        // Network/server failure: keep the local draft and retry with backoff.
        saveTimer.current = window.setTimeout(() => void saveRef.current(), retryDelay.current)
        retryDelay.current = Math.min(retryDelay.current * 2, 60000)
      }
    } finally {
      saving.current = false
      if (pending.current) {
        pending.current = false
        saveTimer.current = window.setTimeout(() => void saveRef.current(), 300)
      }
    }
  }, [bookId, chapter.id, notify, t])

  const runQuickCheck = useCallback((editor: Editor) => {
    if (!quickEnabled) return
    quickAbort.current?.abort()
    const controller = new AbortController()
    quickAbort.current = controller
    const map = buildTextMap(editor.state.doc)
    const fragment = fragmentAround(map, editor.state.selection.from)
    if (!fragment.text.trim()) { setIssues([]); return }
    analysisApi.quickCheck(chapter.id, fragment.text.slice(0, 20000), fragment.offset, controller.signal)
      .then((r) => setIssues(r.issues))
      .catch((err: unknown) => { if (!(err instanceof ApiError && err.isAborted)) setIssues([]) })
  }, [chapter.id, quickEnabled])

  const quickRef = useRef(runQuickCheck)
  useEffect(() => { saveRef.current = save }, [save])
  useEffect(() => { quickRef.current = runQuickCheck }, [runQuickCheck])

  const editor = useEditor({
    extensions: [StarterKit.configure({ code: false, codeBlock: false, link: false, heading: { levels: [1, 2, 3] } })],
    content: initial.content,
    editorProps: { attributes: { class: 'prose', spellcheck: 'false', 'aria-label': t('ed.aria') } },
    onUpdate: ({ editor: ed }) => {
      latest.current = ed.getJSON() as DocNode
      dirty.current = true
      setState('dirty')
      writeDraft(initial.id, { revision: revision.current, content: latest.current, savedAt: Date.now() })
      window.clearTimeout(saveTimer.current)
      saveTimer.current = window.setTimeout(() => void saveRef.current(), SAVE_DELAY)
      window.clearTimeout(quickTimer.current)
      quickTimer.current = window.setTimeout(() => quickRef.current(ed), QUICK_DELAY)
    },
  })

  // Mount: drop a stale local draft. Unmount: flush unsaved text.
  useEffect(() => {
    const draft = readDraft(initial.id)
    if (draft && (draft.revision !== initial.revision || sameDoc(draft.content, initial.content))) writeDraft(initial.id, null)
    return () => {
      window.clearTimeout(quickTimer.current)
      quickAbort.current?.abort()
      window.clearTimeout(saveTimer.current)
      if (dirty.current && !saving.current) void saveRef.current()
    }
  }, [initial.id, initial.revision, initial.content])

  // Save as soon as the connection comes back.
  useEffect(() => {
    const onOnline = () => { if (dirty.current) void saveRef.current() }
    window.addEventListener('online', onOnline)
    return () => window.removeEventListener('online', onOnline)
  }, [])

  // Warn before leaving the page with unsaved changes.
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (state !== 'saved') e.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [state])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); void save({ snapshot: true }) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [save])

  const select = (start: number | null, end: number | null) => {
    const ed = editor
    if (!ed || start === null || end === null) return
    const map = buildTextMap(ed.state.doc)
    const from = offsetToPos(map, start)
    const to = offsetToPos(map, end)
    if (from !== null && to !== null) ed.chain().focus().setTextSelection({ from, to }).scrollIntoView().run()
  }

  const replace = (issue: SpellIssue, value: string) => {
    const ed = editor
    if (!ed) return
    const map = buildTextMap(ed.state.doc)
    const from = offsetToPos(map, issue.start)
    const to = offsetToPos(map, issue.end)
    if (from === null || to === null || ed.state.doc.textBetween(from, to) !== issue.word) {
      notify(t('ed.textChanged'), 'info')
      return
    }
    ed.chain().focus().insertContentAt({ from, to }, value).run()
    setSpell((s) => s && { ...s, spelling: s.spelling.filter((x) => x !== issue).map((x) => x.start > issue.start ? { ...x, start: x.start + value.length - issue.word.length, end: x.end + value.length - issue.word.length } : x) })
  }

  const checkSpelling = () => {
    const ed = editor
    if (!ed) return
    setPanel('spell')
    void run(async () => {
      try {
        setSpell(await languageApi.check(buildTextMap(ed.state.doc).text.slice(0, 100000), worldId))
      } catch (err) { notify(errorText(err), 'error'); setSpell(null) }
    })
  }

  const loadSuggestions = (word: string) => {
    if (suggestions[word]) return
    languageApi.suggest(word).then((r) => setSuggestions((s) => ({ ...s, [word]: r.suggestions }))).catch(() => setSuggestions((s) => ({ ...s, [word]: [] })))
  }

  const reloadFromServer = () => void run(async () => {
    try {
      const fresh = await chaptersApi.get(bookId, chapter.id)
      revision.current = fresh.revision
      latest.current = fresh.content
      editor?.commands.setContent(fresh.content, { emitUpdate: false })
      dirty.current = false
      writeDraft(chapter.id, null)
      setWords(fresh.word_count)
      setState('saved')
    } catch (err) { notify(errorText(err), 'error') }
  })

  const saveMeta = (patch: { title?: string; status?: ChapterStatus; story_time_key?: string | null; story_time_label?: string; is_flashback?: boolean; narrator_unreliable?: boolean }) =>
    void run(async () => {
      try {
        const saved = await chaptersApi.update(bookId, chapter.id, patch)
        setChapter(saved)
        onMetaSaved(saved)
      } catch (err) { notify(errorText(err), 'error') }
    })

  const openVersions = () => void run(async () => {
    try { setVersions(await chaptersApi.versions(bookId, chapter.id)) } catch (err) { notify(errorText(err), 'error') }
  })

  const restore = (versionId: number) => void run(async () => {
    try {
      const restored = await chaptersApi.restore(bookId, chapter.id, versionId)
      revision.current = restored.revision
      latest.current = restored.content
      editor?.commands.setContent(restored.content, { emitUpdate: false })
      dirty.current = false
      setWords(restored.word_count)
      setState('saved')
      setVersions(null)
      setPreview(null)
      notify(t('ed.restored'))
    } catch (err) { notify(errorText(err), 'error') }
  })

  const statusText: Record<SaveState, string> = {
    saved: t('ed.saved'), dirty: t('ed.dirty'), saving: t('ed.saving'), error: online ? t('ed.retrying') : t('ed.offline'), conflict: t('ed.conflict'),
  }

  return (
    <div className="workspace">
      <div className="editor-col">
        <div className="editor-bar">
          <input className="chapter-title" value={chapter.title} onChange={(e) => setChapter({ ...chapter, title: e.target.value })}
            onBlur={(e) => e.target.value.trim() && e.target.value !== initial.title && saveMeta({ title: e.target.value.trim() })} />
          <span className={'save-state ' + state}>{statusText[state]}</span>
          <span className="muted">{words} {t('ov.words')}</span>
        </div>
        {editor && (
          <div className="format-bar">
            <button className={editor.isActive('bold') ? 'on' : ''} onClick={() => editor.chain().focus().toggleBold().run()} title="Ctrl+B"><b>Ж</b></button>
            <button className={editor.isActive('italic') ? 'on' : ''} onClick={() => editor.chain().focus().toggleItalic().run()} title="Ctrl+I"><i>К</i></button>
            <button className={editor.isActive('underline') ? 'on' : ''} onClick={() => editor.chain().focus().toggleUnderline().run()}><u>П</u></button>
            <button className={editor.isActive('heading', { level: 2 }) ? 'on' : ''} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>H2</button>
            <button className={editor.isActive('blockquote') ? 'on' : ''} onClick={() => editor.chain().focus().toggleBlockquote().run()}>❝</button>
            <button className={editor.isActive('bulletList') ? 'on' : ''} onClick={() => editor.chain().focus().toggleBulletList().run()}>•</button>
            <button onClick={() => editor.chain().focus().setHorizontalRule().run()}>⁂</button>
            <button onClick={() => editor.chain().focus().undo().run()} disabled={!editor.can().undo()}>↶</button>
            <button onClick={() => editor.chain().focus().redo().run()} disabled={!editor.can().redo()}>↷</button>
            <span className="spacer" />
            <button onClick={() => void save({ snapshot: true })} title="Ctrl+S">{t('ed.saveVersion')}</button>
            <button onClick={openVersions}>{t('ed.versions')}</button>
          </div>
        )}
        {recoverable && (
          <div className="notice">
            {t('ed.draftFound')} ({new Date(recoverable.savedAt).toLocaleString()})
            <button className="btn-ghost" onClick={() => {
              editor?.commands.setContent(recoverable.content, { emitUpdate: true })
              setRecoverable(null)
            }}>{t('ed.restoreDraft')}</button>
            <button className="link" onClick={() => { writeDraft(chapter.id, null); setRecoverable(null) }}>{t('ed.discardDraft')}</button>
          </div>
        )}
        {state === 'conflict' && (
          <div className="notice danger">
            {t('ed.conflictText')}
            <button className="btn-ghost" onClick={reloadFromServer}>{t('ed.loadServer')}</button>
            <button className="btn-ghost" onClick={() => void save({ force: true })}>{t('ed.overwrite')}</button>
          </div>
        )}
        <div className="paper editor-paper"><EditorContent editor={editor} /></div>
      </div>

      <aside className="side-panel">
        <div className="seg small">
          <button className={panel === 'hints' ? 'on' : ''} onClick={() => setPanel('hints')}>{t('ed.hints')}{issues.length ? ` (${issues.length})` : ''}</button>
          <button className={panel === 'spell' ? 'on' : ''} onClick={() => (spell ? setPanel('spell') : checkSpelling())}>{t('ed.spelling')}</button>
          <button className={panel === 'meta' ? 'on' : ''} onClick={() => setPanel('meta')}>{t('ed.meta')}</button>
        </div>

        {panel === 'hints' && (
          <div className="panel-list">
            {!quickEnabled && <p className="muted">{t('ed.quickOff')}</p>}
            {quickEnabled && issues.length === 0 && <p className="muted">{t('ed.noHints')}</p>}
            {issues.map((i, n) => (
              <button key={n} className={'issue ' + i.severity} onClick={() => select(i.start, i.end)}>
                <b>{i.summary}</b><small>{i.explanation}</small>
              </button>
            ))}
          </div>
        )}

        {panel === 'spell' && (
          <div className="panel-list">
            {!spellEnabled && <p className="muted">{t('ed.spellOff')}</p>}
            <button className="btn-ghost" onClick={checkSpelling} disabled={busy}><Icon n="check" />{t('ed.checkAgain')}</button>
            {spell && spell.spelling.length === 0 && spell.style.length === 0 && <p className="ok"><Icon n="check" />{t('ed.noErrors')}</p>}
            {spell?.spelling.map((s) => (
              <div key={`${s.start}-${s.word}`} className="issue warning" onMouseEnter={() => loadSuggestions(s.word)}>
                <button className="link" onClick={() => select(s.start, s.end)}><b>{s.word}</b></button>
                <small>{s.message}</small>
                <div className="sugg">
                  {(suggestions[s.word] ?? []).map((v) => <button key={v} className="tab" onClick={() => replace(s, v)}>{v}</button>)}
                  {suggestions[s.word]?.length === 0 && <small className="muted">{t('ed.noSuggestions')}</small>}
                </div>
                <div className="note-acts">
                  <button className="link" onClick={() => void languageApi.addWord(s.word).then(() => {
                    setSpell((x) => x && { ...x, spelling: x.spelling.filter((y) => y.word.toLowerCase() !== s.word.toLowerCase()) })
                  }).catch((err) => notify(errorText(err), 'error'))}>{t('ed.addWord')}</button>
                  <button className="link" onClick={() => setSpell((x) => x && { ...x, spelling: x.spelling.filter((y) => y !== s) })}>{t('ed.ignore')}</button>
                </div>
              </div>
            ))}
            {spell && spell.style.length > 0 && <p className="label first">{t('ed.style')}</p>}
            {spell?.style.map((s) => (
              <button key={`${s.rule}-${s.start}`} className="issue info" onClick={() => select(s.start, s.end)}>
                <b>«{s.text.trim() || '␣'}»</b><small>{s.message}</small>
              </button>
            ))}
          </div>
        )}

        {panel === 'meta' && (
          <div className="form">
            <label>{t('ed.status')}
              <select className="field" value={chapter.status} onChange={(e) => saveMeta({ status: e.target.value as ChapterStatus })}>
                {(['draft', 'revision', 'done'] as ChapterStatus[]).map((s) => <option key={s} value={s}>{t('chStatus.' + s)}</option>)}
              </select>
            </label>
            <label>{t('ed.storyTime')}
              <input className="field" inputMode="decimal" placeholder={t('time.key')} defaultValue={chapter.story_time_key === null ? '' : String(Number(chapter.story_time_key))}
                onBlur={(e) => saveMeta({ story_time_key: e.target.value.trim().replace(',', '.') || null })} />
              <input className="field" placeholder={t('time.label')} defaultValue={chapter.story_time_label}
                onBlur={(e) => e.target.value !== chapter.story_time_label && saveMeta({ story_time_label: e.target.value })} />
            </label>
            <small className="muted">{t('ed.storyTimeHint')}</small>
            <label className="check"><input type="checkbox" checked={chapter.is_flashback} onChange={(e) => saveMeta({ is_flashback: e.target.checked })} />{t('ed.flashback')}</label>
            <label className="check"><input type="checkbox" checked={chapter.narrator_unreliable} onChange={(e) => saveMeta({ narrator_unreliable: e.target.checked })} />{t('ed.unreliable')}</label>
          </div>
        )}
      </aside>

      {versions && (
        <Modal title={t('ed.versions')} onClose={() => { setVersions(null); setPreview(null) }} wide>
          {versions.length === 0 && <p className="muted">{t('ed.noVersions')}</p>}
          <div className="versions">
            <div className="panel-list">
              {versions.map((v) => (
                <button key={v.id} className={'issue info' + (preview?.id === v.id ? ' on' : '')} onClick={() => void run(async () => {
                  try { const d = await chaptersApi.version(bookId, chapter.id, v.id); setPreview({ id: v.id, text: d.plain_text }) } catch (err) { notify(errorText(err), 'error') }
                })}>
                  <b>{new Date(v.created_at).toLocaleString()}</b>
                  <small>{t('ver.' + v.reason)} · {v.word_count} {t('ov.words')} · r{v.revision}</small>
                </button>
              ))}
            </div>
            {preview && (
              <div className="version-preview">
                <pre>{preview.text || '—'}</pre>
                <button className="btn" disabled={busy} onClick={() => restore(preview.id)}>{t('ed.restoreVersion')}</button>
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  )
}
