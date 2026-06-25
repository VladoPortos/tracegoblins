// The ONLY data-access seam for the Path view. Calls the real backend API.
// The backend (Tasks 1-10) implements the same contract as the hand-authored path.ts types,
// so no consumer changes are needed — only this file swapped from mock to apiFetch.
import { apiFetch } from './client'
import type { PathTree, NodeResultsPage, RunInputs, PathViewRef } from './path'

export interface NodeResultsOpts { iter?: number; host?: string; status?: string; offset?: number; limit?: number }

export function fetchTree(runId: string, view: PathViewRef, iter = 0): Promise<PathTree> {
  const params = new URLSearchParams()
  if (view.type === 'container' || view.type === 'loop') params.set('root', view.id)
  if (view.type === 'loop') params.set('iter', String(iter))
  const qs = params.toString()
  return apiFetch<PathTree>(`/runs/${runId}/tree${qs ? `?${qs}` : ''}`)
}

export function fetchNodeResults(runId: string, nodeId: string, opts: NodeResultsOpts = {}): Promise<NodeResultsPage> {
  const params = new URLSearchParams()
  if (opts.host) params.set('host', opts.host)
  if (opts.status) params.set('status', opts.status)
  if (opts.offset != null) params.set('offset', String(opts.offset))
  if (opts.limit != null) params.set('limit', String(opts.limit))
  const qs = params.toString()
  return apiFetch<NodeResultsPage>(`/runs/${runId}/nodes/${nodeId}/results${qs ? `?${qs}` : ''}`)
}

export function fetchInputs(runId: string): Promise<RunInputs> {
  return apiFetch<RunInputs>(`/runs/${runId}/inputs`)
}
