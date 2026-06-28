// The ONLY data-access seam for the Path view. Calls the real backend API.
// The backend (Tasks 1-10) implements the same contract as the hand-authored path.ts types,
// so no consumer changes are needed — only this file swapped from mock to apiFetch.
import { apiFetch } from './client'
import type { PathTree, NodeResultsPage, RunInputs, PathViewRef, NodeSource } from './path'

export interface NodeResultsOpts { host?: string; status?: string; offset?: number; limit?: number }

export function fetchTree(runId: string, view: PathViewRef, iter = 0, includeNeverRun = false): Promise<PathTree> {
  const params = new URLSearchParams()
  if (view.type === 'container' || view.type === 'loop') params.set('root', view.id)
  if (view.type === 'loop') params.set('iter', String(iter))
  if (includeNeverRun && view.type !== 'loop') params.set('never_run', '1')
  const qs = params.toString()
  return apiFetch<PathTree>(`/runs/${runId}/tree${qs ? `?${qs}` : ''}`)
}

export function fetchNodeSource(runId: string, nodeId: string): Promise<NodeSource> {
  // Never-run ghost ids are `nr:{file}:{line}`; the file contains '/', so fetch via query params
  // (a dedicated endpoint) rather than a path segment that routing would split (OV5).
  if (nodeId.startsWith('nr:')) {
    const body = nodeId.slice(3)
    const i = body.lastIndexOf(':')
    const params = new URLSearchParams({ file: body.slice(0, i), line: body.slice(i + 1) })
    return apiFetch<NodeSource>(`/runs/${runId}/ghost-source?${params.toString()}`)
  }
  return apiFetch<NodeSource>(`/runs/${runId}/nodes/${nodeId}/source`)
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

// Whole-run Markdown summary (status, per-host recap, path-to-failure) for tickets/KB.
// The endpoint returns text/plain; apiFetch falls back to the raw string for non-JSON bodies.
export function fetchRunSummary(runId: string): Promise<string> {
  return apiFetch<string>(`/runs/${runId}/summary`)
}
