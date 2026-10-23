import { useAccess } from '../access'
import { useEffect, useMemo, useState } from 'react'
import { analysisApi } from '../api/analysis'
import { chaptersApi } from '../api/chapters'
import type { AIStatus, AnalysisJob, Book, ChapterSummary, Decision, Evidence, Finding, FindingCategory, JobKind } from '../api/types'
import Header from '../components/Header'
import Icon from '../components/Icon'
import { Empty, ErrorState, Loading } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { navigate, projectPath } from '../router'
import { useApp } from '../settings-context'
import type { Section } from '../types'

const ACTIVE = new Set(['pending', 'running'])
const CATEGORIES: FindingCategory[] = ['confirmed', 'potential', 'insufficient_data', 'unverified']
const DECISIONS: Decision[] = ['accepted', 'rejected', 'ignored']
const EVIDENCE_SECTION: Partial<Record<Evidence['source_type'], Section>> = {
  chapter: 'book', character: 'encyclopedia', faction: 'encyclopedia', lore: 'encyclopedia', page: 'encyclopedia', event: 'timeline',
}

export default function Analysis({ book }: { book: Book }) {
  const { t, notify } = useApp()
  const { edit } = useAccess()
  const jobs = useAsync((signal) => analysisApi.jobs({ book: book.id }, signal).then((p) => p.results), [book.id])
  const ai = useAsync<AIStatus>((signal) => analysisApi.aiStatus(signal), [])
  const chapters = useAsync<ChapterSummary[]>((signal) => chaptersApi.list(book.id, signal), [book.id])
  const [selected, setSelected] = useState<number | null>(null)
  const [deepKind, setDeepKind] = useState<Exclude<JobKind, 'consistency' | 'fragment'>>('book_with_lore')
  const [chapterId, setChapterId] = useState<number | null>(null)
  const { busy, run } = useBusy()

  const list = jobs.data ?? []
  const current = list.find((j) => j.id === selected) ?? list[0]
  const hasActive = list.some((j) => ACTIVE.has(j.status))

  // Poll while a job is pending/running (the worker updates progress in the DB).
  const reloadJobs = jobs.reload
  useEffect(() => {
    if (!hasActive) return
    const timer = window.setInterval(reloadJobs, 2500)
    return () => window.clearInterval(timer)
  }, [hasActive, reloadJobs])

  const runChecks = () => void run(async () => {
    try {
      const job = await analysisApi.runConsistency(book.world, book.id)
      jobs.setData((prev) => [job, ...(prev ?? [])])
      setSelected(job.id)
    } catch (err) { notify(errorText(err), 'error') }
  })

  const runDeep = () => void run(async () => {
    try {
      const chapter = deepKind === 'chapter' ? chapterId ?? chapters.data?.[0]?.id : undefined
      const job = await analysisApi.createJob({ kind: deepKind, book: book.id, chapter })
      jobs.setData((prev) => [job, ...(prev ?? []).filter((j) => !(j.status === 'pending' && j.kind === job.kind))])
      setSelected(job.id)
    } catch (err) { notify(errorText(err), 'error') }
  })

  const cancel = (job: AnalysisJob) => void run(async () => {
    try { await analysisApi.cancel(job.id); jobs.reload() } catch (err) { notify(errorText(err), 'error') }
  })

  if (!edit) {
    // Checks and their findings are working tools of the people who edit the text.
    return <><Header title={t('s.analysis')} sub={t('an.sub')} /><Empty title={t('ro.analysisTitle')} text={t('ro.analysisText')} /></>
  }

  return (
    <>
      <Header title={t('s.analysis')} sub={t('an.sub')} />
      <div className="an-grid">
        <div className="panel an-card">
          <h3><Icon n="check" />{t('an.rulesTitle')}</h3>
          <p>{t('an.rulesText')}</p>
          <button className="btn" onClick={runChecks} disabled={busy}>{t('an.runRules')}</button>
        </div>
        <div className="panel an-card">
          <h3><Icon n="logo" />{t('an.deepTitle')}</h3>
          <p>{t('an.deepText')}</p>
          <div className="ai-status">
            {ai.loading ? <span className="muted">{t('ui.loading')}</span> : ai.data?.available
              ? <span className="ok"><Icon n="check" />{t('an.aiReady')}: {ai.data.model}</span>
              : <span className="warn">{ai.data?.server ? `${t('an.modelMissing')}: ${ai.data.model}` : t('an.aiOffline')}</span>}
            {ai.data?.queue && <small className="muted"> · {t('an.queue')}: {ai.data.queue.pending}/{ai.data.queue.running}</small>}
            <button className="link" onClick={ai.reload}>↻</button>
          </div>
          <div className="row2">
            <select className="field" value={deepKind} onChange={(e) => setDeepKind(e.target.value as typeof deepKind)}>
              <option value="chapter">{t('jobKind.chapter')}</option>
              <option value="book">{t('jobKind.book')}</option>
              <option value="book_with_lore">{t('jobKind.book_with_lore')}</option>
            </select>
            {deepKind === 'chapter' && (
              <select className="field" value={chapterId ?? ''} onChange={(e) => setChapterId(Number(e.target.value))}>
                {chapters.data?.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
            )}
          </div>
          <button className="btn" onClick={runDeep} disabled={busy || (deepKind === 'chapter' && !chapters.data?.length)}>{t('an.runDeep')}</button>
          {!ai.data?.available && <small className="muted">{t('an.deepWithoutAi')}</small>}
        </div>
      </div>

      <ErrorState error={jobs.error} onRetry={jobs.reload} />
      {jobs.loading && !jobs.data ? <Loading /> : list.length === 0 ? (
        <Empty title={t('an.emptyTitle')} text={t('an.emptyText')} />
      ) : (
        <div className="an-layout">
          <div className="panel-list jobs">
            {list.map((j) => (
              <button key={j.id} className={'issue ' + (j.id === current?.id ? 'on ' : '') + (j.status === 'failed' ? 'error' : 'info')} onClick={() => setSelected(j.id)}>
                <b>{t('jobKind.' + j.kind)}</b>
                <small>{new Date(j.created_at).toLocaleString()} · {t('jobStatus.' + j.status)}{j.status === 'completed' ? ` · ${j.findings_count}` : ''}</small>
                {ACTIVE.has(j.status) && <div className="bar"><i style={{ width: `${Math.round(j.progress * 100)}%` }} /></div>}
              </button>
            ))}
          </div>
          {current && <JobView key={current.id} job={current} book={book} onCancel={() => cancel(current)} />}
        </div>
      )}
    </>
  )
}

function JobView({ job, book, onCancel }: { job: AnalysisJob; book: Book; onCancel: () => void }) {
  const { t } = useApp()
  const done = job.status === 'completed'
  const findings = useAsync<Finding[]>((signal) => (done ? analysisApi.results(job.id, signal) : Promise.resolve([])), [job.id, done])
  const [filter, setFilter] = useState<'open' | 'all'>('open')
  const visible = useMemo(() => (findings.data ?? []).filter((f) => filter === 'all' || f.decision === 'new'), [findings.data, filter])

  return (
    <div className="job-view">
      <div className="job-head">
        <div>
          <h3>{t('jobKind.' + job.kind)} — {t('jobStatus.' + job.status)}</h3>
          <small className="muted">
            {job.progress_message}
            {job.stats.seconds !== undefined && ` · ${job.stats.seconds} s`}
            {job.stats.quotes_total ? ` · ${t('an.quotes')}: ${job.stats.quotes_verified}/${job.stats.quotes_total}` : ''}
            {job.model_name && ` · ${job.model_name}`}
          </small>
        </div>
        {ACTIVE.has(job.status) && <button className="btn-ghost" onClick={onCancel} disabled={job.cancel_requested}>{t('ui.cancel')}</button>}
      </div>
      {job.error_message && <p className={job.status === 'failed' ? 'field-error' : 'notice'}>{job.error_message}</p>}
      {job.status === 'pending' && <p className="muted">{t('an.pendingHint')}</p>}
      {done && (
        <>
          <div className="tabs">
            <button className={'tab' + (filter === 'open' ? ' on' : '')} onClick={() => setFilter('open')}>{t('an.open')}</button>
            <button className={'tab' + (filter === 'all' ? ' on' : '')} onClick={() => setFilter('all')}>{t('an.all')}</button>
          </div>
          <ErrorState error={findings.error} onRetry={findings.reload} />
          {findings.loading && !findings.data ? <Loading /> : visible.length === 0 ? <p className="ok"><Icon n="check" />{t('an.noFindings')}</p> : (
            CATEGORIES.map((cat) => {
              const items = visible.filter((f) => f.category === cat)
              if (!items.length) return null
              return (
                <section key={cat}>
                  <p className="label first">{t('cat2.' + cat)} · {items.length}</p>
                  {items.map((f) => <FindingCard key={f.id} finding={f} book={book}
                    onChange={(nf) => findings.setData((prev) => (prev ?? []).map((x) => (x.id === nf.id ? nf : x)))} />)}
                </section>
              )
            })
          )}
        </>
      )}
    </div>
  )
}

function FindingCard({ finding: f, book, onChange }: { finding: Finding; book: Book; onChange: (f: Finding) => void }) {
  const { t, notify } = useApp()
  const [explanation, setExplanation] = useState<string | null>(null)
  const { busy, run } = useBusy()
  const decide = (decision: Decision) => void run(async () => {
    try { onChange(await analysisApi.decide(f.id, f.decision === decision ? 'new' : decision)) } catch (err) { notify(errorText(err), 'error') }
  })
  const explain = () => void run(async () => {
    try { setExplanation((await analysisApi.explain(f.id)).explanation) } catch (err) { notify(errorText(err), 'error') }
  })
  const openEvidence = (e: Evidence) => {
    const section = EVIDENCE_SECTION[e.source_type]
    if (section) navigate(projectPath(book.id, section, `${e.source_type}:${e.source_id}`))
  }
  return (
    <div className={'finding ' + f.severity + (f.decision !== 'new' ? ' decided' : '')}>
      <div className="finding-head">
        <b>{f.summary}</b>
        <span className="tag">{t('source.' + f.source)}{f.confidence !== null ? ` · ${Math.round(f.confidence * 100)}%` : ''}</span>
      </div>
      {f.explanation && <p>{f.explanation}</p>}
      {f.evidence.length > 0 && (
        <ul className="evidence">
          {f.evidence.map((e) => (
            <li key={e.id}>
              <button className="link" onClick={() => openEvidence(e)}>{t('evidence.' + e.source_type)}: {e.source_label}</button>
              {e.quote && <q>{e.quote}</q>}
              {e.quote && <small className={e.verified ? 'ok' : 'warn'}>{e.verified ? t('an.verified') : t('an.unverified')}</small>}
            </li>
          ))}
        </ul>
      )}
      {explanation && <p className="notice">{explanation} <small className="muted">({t('an.aiNote')})</small></p>}
      <div className="note-acts">
        {DECISIONS.map((d) => (
          <button key={d} className={'link' + (f.decision === d ? ' active' : '')} disabled={busy} onClick={() => decide(d)}>{t('decision.' + d)}</button>
        ))}
        <button className="link" disabled={busy} onClick={explain}>{t('an.explain')}</button>
      </div>
    </div>
  )
}
