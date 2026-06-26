import type { LaidOut } from './layout'
import type { PathEdge } from '../api/path'
import { PathEdges } from './PathEdges'
import { PathNodeCard } from './PathNodeCard'

export function PathCanvas({ layout, selectedId, onSelect, onEnter, isTaken, isBranchTaken, reduced }: {
  layout: LaidOut; selectedId: string | null; reduced: boolean
  onSelect: (id: string) => void; onEnter: (t: { type: 'container' | 'loop'; id: string }) => void
  isTaken: (e: PathEdge) => boolean
  isBranchTaken: (branch: string | null | undefined) => boolean
}) {
  return (
    <div style={{ position: 'relative', width: layout.worldW, height: layout.worldH }}>
      <PathEdges layout={layout} isTaken={isTaken} reduced={reduced} />
      {layout.nodes.map((n) => {
        // Status comes directly from the real API node — no mock overrides.
        // Branch greying: notTaken when a branch key is set and isBranchTaken returns false.
        const notTaken = (!!n.branch && !isBranchTaken(n.branch)) || !!n.never_run
        return (
          <PathNodeCard
            key={n.id}
            node={n}
            selected={selectedId === n.id}
            onSelect={onSelect}
            onEnter={onEnter}
            reduced={reduced}
            notTaken={notTaken}
          />
        )
      })}
    </div>
  )
}
