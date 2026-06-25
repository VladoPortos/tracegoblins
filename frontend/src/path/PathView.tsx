import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router'
import { useRun } from '../api/runs'
import { useRunTree } from '../api/path'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { layoutTree } from './layout'
import { PathCanvas } from './PathCanvas'

export function PathView() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const run = useRun(id)
  const tree = useRunTree(id, { type: 'main' })

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reduced, setReduced] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduced(mq.matches)
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  if (tree.isPending) return <FullScreenSpinner />
  const title = run.data?.template_name || 'Day2Actions'

  const layout = tree.data ? layoutTree(tree.data.nodes, tree.data.edges) : null

  const onEnter = (_t: { type: 'container' | 'loop'; id: string }) => {
    // no-op for now; Task 7+ will navigate into containers/loops
  }

  return (
    <div className="col" style={{ height: '100%', minWidth: 0, background: 'var(--bg)' }}>
      <div className="row gap2" style={{ height: 42, padding: '0 14px', background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
        <button className="btn icon btn-ghost sm" onClick={() => nav(`/runs/${id}`)} aria-label="Back to status map">←</button>
        <div className="row gap2">
          <div style={{ width: 10, height: 10, borderRadius: 3, background: 'var(--flow)', boxShadow: '0 0 10px var(--flow-glow)' }} />
          <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{title}</span>
        </div>
        <span className="dim mono" style={{ fontSize: 11 }}>execution order · left → right</span>
        <div className="grow" />
        <span className="dim" style={{ fontSize: 11 }}>{tree.data?.nodes.length ?? 0} steps</span>
      </div>
      <div className="grow" data-testid="path-canvas" style={{ position: 'relative', overflow: 'hidden', minHeight: 0 }}>
        {layout && (
          <PathCanvas
            layout={layout}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onEnter={onEnter}
            isTaken={() => true}
            reduced={reduced}
            transform="translate(40px,40px) scale(0.62)"
          />
        )}
      </div>
    </div>
  )
}
