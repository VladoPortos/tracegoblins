// frontend/src/path/layout.ts
import dagre from '@dagrejs/dagre'
import type { PathNode, PathEdge } from '../api/path'

export interface PositionedNode extends PathNode { x: number; y: number; w: number; h: number }
export interface LaidOut { nodes: PositionedNode[]; edges: PathEdge[]; worldW: number; worldH: number }

export function nodeSize(n: PathNode): { w: number; h: number } {
  if (n.type === 'role' || n.type === 'block' || n.type === 'include') return { w: 208, h: 80 }
  if (n.type === 'loop') return { w: 216, h: 96 }
  if (n.type === 'when') return { w: 236, h: 96 }
  return { w: 200, h: 64 } // task | item | result
}

export function layoutTree(nodes: PathNode[], edges: PathEdge[]): LaidOut {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 42, ranksep: 90, marginx: 40, marginy: 40 })
  g.setDefaultEdgeLabel(() => ({}))
  const sizes = new Map<string, { w: number; h: number }>()
  for (const n of nodes) { const s = nodeSize(n); sizes.set(n.id, s); g.setNode(n.id, { width: s.w, height: s.h }) }
  for (const e of edges) g.setEdge(e.from, e.to)
  dagre.layout(g)

  let worldW = 0, worldH = 0
  const positioned: PositionedNode[] = nodes.map((n) => {
    const gn = g.node(n.id); const s = sizes.get(n.id)!
    const x = gn.x - s.w / 2, y = gn.y - s.h / 2
    worldW = Math.max(worldW, x + s.w); worldH = Math.max(worldH, y + s.h)
    return { ...n, x, y, w: s.w, h: s.h }
  })
  return { nodes: positioned, edges, worldW: worldW + 40, worldH: worldH + 40 }
}
