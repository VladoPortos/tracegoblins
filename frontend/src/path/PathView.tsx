import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router'
import { useRun } from '../api/runs'
import { useRunTree } from '../api/path'
import type { PathViewRef } from '../api/path'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { layoutTree } from './layout'
import { PathCanvas } from './PathCanvas'
import { usePathController } from './usePathController'
import { PathStepper } from './PathStepper'
import { HostScopeChip } from './HostScopeChip'
import type { HostScopeId } from './HostScopeChip'
import { PathDrawer } from './PathDrawer'
import { InputsPanel } from './InputsPanel'
import { PathMinimap } from './PathMinimap'

export function PathView() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const run = useRun(id)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reduced, setReduced] = useState(false)
  const [hostScope, setHostScope] = useState<HostScopeId>('all')
  const [showInputs, setShowInputs] = useState(false)

  // Branch-taken logic: when scope is 'all' every branch is lit (all hosts took some branch).
  // When a single host is selected we would need per-host NodeResults for each branch node to
  // know which branch that host took — that requires an additional fetch per branch node and is
  // deferred to Task 13. For now, a single-host scope keeps all branches lit (no greying) rather
  // than crashing or showing wrong data. Real forks carry a `branch` field on each branch node;
  // the structural path still works, only the greying is not yet host-aware.
  const isBranchTaken = useCallback((_branch: string | null | undefined): boolean => {
    return true
  }, [])

  const isTaken = useCallback((e: { branch?: string | null }) => isBranchTaken(e.branch), [isBranchTaken])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduced(mq.matches)
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

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
  const tree = useRunTree(id, view, iter)

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

  const enter = useCallback((target: { type: 'container' | 'loop'; id: string }) => {
    setView(target as PathViewRef)
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
    // A container tree's nodes are direct children; child_count on the first 'role'/'block'/'include' node
    // mirrors the original parent's count. Fall back to the total node count in the sub-tree.
    const meta = tree.data.nodes.find(n => n.child_count != null)
    return meta?.child_count ?? tree.data.nodes.length
  }, [tree.data, view.type])

  // Breadcrumb array: root always present; container/loop add a second crumb.
  const breadcrumb = useMemo(() => {
    const crumbs: { key: string; label: string; exitRef: PathViewRef | null }[] = [
      { key: 'root', label: run.data?.template_name || 'Run', exitRef: { type: 'main' } },
    ]
    if (view.type === 'container') {
      crumbs.push({ key: 'container', label: view.id, exitRef: null })
    } else if (view.type === 'loop') {
      // Derive breadcrumb label from the loop root node in the tree; fall back to the view id.
      const loopNode = tree.data?.nodes.find(n => n.type === 'loop')
      const loopLabel = loopNode
        ? `${loopNode.label}${loopTotal != null ? ` ×${loopTotal}` : ''}`
        : view.id
      crumbs.push({ key: 'loop', label: loopLabel, exitRef: null })
    }
    return crumbs.map((c, i) => {
      const last = i === crumbs.length - 1
      return { key: c.key, label: c.label, sep: !last, last, exitRef: last ? null : c.exitRef }
    })
  }, [view, run.data, tree.data, loopTotal])

  let viewHint = ''
  if (view.type === 'main') viewHint = 'execution order · left → right'
  if (view.type === 'container') {
    viewHint = containerTaskCount != null ? `sub-flow · ${containerTaskCount} tasks` : 'sub-flow'
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

  if (tree.isPending && !layout) return <FullScreenSpinner />
  const title = run.data?.template_name || 'Day2Actions'

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
        <HostScopeChip value={hostScope} onPick={setHostScope} />
        <span className="dim" style={{ fontSize: 11 }}>{tree.data?.nodes.length ?? 0} steps</span>
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
        onMouseDown={ctrl.onMouseDown}
      >
        {layout && (
          <div style={{ position: 'absolute', inset: 0 }}>
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
          />
        )}
      </div>
    </div>
  )
}
