// The ONLY data-access seam for the Path view. Mock now; the backend plan rewrites the three
// functions to `apiFetch<...>(...)` against /runs/{id}/tree · /nodes/{id}/results · /inputs.
import type { PathTree, NodeResultsPage, RunInputs, PathViewRef } from './path'
import { treeFor, loopResults, MOCK_INPUTS } from './pathFixture'

const MOCK_LATENCY_MS = 120  // makes loading states visible during dev

function delay<T>(value: T): Promise<T> {
  return new Promise((res) => setTimeout(() => res(value), MOCK_LATENCY_MS))
}

export interface NodeResultsOpts { iter?: number; host?: string; status?: string; offset?: number; limit?: number }

export function fetchTree(runId: string, view: PathViewRef, iter = 0): Promise<PathTree> {
  return delay(treeFor(runId, view, iter))
}
export function fetchNodeResults(_runId: string, _nodeId: string, opts: NodeResultsOpts = {}): Promise<NodeResultsPage> {
  const all = loopResults()
  const offset = opts.offset ?? 0
  const limit = opts.limit ?? all.length
  return delay({ results: all.slice(offset, offset + limit), total: all.length })
}
export function fetchInputs(_runId: string): Promise<RunInputs> {
  return delay(MOCK_INPUTS)
}
