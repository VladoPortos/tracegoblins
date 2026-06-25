import type { LaidOut } from './layout'
import type { PathEdge } from '../api/path'
import { PathEdges } from './PathEdges'
import { PathNodeCard } from './PathNodeCard'

export function PathCanvas({ layout, selectedId, onSelect, onEnter, isTaken, reduced, transform }: {
  layout: LaidOut; selectedId: string | null; reduced: boolean
  onSelect: (id: string) => void; onEnter: (t: { type: 'container' | 'loop'; id: string }) => void
  isTaken: (e: PathEdge) => boolean; transform: string
}) {
  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      <div style={{ position: 'absolute', left: 0, top: 0, transformOrigin: '0 0', transform }}>
        <div style={{ position: 'relative', width: layout.worldW, height: layout.worldH }}>
          <PathEdges layout={layout} isTaken={isTaken} reduced={reduced} />
          {layout.nodes.map((n) => (
            <PathNodeCard key={n.id} node={n} selected={selectedId === n.id} onSelect={onSelect} onEnter={onEnter} reduced={reduced} />
          ))}
        </div>
      </div>
    </div>
  )
}
