import type { LaidOut } from './layout'
import type { PathEdge, PathStatus } from '../api/path'
import { PathEdges } from './PathEdges'
import { PathNodeCard } from './PathNodeCard'

export function PathCanvas({ layout, selectedId, onSelect, onEnter, isTaken, isBranchTaken, hostScope, reduced }: {
  layout: LaidOut; selectedId: string | null; reduced: boolean
  onSelect: (id: string) => void; onEnter: (t: { type: 'container' | 'loop'; id: string }) => void
  isTaken: (e: PathEdge) => boolean
  isBranchTaken: (branch: string | null | undefined) => boolean
  hostScope: string
}) {
  return (
    <div style={{ position: 'relative', width: layout.worldW, height: layout.worldH }}>
      <PathEdges layout={layout} isTaken={isTaken} reduced={reduced} />
      {layout.nodes.map((n) => {
        // Per-host status override: restart node shows failed only for web-13
        const statusOverride: PathStatus | undefined = (n.id === 'restart' && hostScope !== 'all')
          ? (hostScope === 'web-13' ? 'failed' : 'ok')
          : undefined
        const nodeWithStatus = statusOverride ? { ...n, status: statusOverride } : n
        const notTaken = !!n.branch && !isBranchTaken(n.branch)
        return (
          <PathNodeCard
            key={n.id}
            node={nodeWithStatus}
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
