import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router'
import { useRun } from '../api/runs'
import { useRunTree } from '../api/path'
import type { PathViewRef, PathNode } from '../api/path'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { layoutTree } from './layout'
import { PathCanvas } from './PathCanvas'
import { usePathController } from './usePathController'
import { PathStepper } from './PathStepper'
import { HostScopeChip } from './HostScopeChip'
import type { HostScopeId } from './HostScopeChip'
import { PathDrawer } from './PathDrawer'
import { CodeOverlay } from './CodeOverlay'
import { InputsPanel } from './InputsPanel'
import { PathMinimap } from './PathMinimap'
import { useCopied } from '../components/atoms/useCopied'
import { fetchRunSummary } from '../api/pathSource'

export function PathView() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const run = useRun(id)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [sourceNodeId, setSourceNodeId] = useState<string | null>(null)
  const [reduced, setReduced] = useState(false)
  const [hostScope, setHostScope] = useState<HostScopeId>('all')
  const [showInputs, setShowInputs] = useState(false)
  const [showNeverRun, setShowNeverRun] = useState(false)

  // Copy a whole-run Markdown summary (status, recap, path-to-failure) for tickets/KB.
  const { copied: summaryCopied, copy: copyText } = useCopied()
  const [summaryBusy, setSummaryBusy] = useState(false)
  const copySummary = useCallback(async () => {
    setSummaryBusy(true)
    try { copyText(await fetchRunSummary(id)) }
    catch { /* clipboard / network errors are non-fatal */ }
    finally { setSummaryBusy(false) }
  }, [id, copyText])

  // View navigation state lives here so we can pass it to useRunTree before
  // the controller is initialized (avoids a circular deps problem between
  // ctrl.view → tree → layout → ctrl).
  const [view, setView] = useState<PathViewRef>({ type: 'main' })
  const [iter, setIter] = useState(0)
  const [animKind, setAnimKind] = useState<'in' | 'out'>('in')
  const [animKey, setAnimKey] = useState(0)
  const [animate, setAnimate] = useState(false)
  const animTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Drive tree fetch from view state.
  const tree = useRunTree(id, view, iter, showNeverRun)

  // Build a map of branchKey → taken_hosts from the current tree's fork branch nodes.
  // A fork branch node has node.branch != null and node.taken_hosts set by the backend.
  // Treat absent taken_hosts (e.g. mock fixture nodes) as "taken" to avoid false greying.
  const takenMap = useMemo<Record<string, string[]>>(() => {
    if (!tree.data) return {}
    const map: Record<string, string[]> = {}
    for (const node of tree.data.nodes as PathNode[]) {
      if (node.branch != null && node.taken_hosts != null) {
        map[node.branch] = node.taken_hosts
      }
    }
    return map
  }, [tree.data])

  // Branch-taken logic: 'all' → every branch lit; single host → grey branches the host didn't take.
  // Absent taken_hosts means unknown (fixture / old data) → treat as taken, never crash.
  const isBranchTaken = useCallback((branchKey: string | null | undefined): boolean => {
    if (branchKey === 'never_run') return false        // ghost branch — always greyed
    if (hostScope === 'all' || !branchKey) return true
    const hosts = takenMap[branchKey]
    if (hosts == null) return true  // absent means unknown → treat as taken
    return hosts.includes(hostScope)
  }, [hostScope, takenMap])

  const isTaken = useCallback((e: { branch?: string | null }) => isBranchTaken(e.branch), [isBranchTaken])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduced(mq.matches)
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  // Memoize layout. Key on tree.data identity; switching views produces a new
  // tree.data object → new layout object → controller's fit effect fires.
  const layout = useMemo(
    () => (tree.data ? layoutTree(tree.data.nodes, tree.data.edges) : null),
    [tree.data],
  )

  const triggerAnim = useCallback(() => {
    if (animTimerRef.current) clearTimeout(animTimerRef.current)
    setAnimate(true)
    setAnimKey(k => k + 1)
    animTimerRef.current = setTimeout(() => setAnimate(false), 400)
  }, [])

  const [enteredLabel, setEnteredLabel] = useState<string | null>(null)
  const enter = useCallback((target: { type: 'container' | 'loop'; id: string }, label?: string) => {
    setView(target as PathViewRef)
    setEnteredLabel(label ?? null)   // human label for the breadcrumb crumb (PATH6)
    setIter(0)
    setAnimKind('in')
    setSelectedId(null)
    triggerAnim()
  }, [triggerAnim])

  const exitTo = useCallback((ref: PathViewRef) => {
    setView(ref)
    setAnimKind('out')
    setSelectedId(null)
    triggerAnim()
  }, [triggerAnim])

  // Resolve the view-root node from the current tree (used for breadcrumb label + stepper total).
  // For loop views the loop root node (first node with item_count) carries item_count.
  // For container views the first node with child_count carries the task count.
  const loopTotal = useMemo(() => {
    if (!tree.data || view.type !== 'loop') return null
    const loopNode = tree.data.nodes.find(n => n.item_count != null)
    return loopNode?.item_count ?? null
  }, [tree.data, view.type])

  const containerTaskCount = useMemo(() => {
    if (!tree.data || view.type !== 'container') return null
    // Count the REAL direct children of this sub-flow — not an arbitrary nested child's child_count
    // (PATH5). Exclude never-run ghosts and synthetic decision nodes.
    return tree.data.nodes.filter(n => !n.never_run && n.type !== 'when').length
  }, [tree.data, view.type])

  // Breadcrumb array: root always present; container/loop add a second crumb.
  const breadcrumb = useMemo(() => {
    const crumbs: { key: string; label: string; exitRef: PathViewRef | null }[] = [
      { key: 'root', label: run.data?.template_name || 'Run', exitRef: { type: 'main' } },
    ]
    if (view.type === 'container') {
      crumbs.push({ key: 'container', label: enteredLabel || view.id, exitRef: null })
    } else if (view.type === 'loop') {
      // Derive breadcrumb label from the loop root node in the tree; fall back to the view id.
      const loopNode = tree.data?.nodes.find(n => n.type === 'loop')
      const loopLabel = loopNode
        ? `${loopNode.label}${loopTotal != null ? ` \xd7${loopTotal}` : ''}`
        : view.id
      crumbs.push({ key: 'loop', label: loopLabel, exitRef: null })
    }
    return crumbs.map((c, i) => {
      const last = i === crumbs.length - 1
      return { key: c.key, label: c.label, sep: !last, last, exitRef: last ? null : c.exitRef }
    })
  }, [view, run.data, tree.data, loopTotal, enteredLabel])

  let viewHint = ''
  if (view.type === 'main') viewHint = 'execution order \xb7 left → right'
  if (view.type === 'container') {
    viewHint = containerTaskCount != null ? `sub-flow \xb7 ${containerTaskCount} tasks` : 'sub-flow'
  }
  if (view.type === 'loop') viewHint = `iteration ${iter + 1} of ${loopTotal ?? '?'}`

  // Stepper: advance/retreat through loop iterations; clamp to real item_count (or safe default).
  const stepMax = loopTotal != null ? loopTotal - 1 : 0
  const step = useCallback((dir: 1 | -1) => {
    setIter(i => Math.max(0, Math.min(stepMax, i + dir)))
  }, [stepMax])

  // Pass layout to the controller. The controller keeps a layoutRef internally
  // and syncs it each render via useEffect, so fitView always uses current dims.
  const ctrl = usePathController(layout, () => setSelectedId(null))

  // Resolve selected node from current tree data (layout nodes are PositionedNode which extends PathNode)
  const selectedNode = useMemo(() => {
    if (!selectedId || !layout) return null
    return layout.nodes.find(n => n.id === selectedId) ?? null
  }, [selectedId, layout])

  const sourceNode = useMemo(
    () => (sourceNodeId && layout ? layout.nodes.find(n => n.id === sourceNodeId) ?? null : null),
    [sourceNodeId, layout],
  )

  if (tree.isPending && !layout) return <FullScreenSpinner />
  const title = run.data?.template_name || 'Run'

  const doAnim = animate && !reduced
  const worldAnimStyle: React.CSSProperties = {
    position: 'relative',
    width: layout?.worldW,
    height: layout?.worldH,
    transformOrigin: '50% 50%',
    animation: doAnim
      ? `${animKind === 'in' ? 'zoomIn' : 'zoomOut'} .34s cubic-bezier(.2,.7,.3,1) both`
      : 'none',
  }

  // Real per-host recap from the run; drives the host-scope triage roster (status dots + filter).
  const recap = run.data?.recap ?? []

  return (
    <div className="col" style={{ height: '100%', minWidth: 0, background: 'var(--bg)' }}>
      {/* Top bar */}
      <div className="row gap2" style={{ height: 42, padding: '0 14px', background: 'var(--surface)', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <button className="btn icon btn-ghost sm" onClick={() => nav(`/runs/${id}`)} aria-label="Back to status map">←</button>
        <div className="row gap2">
          <div style={{ width: 10, height: 10, borderRadius: 3, background: 'var(--flow)', boxShadow: '0 0 10px var(--flow-glow)' }} />
          <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{title}</span>
        </div>
        <div className="grow" />
        <button
          data-testid="inputs-toggle"
          className="btn sm btn-ghost"
          onClick={() => setShowInputs(v => !v)}
          style={{
            fontSize: 11.5, fontWeight: 600,
            color: showInputs ? 'var(--flow)' : 'var(--dim)',
            border: showInputs ? '1px solid var(--flow-line, var(--border))' : '1px solid transparent',
            borderRadius: 6, padding: '3px 9px',
          }}
          aria-label="Toggle run inputs panel"
          aria-expanded={showInputs}
        >
          Inputs
        </button>
        <button
          data-testid="never-run-toggle"
          className="btn sm btn-ghost"
          onClick={() => setShowNeverRun(v => !v)}
          style={{
            fontSize: 11.5, fontWeight: 600,
            color: showNeverRun ? 'var(--flow)' : 'var(--dim)',
            border: showNeverRun ? '1px solid var(--flow-line, var(--border))' : '1px solid transparent',
            borderRadius: 6, padding: '3px 9px',
          }}
          aria-pressed={showNeverRun}
          aria-label="Toggle never-run branches"
        >
          Never-run
        </button>
        <HostScopeChip recap={recap} value={hostScope} onPick={setHostScope} />
        <button
          data-testid="copy-summary-btn"
          className="btn sm btn-ghost"
          onClick={copySummary}
          disabled={summaryBusy}
          style={{
            fontSize: 11.5, fontWeight: 600,
            color: summaryCopied ? 'var(--ok)' : 'var(--dim)',
            border: '1px solid transparent', borderRadius: 6, padding: '3px 9px',
          }}
          title="Copy a Markdown run summary for a ticket or KB entry"
          aria-label="Copy run summary"
        >
          {summaryCopied ? 'Copied ✓' : summaryBusy ? 'Copying…' : 'Copy summary'}
        </button>
        {/* FE8: count real flow steps only — exclude never-run ghosts and synthetic decision nodes */}
        <span className="dim" style={{ fontSize: 11 }}>
          {tree.data?.nodes.filter(n => !n.never_run && n.type !== 'when').length ?? 0} steps
        </span>
      </div>

      {/* Breadcrumb row */}
      <div
        data-testid="path-breadcrumb"
        style={{
          display: 'flex', alignItems: 'center', gap: 7,
          padding: '0 16px', height: 38,
          background: 'var(--canvas, var(--bg))',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0, zIndex: 5,
        }}
      >
        {breadcrumb.map((c) => (
          <span key={c.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
            <span
              data-testid={c.last ? undefined : `crumb-${c.key}`}
              onClick={c.last ? undefined : () => c.exitRef && exitTo(c.exitRef)}
              style={{
                fontFamily: 'var(--font-mono)', fontSize: 12,
                fontWeight: c.last ? 600 : 500,
                color: c.last ? 'var(--text)' : 'var(--flow)',
                cursor: c.last ? 'default' : 'pointer',
              }}
            >
              {c.label}
            </span>
            {c.sep && <span style={{ color: 'var(--dim)', fontSize: 11 }}>›</span>}
          </span>
        ))}
        <div style={{ flex: 1 }} />
        <span className="mono dim" style={{ fontSize: 11 }}>{viewHint}</span>
      </div>

      {/* Canvas */}
      <div
        ref={ctrl.canvasRef}
        className="grow"
        data-testid="path-canvas"
        style={{ position: 'relative', overflow: 'hidden', minHeight: 0, cursor: 'grab' }}
      >
        {layout && (
          // onMouseDown lives on THIS full-canvas background layer (which holds only the world/nodes),
          // NOT the outer div — the floating panels (drawer/inputs/stepper/minimap) are siblings of
          // this layer, so their mousedowns never reach the pan/deselect handler and can't close the
          // drawer (e.g. clicking the Code tab). Background + node presses still pan/deselect normally.
          <div style={{ position: 'absolute', inset: 0 }} onMouseDown={ctrl.onMouseDown}>
            <div style={{ position: 'absolute', left: 0, top: 0, transformOrigin: '0 0', transform: ctrl.transform }}>
              {/* Animation wrapper: keyed on view+animKey to remount on each nav */}
              <div key={`${view.type}-${'id' in view ? view.id : ''}-${animKey}`} style={worldAnimStyle}>
                <PathCanvas
                  layout={layout}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  onEnter={enter}
                  isTaken={isTaken}
                  isBranchTaken={isBranchTaken}
                  reduced={reduced}
                />
              </div>
            </div>
          </div>
        )}
        {layout && ctrl.cw > 0 && (
          <PathMinimap
            layout={layout}
            panX={ctrl.panX}
            panY={ctrl.panY}
            zoom={ctrl.zoom}
            cw={ctrl.cw}
            ch={ctrl.ch}
            onJump={ctrl.panTo}
          />
        )}
        {showNeverRun && tree.data?.never_run_note && (
          <div style={{
            position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
            padding: '6px 12px', background: 'var(--surface-2)', border: '1px solid var(--border)',
            borderRadius: 8, fontSize: 11.5, color: 'var(--dim)', fontFamily: 'var(--font-mono)',
            boxShadow: 'var(--shadow-2)', zIndex: 8, pointerEvents: 'none',
          }}>
            {tree.data.never_run_note}
          </div>
        )}
        {view.type === 'loop' && loopTotal != null && loopTotal > 0 && (
          <PathStepper iter={iter} total={loopTotal} onStep={step} />
        )}
        {showInputs && <InputsPanel runId={id} />}
        {selectedNode && (
          <PathDrawer
            runId={id}
            node={selectedNode}
            iter={iter}
            hostScope={hostScope}
            reduced={reduced}
            onClose={() => setSelectedId(null)}
            onViewSource={(n) => setSourceNodeId(n.id)}
          />
        )}
        {sourceNode && (
          <CodeOverlay runId={id} node={sourceNode} onClose={() => setSourceNodeId(null)} />
        )}
      </div>
    </div>
  )
}
