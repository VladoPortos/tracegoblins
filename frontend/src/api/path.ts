// The Path Explorer data contract. Hand-authored for the frontend-first slice; the backend
// plan implements byte-identical response shapes so pathSource.ts can swap mock → apiFetch
// with no change to consumers. Mirrors the run_nodes / run_node_results schema (spec §5.2).

export type PathNodeType =
  | 'play' | 'role' | 'block' | 'include' | 'task' | 'loop' | 'when' | 'item' | 'result'
export type PathStatus =
  | 'ok' | 'changed' | 'failed' | 'unreachable' | 'skipped' | 'included' | 'never_run'

/** A box in the flow. Coordinates are NOT included — layout.ts computes them. */
export interface PathNode {
  id: string
  type: PathNodeType
  label: string
  sub: string | null               // "role · 12 tasks" | "loop · 50 items" | module subtitle
  status: PathStatus
  action: string | null            // e.g. "ansible.builtin.apt"
  host_count: number | null
  taken_hosts: string[] | null     // fork branch nodes only: sorted list of hosts that took this branch
  item_count: number | null        // loop size (loop nodes)
  ok_count: number | null          // loop fan-out summary
  fail_count: number | null
  has_failures: boolean
  is_conditional: boolean
  is_handler?: boolean             // fired handler (notified + flushed) — badge it on the card
  condition: string | null         // when expression / false_condition
  branch: string | null            // branch key on when-children, e.g. "redhat" | "windows"
  enter_to: { type: 'container' | 'loop'; id: string } | null  // null = not enterable
  child_count: number | null       // container child count
  duration_s: number | null
  task_path: string | null         // "roles/app/tasks/main.yml:42" (Code tab)
  never_run?: boolean              // ghost node — present in source, never executed
  result_node_id?: string | null  // loop-view synthetic nodes → real loop node_id for /results
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
  never_run_note?: string | null   // set when never-run was toggled but ghosts live one drill-in down
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

export interface ResolvedValue {
  key: string
  expr: string | null
  value: unknown | null
  source: 'module_args' | 'set_fact' | 'debug' | 'task_args' | 'item' | 'when'
  recorded: boolean
  host: string | null
}
export type SourceUnavailable =
  | 'not_linked' | 'not_cloned' | 'revision_missing' | 'no_path' | 'binary' | 'too_large'
export interface NodeSource {
  project_id: string | null
  path: string | null
  ref: string | null
  content: string | null
  focus_line: number | null
  executed_lines: number[]
  skipped_lines: number[]
  never_run_lines: number[]
  resolved: ResolvedValue[]
  hosts: string[]
  revision_mismatch: boolean
  unavailable: SourceUnavailable | null
}

import { useQuery, keepPreviousData } from '@tanstack/react-query'
import * as pathSource from './pathSource'

export const pathTreeKey = (id: string, view: PathViewRef, iter: number) =>
  ['runs', id, 'path', view.type, view.type === 'main' ? '' : view.id, iter] as const
export const nodeResultsKey = (id: string, nodeId: string) => ['runs', id, 'path', 'results', nodeId] as const
export const runInputsKey = (id: string) => ['runs', id, 'inputs'] as const
export const nodeSourceKey = (id: string, nodeId: string) => ['runs', id, 'path', 'source', nodeId] as const

export function useNodeSource(id: string, nodeId: string | null, enabled = true) {
  return useQuery<NodeSource>({
    queryKey: nodeSourceKey(id, nodeId ?? 'none'),
    queryFn: () => pathSource.fetchNodeSource(id, nodeId!),
    enabled: !!id && !!nodeId && enabled,
  })
}

export function useRunTree(id: string, view: PathViewRef, iter = 0, includeNeverRun = false) {
  return useQuery<PathTree>({
    queryKey: [...pathTreeKey(id, view, view.type === 'loop' ? iter : 0), includeNeverRun],
    queryFn: () => pathSource.fetchTree(id, view, iter, includeNeverRun),
    enabled: !!id,
    // keep the previous view's tree on screen while the next loads → no full-screen spinner flash
    // on every view switch / loop step (PATH2)
    placeholderData: keepPreviousData,
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
