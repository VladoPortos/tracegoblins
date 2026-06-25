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

  // Per prototype lines 424–429: all → every branch taken; single RedHat host → redhat only; win-01 → windows only.
  const isBranchTaken = useCallback((branch: string | null | undefined): boolean => {
    if (!branch || hostScope === 'all') return true
    const isWin = hostScope === 'win-01'
    return isWin ? branch === 'windows' : branch === 'redhat'
  }, [hostScope])

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

  // Breadcrumb array: root always present; container/loop add a second crumb.
  const breadcrumb = useMemo(() => {
    const crumbs: { key: string; label: string; exitRef: PathViewRef | null }[] = [
      { key: 'root', label: 'Day2Actions', exitRef: { type: 'main' } },
    ]
    if (view.type === 'container') {
      crumbs.push({ key: 'container', label: view.id, exitRef: null })
    } else if (view.type === 'loop') {
      crumbs.push({ key: 'loop', label: 'install packages ×50', exitRef: null })
    }
    return crumbs.map((c, i) => {
      const last = i === crumbs.length - 1
      return { key: c.key, label: c.label, sep: !last, last, exitRef: last ? null : c.exitRef }
    })
  }, [view])

  let viewHint = ''
  if (view.type === 'main') viewHint = 'execution order · left → right'
  if (view.type === 'container') viewHint = 'sub-flow · 12 tasks'
  if (view.type === 'loop') viewHint = `iteration ${iter + 1} of 50`

  // Stepper: advance/retreat through loop iterations; clamp to 0..49.
  const step = useCallback((dir: 1 | -1) => {
    setIter(i => Math.max(0, Math.min(49, i + dir)))
  }, [])

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
                  hostScope={hostScope}
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
        {view.type === 'loop' && (
          <PathStepper iter={iter} total={50} onStep={step} />
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
