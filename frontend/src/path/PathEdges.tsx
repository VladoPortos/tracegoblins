import type { LaidOut, PositionedNode } from './layout'
import type { PathEdge } from '../api/path'

function edgePath(a: PositionedNode, b: PositionedNode): string {
  const sx = a.x + a.w, sy = a.y + a.h / 2, ex = b.x, ey = b.y + b.h / 2
  const dx = Math.max(48, ex - sx)
  const k = Math.abs(sy - ey) < 6 ? 0.45 : 0.55
  return `M ${sx} ${sy} C ${sx + dx * k} ${sy}, ${ex - dx * k} ${ey}, ${ex} ${ey}`
}

export function PathEdges({ layout, isTaken, reduced }: { layout: LaidOut; isTaken: (e: PathEdge) => boolean; reduced: boolean }) {
  const byId = new Map(layout.nodes.map((n) => [n.id, n]))
  return (
    <svg width={layout.worldW} height={layout.worldH} style={{ position: 'absolute', left: 0, top: 0, pointerEvents: 'none', overflow: 'visible' }}>
      {layout.edges.map((e, i) => {
        const a = byId.get(e.from), b = byId.get(e.to)
        if (!a || !b) return null
        const d = edgePath(a, b), taken = isTaken(e)
        return (
          <g key={i}>
            <path d={d} style={{ fill: 'none', stroke: taken ? 'var(--flow-dim)' : 'var(--edge-dim)', strokeWidth: taken ? 3 : 2, strokeDasharray: taken ? 'none' : '7 7', strokeLinecap: 'round', opacity: taken ? 1 : 0.5 }} />
            {taken && <path d={d} style={{ fill: 'none', stroke: 'var(--flow)', strokeWidth: 3.2, strokeLinecap: 'round', strokeDasharray: '1 26', filter: 'drop-shadow(0 0 5px var(--flow-glow))', opacity: 0.95, animation: reduced ? 'none' : 'dashflow 1.5s linear infinite' }} />}
          </g>
        )
      })}
    </svg>
  )
}
