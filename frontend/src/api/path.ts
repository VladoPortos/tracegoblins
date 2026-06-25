// The Path Explorer data contract. Hand-authored for the frontend-first slice; the backend
// plan implements byte-identical response shapes so pathSource.ts can swap mock → apiFetch
// with no change to consumers. Mirrors the run_nodes / run_node_results schema (spec §5.2).

export type PathNodeType =
  | 'play' | 'role' | 'block' | 'include' | 'task' | 'loop' | 'when' | 'item' | 'result'
export type PathStatus =
  | 'ok' | 'changed' | 'failed' | 'unreachable' | 'skipped' | 'included'

/** A box in the flow. Coordinates are NOT included — layout.ts computes them. */
export interface PathNode {
  id: string
  type: PathNodeType
  label: string
  sub: string | null               // "role · 12 tasks" | "loop · 50 items" | module subtitle
  status: PathStatus
  action: string | null            // e.g. "ansible.builtin.apt"
  host_count: number | null
  item_count: number | null        // loop size (loop nodes)
  ok_count: number | null          // loop fan-out summary
  fail_count: number | null
  has_failures: boolean
  is_conditional: boolean
  condition: string | null         // when expression / false_condition
  branch: string | null            // branch key on when-children, e.g. "redhat" | "windows"
  enter_to: { type: 'container' | 'loop'; id: string } | null  // null = not enterable
  child_count: number | null       // container child count
  duration_s: number | null
  task_path: string | null         // "roles/app/tasks/main.yml:42" (Code tab)
}

export interface PathEdge { from: string; to: string; branch: string | null }

export type PathViewRef =
  | { type: 'main' }
  | { type: 'container'; id: string }
  | { type: 'loop'; id: string }

export interface PathTree {
  run_id: string
  view: PathViewRef
  nodes: PathNode[]
  edges: PathEdge[]
}

/** One fan-out leaf (host × loop-item) — powers the loop stepper and per-host detail. */
export interface NodeResult {
  host: string
  item_index: number | null
  item_value: unknown | null
  status: PathStatus
  changed: boolean
  output: string | null
  skip_reason: string | null
  duration_s: number | null
}
export interface NodeResultsPage { results: NodeResult[]; total: number }

export interface RunInputs {
  extra_vars: Record<string, unknown>
  survey: Record<string, unknown> | null
  limit: string | null
  scm_revision: string | null
  project_id: number | null
  project_name: string | null
}

import { useQuery } from '@tanstack/react-query'
import * as pathSource from './pathSource'

export const pathTreeKey = (id: string, view: PathViewRef, iter: number) =>
  ['runs', id, 'path', view.type, view.type === 'main' ? '' : view.id, iter] as const
export const nodeResultsKey = (id: string, nodeId: string) => ['runs', id, 'path', 'results', nodeId] as const
export const runInputsKey = (id: string) => ['runs', id, 'inputs'] as const

export function useRunTree(id: string, view: PathViewRef, iter = 0) {
  return useQuery<PathTree>({
    queryKey: pathTreeKey(id, view, view.type === 'loop' ? iter : 0),
    queryFn: () => pathSource.fetchTree(id, view, iter),
    enabled: !!id,
  })
}
export function useNodeResults(id: string, nodeId: string | null, opts: pathSource.NodeResultsOpts = {}, enabled = true) {
  return useQuery<NodeResultsPage>({
    queryKey: [...nodeResultsKey(id, nodeId ?? 'none'), opts],
    queryFn: () => pathSource.fetchNodeResults(id, nodeId!, opts),
    enabled: !!id && !!nodeId && enabled,
  })
}
export function useRunInputs(id: string) {
  return useQuery<RunInputs>({ queryKey: runInputsKey(id), queryFn: () => pathSource.fetchInputs(id), enabled: !!id })
}
