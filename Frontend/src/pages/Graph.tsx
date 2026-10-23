import { useAccess } from '../access'
import {
  Background, ConnectionMode, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, applyNodeChanges,
} from '@xyflow/react'
import type { Connection, Edge, Node, NodeChange, NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useMemo, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { charactersApi } from '../api/characters'
import { factionsApi } from '../api/factions'
import { relationshipsApi } from '../api/relationships'
import type { Book, Character, CharacterStatus, Faction, Membership, Relationship, RelationshipKind } from '../api/types'
import { pagesApi } from '../api/pages'
import { worldsApi } from '../api/worlds'
import { navigate, pagePath } from '../router'
import { forceLayout } from '../components/graphLayout'
import Header from '../components/Header'
import { Confirm, ErrorState, Loading, Modal } from '../components/Ui'
import { errorText, useAsync, useBusy } from '../hooks'
import { useApp } from '../settings-context'

type View = 'factions' | 'relations'
type NodeKey = `character:${number}` | `faction:${number}`
type GNodeData = { label: string; sub: string; color: string; image?: string; dead?: boolean; dim?: boolean }
type GNode = Node<GNodeData, 'character' | 'faction'>

const REL_KINDS: RelationshipKind[] = ['alliance', 'enmity', 'family', 'subordination', 'mentorship', 'acquaintance', 'membership', 'other']
const KIND_COLOR: Record<RelationshipKind, string> = {
  alliance: '#6fd1a0', enmity: '#e5484d', family: '#e0b36a', subordination: '#7aa2ff',
  mentorship: '#3fb8c9', acquaintance: '#9aa7b8', membership: '#c58bff', other: '#8f8f8f',
}
const ARROW_KINDS = new Set<RelationshipKind>(['subordination', 'mentorship'])
const STATUSES: CharacterStatus[] = ['alive', 'dead', 'missing', 'unknown', 'other']

function CharacterNode({ data, selected }: NodeProps<Node<GNodeData, 'character'>>) {
  return (
    <div className={'gnode char-node' + (selected ? ' sel' : '') + (data.dim ? ' dim' : '')} style={{ ['--n' as string]: data.color }}>
      <Handle type="target" position={Position.Top} />
      {data.image ? <img src={data.image} alt="" draggable={false} /> : <span className="gav">{data.label[0]}</span>}
      <b>{data.label}{data.dead ? ' †' : ''}</b>
      {data.sub && <small>{data.sub}</small>}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function FactionNode({ data, selected }: NodeProps<Node<GNodeData, 'faction'>>) {
  return (
    <div className={'gnode faction-node' + (selected ? ' sel' : '')} style={{ ['--n' as string]: data.color }}>
      <Handle type="target" position={Position.Top} />
      <b>{data.label}</b>
      <small>{data.sub}</small>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

const NODE_TYPES = { character: CharacterNode, faction: FactionNode }

type GraphData = {
  characters: Character[]; factions: Faction[]; memberships: Membership[]; relationships: Relationship[]
  layouts: Record<View, Record<string, [number, number]>>; version: number
}

let loadCounter = 0

export default function Graph({ book }: { book: Book }) {
  const { t, theme, notify } = useApp()
  const { edit } = useAccess()
  const worldId = book.world
  const [view, setView] = useState<View>('relations')
  const [familyOnly, setFamilyOnly] = useState(false)
  const data = useAsync<GraphData>(async (signal) => {
    const [characters, factions, memberships, relationships, rel, fac] = await Promise.all([
      charactersApi.list(worldId, {}, signal), factionsApi.list(worldId, signal), factionsApi.memberships(worldId),
      relationshipsApi.list(worldId), worldsApi.graphLayout(worldId, 'relations', signal), worldsApi.graphLayout(worldId, 'factions', signal),
    ])
    loadCounter += 1
    return { characters, factions, memberships, relationships, layouts: { relations: rel.positions, factions: fac.positions }, version: loadCounter }
  }, [worldId])
  const [flow, setFlow] = useState<{ key: string; nodes: GNode[] }>({ key: '', nodes: [] })
  const [selected, setSelected] = useState<{ type: 'node' | 'edge'; id: string } | null>(null)
  const [connecting, setConnecting] = useState<{ source: NodeKey; target: NodeKey } | null>(null)
  const [creating, setCreating] = useState<'character' | 'faction' | null>(null)
  const [deleting, setDeleting] = useState<{ label: string; run: () => Promise<unknown> } | null>(null)
  const saveTimer = useRef<number | undefined>(undefined)
  const { busy, run } = useBusy()
  const d = data.data

  const nodeKeys = useMemo<NodeKey[]>(() => {
    if (!d) return []
    const chars = d.characters.map((c) => `character:${c.id}` as NodeKey)
    return view === 'relations' ? chars : [...d.factions.map((f) => `faction:${f.id}` as NodeKey), ...chars]
  }, [d, view])

  const edges = useMemo<Edge[]>(() => {
    if (!d) return []
    const keys = new Set<string>(nodeKeys)
    const out: Edge[] = []
    for (const r of d.relationships) {
      const s = `${r.source.type}:${r.source.id}`
      const tg = `${r.target.type}:${r.target.id}`
      if (!keys.has(s) || !keys.has(tg)) continue
      if (view === 'factions' && r.source.type !== 'faction' && r.target.type !== 'faction') continue
      const color = KIND_COLOR[r.kind]
      const dim = familyOnly && r.kind !== 'family'
      out.push({
        id: `rel:${r.id}`, source: s, target: tg, label: t('relKind.' + r.kind),
        style: { stroke: color, strokeWidth: r.kind === 'family' ? 3 : 2, opacity: dim ? 0.12 : 1 },
        labelStyle: { fill: color, fontWeight: 600, opacity: dim ? 0.2 : 1 },
        labelBgStyle: { fill: 'var(--card)' },
        markerEnd: ARROW_KINDS.has(r.kind) ? { type: MarkerType.ArrowClosed, color } : undefined,
        selected: selected?.type === 'edge' && selected.id === `rel:${r.id}`,
      })
    }
    if (view === 'factions') {
      for (const m of d.memberships) {
        const f = d.factions.find((x) => x.id === m.faction)
        out.push({
          id: `mem:${m.id}`, source: `character:${m.character}`, target: `faction:${m.faction}`,
          label: m.role || undefined, style: { stroke: f?.color ?? '#c58bff', strokeDasharray: '6 4', strokeWidth: 2 },
          labelStyle: { fill: f?.color ?? '#c58bff' }, labelBgStyle: { fill: 'var(--card)' },
          selected: selected?.type === 'edge' && selected.id === `mem:${m.id}`,
        })
      }
    }
    return out
  }, [d, view, nodeKeys, familyOnly, selected, t])

  /** Build nodes: keep on-screen positions, then saved layout, then place new nodes automatically. */
  const buildNodes = useCallback((relayout: boolean): GNode[] => {
    if (!d) return []
    const current = Object.fromEntries(flow.nodes.map((n) => [n.id, n.position]))
    const saved = d.layouts[view]
    const fixed: Record<string, { x: number; y: number }> = {}
    if (!relayout) {
      for (const k of nodeKeys) {
        if (current[k] && flow.key.startsWith(view)) fixed[k] = current[k]
        else if (saved[k]) fixed[k] = { x: saved[k][0], y: saved[k][1] }
      }
    }
    const pos = forceLayout(nodeKeys, edges.map((e) => [e.source, e.target]), fixed)
    const familyIds = new Set(d.relationships.filter((r) => r.kind === 'family').flatMap((r) => [`${r.source.type}:${r.source.id}`, `${r.target.type}:${r.target.id}`]))
    return nodeKeys.map((k) => {
      const [type, raw] = k.split(':')
      const id = Number(raw)
      if (type === 'faction') {
        const f = d.factions.find((x) => x.id === id)!
        return { id: k, type: 'faction', position: pos[k], data: { label: `${f.emblem ? f.emblem + ' ' : ''}${f.name}`, sub: `${f.members_count} ${t('gr.members')}`, color: f.color } }
      }
      const c = d.characters.find((x) => x.id === id)!
      const faction = c.memberships[0]
      return {
        id: k, type: 'character', position: pos[k],
        data: {
          label: c.name, sub: faction?.faction_name ?? '', color: faction?.faction_color ?? '#7aa2ff',
          image: c.has_portrait ? charactersApi.portraitUrl(worldId, c) : undefined, dead: c.status === 'dead',
          dim: familyOnly && view === 'relations' && !familyIds.has(k),
        },
      }
    })
  }, [d, view, nodeKeys, edges, flow, familyOnly, t, worldId])

  // Rebuild nodes when data, view or the family filter change (state adjusted during render).
  const flowKey = d ? `${view}:${d.version}:${familyOnly}` : ''
  if (d && flow.key !== flowKey) setFlow({ key: flowKey, nodes: buildNodes(false) })

  const persist = (nodes: GNode[]) => {
    if (!edit) return  // readers may move nodes to look around; the shared layout is not changed
    window.clearTimeout(saveTimer.current)
    const positions = Object.fromEntries(nodes.map((n) => [n.id, [n.position.x, n.position.y] as [number, number]]))
    saveTimer.current = window.setTimeout(() => {
      worldsApi.saveGraphLayout(worldId, view, positions).catch((err) => notify(errorText(err), 'error'))
    }, 500)
  }

  const onNodesChange = (changes: NodeChange<GNode>[]) => setFlow((f) => ({ ...f, nodes: applyNodeChanges(changes, f.nodes) }))

  const relayout = () => {
    const nodes = buildNodes(true)
    setFlow((f) => ({ ...f, nodes }))
    persist(nodes)
  }

  const onConnect = (c: Connection) => {
    if (!c.source || !c.target || c.source === c.target) return
    setConnecting({ source: c.source as NodeKey, target: c.target as NodeKey })
  }

  const reload = data.reload
  /** Characters and factions are edited on their encyclopedia page (created on demand if missing). */
  const openPage = (type: 'character' | 'faction', id: number, pageId: number | null) => {
    if (pageId) { navigate(pagePath(book.id, pageId)); return }
    pagesApi.byEntity(worldId, type, id).then((p) => navigate(pagePath(book.id, p.id))).catch((err) => notify(errorText(err), 'error'))
  }
  const guard = (action: () => Promise<unknown>) => void run(async () => {
    try { await action(); reload() } catch (err) { notify(errorText(err), 'error') }
  })

  const selectedRel = selected?.type === 'edge' && selected.id.startsWith('rel:') ? d?.relationships.find((r) => `rel:${r.id}` === selected.id) : undefined
  const selectedMem = selected?.type === 'edge' && selected.id.startsWith('mem:') ? d?.memberships.find((m) => `mem:${m.id}` === selected.id) : undefined
  const selectedChar = selected?.type === 'node' && selected.id.startsWith('character:') ? d?.characters.find((c) => `character:${c.id}` === selected.id) : undefined
  const selectedFaction = selected?.type === 'node' && selected.id.startsWith('faction:') ? d?.factions.find((f) => `faction:${f.id}` === selected.id) : undefined
  const nameOf = (key: string) => {
    const [type, id] = key.split(':')
    return type === 'faction' ? d?.factions.find((f) => f.id === Number(id))?.name : d?.characters.find((c) => c.id === Number(id))?.name
  }

  return (
    <>
      <div className="page-head">
        <Header title={t('s.graph')} sub={t('gr.sub')} />
        <div className="head-acts">
          <div className="seg">
            <button className={view === 'relations' ? 'on' : ''} onClick={() => { setView('relations'); setSelected(null) }}>{t('gr.relations')}</button>
            <button className={view === 'factions' ? 'on' : ''} onClick={() => { setView('factions'); setSelected(null) }}>{t('gr.factions')}</button>
          </div>
          {edit && <button className="btn-ghost" onClick={() => setCreating('character')}>+ {t('search.character')}</button>}
          {edit && <button className="btn-ghost" onClick={() => setCreating('faction')}>+ {t('search.faction')}</button>}
          {edit && <button className="btn-ghost" onClick={relayout} disabled={!d}>{t('gr.relayout')}</button>}
        </div>
      </div>
      <ErrorState error={data.error} onRetry={data.reload} />
      {data.loading && !d ? <Loading /> : d && (
        <div className="graph-wrap">
          <div className="graph-canvas">
            {nodeKeys.length === 0 && <p className="graph-empty muted">{t('gr.empty')}</p>}
            <ReactFlow<GNode, Edge>
              key={view} fitViewOptions={{ padding: 0.25, maxZoom: 1.1 }}
              nodes={flow.nodes} edges={edges} nodeTypes={NODE_TYPES} onNodesChange={onNodesChange}
              onNodeDragStop={(_, __, dragged) => {
                const moved = new Map(dragged.map((n) => [n.id, n.position]))
                persist(flow.nodes.map((n) => (moved.has(n.id) ? { ...n, position: moved.get(n.id)! } : n)))
              }}
              onNodeClick={(_, n) => setSelected({ type: 'node', id: n.id })}
              onEdgeClick={(_, e) => setSelected({ type: 'edge', id: e.id })}
              onPaneClick={() => setSelected(null)}
              onConnect={onConnect} connectionMode={ConnectionMode.Loose} nodesConnectable={edit}
              deleteKeyCode={null} colorMode={theme} fitView minZoom={0.1} maxZoom={2.5} proOptions={{ hideAttribution: true }}
            >
              <Background gap={24} />
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable nodeColor={(n) => (n.data as GNodeData).color} />
            </ReactFlow>
          </div>
          <aside className="graph-side">
            {!selected && (
              <div className="panel-list">
                <p className="muted">{t('gr.help')}</p>
                {view === 'relations' && (
                  <label className="check"><input type="checkbox" checked={familyOnly} onChange={(e) => setFamilyOnly(e.target.checked)} />{t('gr.familyOnly')}</label>
                )}
                <p className="label first">{t('gr.legend')}</p>
                {REL_KINDS.filter((k) => view === 'factions' || k !== 'membership').map((k) => (
                  <span key={k} className="legend"><i style={{ background: KIND_COLOR[k] }} />{t('relKind.' + k)}</span>
                ))}
                {view === 'factions' && <span className="legend"><i className="dashed" />{t('gr.memberEdge')}</span>}
              </div>
            )}
            {selectedChar && (
              <NodePanel key={selectedChar.id} title={selectedChar.name} canDelete={edit} onEdit={() => openPage('character', selectedChar.id, selectedChar.page_id)}
                onDelete={() => setDeleting({ label: selectedChar.name, run: () => charactersApi.remove(worldId, selectedChar.id) })}>
                <label>{t('cf.status')}
                  <select className="field" value={selectedChar.status} disabled={busy || !edit}
                    onChange={(e) => guard(() => charactersApi.update(worldId, selectedChar.id, { status: e.target.value as CharacterStatus }))}>
                    {STATUSES.map((s) => <option key={s} value={s}>{t('status.' + s)}</option>)}
                  </select>
                </label>
                {selectedChar.summary && <p>{selectedChar.summary}</p>}
                {edit && <LinkTo nodeKey={`character:${selectedChar.id}`} keys={nodeKeys} nameOf={nameOf} onPick={(target) => setConnecting({ source: `character:${selectedChar.id}`, target })} />}
                <Connections nodeKey={`character:${selectedChar.id}`} edges={edges} nameOf={nameOf} onPick={(id) => setSelected({ type: 'edge', id })} />
              </NodePanel>
            )}
            {selectedFaction && (
              <NodePanel key={selectedFaction.id} title={selectedFaction.name} canDelete={edit} onEdit={() => openPage('faction', selectedFaction.id, selectedFaction.page_id)}
                onDelete={() => setDeleting({ label: selectedFaction.name, run: () => factionsApi.remove(worldId, selectedFaction.id) })}>
                <label>{t('ui.color')}
                  <input className="field color" type="color" defaultValue={selectedFaction.color} disabled={!edit}
                    onBlur={(e) => e.target.value !== selectedFaction.color && guard(() => factionsApi.update(worldId, selectedFaction.id, { color: e.target.value }))} />
                </label>
                {selectedFaction.description && <p>{selectedFaction.description}</p>}
                {edit && <LinkTo nodeKey={`faction:${selectedFaction.id}`} keys={nodeKeys} nameOf={nameOf} onPick={(target) => setConnecting({ source: `faction:${selectedFaction.id}`, target })} />}
                <Connections nodeKey={`faction:${selectedFaction.id}`} edges={edges} nameOf={nameOf} onPick={(id) => setSelected({ type: 'edge', id })} />
              </NodePanel>
            )}
            {selectedRel && (
              <div className="form" key={selectedRel.id}>
                <h3>{selectedRel.source.label} — {selectedRel.target.label}</h3>
                <label>{t('gr.kind')}
                  <select className="field" value={selectedRel.kind} disabled={busy || !edit}
                    onChange={(e) => guard(() => relationshipsApi.update(worldId, selectedRel.id, { kind: e.target.value as RelationshipKind }))}>
                    {REL_KINDS.map((k) => <option key={k} value={k}>{t('relKind.' + k)}</option>)}
                  </select>
                </label>
                <label>{t('ui.description')}
                  <textarea className="field" defaultValue={selectedRel.description} readOnly={!edit}
                    onBlur={(e) => e.target.value !== selectedRel.description && guard(() => relationshipsApi.update(worldId, selectedRel.id, { description: e.target.value }))} />
                </label>
                {edit && <button className="btn-ghost danger-text" onClick={() => setDeleting({ label: t('relKind.' + selectedRel.kind), run: () => relationshipsApi.remove(worldId, selectedRel.id) })}>{t('ui.delete')}</button>}
              </div>
            )}
            {selectedMem && (
              <div className="form" key={selectedMem.id}>
                <h3>{selectedMem.character_name} → {selectedMem.faction_name}</h3>
                <label>{t('cf.role')}
                  <input className="field" defaultValue={selectedMem.role} readOnly={!edit}
                    onBlur={(e) => e.target.value !== selectedMem.role && guard(() => factionsApi.updateMembership(worldId, selectedMem.id, { role: e.target.value }))} />
                </label>
                {edit && <button className="btn-ghost danger-text" onClick={() => setDeleting({ label: t('gr.memberEdge'), run: () => factionsApi.removeMembership(worldId, selectedMem.id) })}>{t('ui.delete')}</button>}
              </div>
            )}
          </aside>
        </div>
      )}
      {connecting && d && (
        <ConnectDialog worldId={worldId} source={connecting.source} target={connecting.target} nameOf={nameOf}
          onClose={() => setConnecting(null)} onDone={() => { setConnecting(null); reload() }} />
      )}
      {creating && (
        <QuickCreate kind={creating} worldId={worldId} onClose={() => setCreating(null)} onDone={() => { setCreating(null); reload() }} />
      )}
      {deleting && (
        <Confirm title={t('ui.confirmDelete')} text={deleting.label} confirmLabel={t('ui.delete')} busy={busy}
          onCancel={() => setDeleting(null)}
          onConfirm={() => { const action = deleting.run; setDeleting(null); setSelected(null); guard(action) }} />
      )}
    </>
  )
}

function NodePanel({ title, canDelete, onEdit, onDelete, children }: { title: string; canDelete: boolean; onEdit: () => void; onDelete: () => void; children: ReactNode }) {
  const { t } = useApp()
  return (
    <div className="form">
      <h3>{title}</h3>
      {children}
      <div className="head-acts">
        <button className="btn-ghost" onClick={onEdit}>{t('gr.openCard')}</button>
        {canDelete && <button className="btn-ghost danger-text" onClick={onDelete}>{t('ui.delete')}</button>}
      </div>
    </div>
  )
}

/** Button-based alternative to dragging a link between two nodes. */
function LinkTo({ nodeKey, keys, nameOf, onPick }: { nodeKey: NodeKey; keys: NodeKey[]; nameOf: (k: string) => string | undefined; onPick: (k: NodeKey) => void }) {
  const { t } = useApp()
  const [target, setTarget] = useState('')
  return (
    <div className="fact-row">
      <select className="field" value={target} onChange={(e) => setTarget(e.target.value)} aria-label={t('gr.linkTo')}>
        <option value="">{t('gr.linkTo')}</option>
        {keys.filter((k) => k !== nodeKey).map((k) => <option key={k} value={k}>{nameOf(k)}</option>)}
      </select>
      <button type="button" className="btn-ghost" disabled={!target} onClick={() => { onPick(target as NodeKey); setTarget('') }}>{t('ui.add')}</button>
    </div>
  )
}

function Connections({ nodeKey, edges, nameOf, onPick }: { nodeKey: string; edges: Edge[]; nameOf: (k: string) => string | undefined; onPick: (id: string) => void }) {
  const { t } = useApp()
  const mine = edges.filter((e) => e.source === nodeKey || e.target === nodeKey)
  if (!mine.length) return <p className="muted">{t('gr.noLinks')}</p>
  return (
    <div className="panel-list">
      {mine.map((e) => (
        <button key={e.id} className="issue info" onClick={() => onPick(e.id)}>
          <b>{nameOf(e.source === nodeKey ? e.target : e.source)}</b>
          <small>{String(e.label ?? t('gr.memberEdge'))}</small>
        </button>
      ))}
    </div>
  )
}

/** Created after dragging from one node to another. */
function ConnectDialog({ worldId, source, target, nameOf, onClose, onDone }: {
  worldId: number; source: NodeKey; target: NodeKey; nameOf: (k: string) => string | undefined; onClose: () => void; onDone: () => void
}) {
  const { t, notify } = useApp()
  const [sType, sId] = source.split(':') as ['character' | 'faction', string]
  const [tType, tId] = target.split(':') as ['character' | 'faction', string]
  const charToFaction = sType !== tType
  const [kind, setKind] = useState<RelationshipKind | 'member'>(charToFaction ? 'member' : 'alliance')
  const [text, setText] = useState('')
  const { busy, run } = useBusy()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      try {
        if (kind === 'member') {
          const character = Number(sType === 'character' ? sId : tId)
          const faction = Number(sType === 'faction' ? sId : tId)
          await factionsApi.addMembership(worldId, { character, faction, role: text })
        } else {
          await relationshipsApi.create(worldId, {
            kind, description: text, directed: ARROW_KINDS.has(kind),
            source: { type: sType, id: Number(sId) }, target: { type: tType, id: Number(tId) },
          })
        }
        onDone()
      } catch (err) { notify(errorText(err), 'error') }
    })
  }
  return (
    <Modal title={`${nameOf(source)} → ${nameOf(target)}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>{t('gr.kind')}
          <select className="field" value={kind} onChange={(e) => setKind(e.target.value as RelationshipKind | 'member')} autoFocus>
            {charToFaction && <option value="member">{t('gr.memberEdge')}</option>}
            {REL_KINDS.filter((k) => !(charToFaction && k === 'membership')).map((k) => <option key={k} value={k}>{t('relKind.' + k)}</option>)}
          </select>
        </label>
        {ARROW_KINDS.has(kind as RelationshipKind) && <small className="muted">{t('gr.directionHint')}</small>}
        <label>{kind === 'member' ? t('cf.role') : t('ui.description')}
          <input className="field" value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <div className="acts">
          <span className="spacer" />
          <button type="button" className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
          <button className="btn" disabled={busy}>{t('ui.create')}</button>
        </div>
      </form>
    </Modal>
  )
}

function QuickCreate({ kind, worldId, onClose, onDone }: { kind: 'character' | 'faction'; worldId: number; onClose: () => void; onDone: () => void }) {
  const { t, notify } = useApp()
  const [name, setName] = useState('')
  const [color, setColor] = useState('#e879a8')
  const { busy, run } = useBusy()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      try {
        if (kind === 'character') await charactersApi.create(worldId, { name: name.trim() })
        else await factionsApi.create(worldId, { name: name.trim(), color })
        onDone()
      } catch (err) { notify(errorText(err), 'error') }
    })
  }
  return (
    <Modal title={kind === 'character' ? t('cf.new') : t('ff.new')} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>{kind === 'character' ? t('cf.name') : t('ui.title')}<input className="field" required autoFocus value={name} onChange={(e) => setName(e.target.value)} /></label>
        {kind === 'faction' && <label>{t('ui.color')}<input className="field color" type="color" value={color} onChange={(e) => setColor(e.target.value)} /></label>}
        <div className="acts">
          <span className="spacer" />
          <button type="button" className="btn-ghost" onClick={onClose}>{t('ui.cancel')}</button>
          <button className="btn" disabled={busy || !name.trim()}>{t('ui.create')}</button>
        </div>
      </form>
    </Modal>
  )
}
