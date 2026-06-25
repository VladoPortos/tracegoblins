import type { LaidOut } from './layout'
import type { PathEdge } from '../api/path'
import { PathEdges } from './PathEdges'
import { PathNodeCard } from './PathNodeCard'

export function PathCanvas({ layout, selectedId, onSelect, onEnter, isTaken, reduced }: {
  layout: LaidOut; selectedId: string | null; reduced: boolean
  onSelect: (id: string) => void; onEnter: (t: { type: 'container' | 'loop'; id: string }) => void
  isTaken: (e: PathEdge) => boolean
}) {
  return (
    <div style={{ position: 'relative', width: layout.worldW, height: layout.worldH }}>
      <PathEdges layout={layout} isTaken={isTaken} reduced={reduced} />
      {layout.nodes.map((n) => (
        <PathNodeCard key={n.id} node={n} selected={selectedId === n.id} onSelect={onSelect} onEnter={onEnter} reduced={reduced} />
      ))}
    </div>
  )
}
