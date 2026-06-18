import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiUpload, type RunCard, type RunDetail, type RunListResponse, type TaskFull, type TaskLean } from './client'

export const runsKey = ['runs'] as const
export const runKey = (id: string) => ['runs', id] as const
export const runTasksKey = (id: string) => ['runs', id, 'tasks'] as const
export const taskKey = (id: string, seq: number) => ['runs', id, 'tasks', seq] as const
export const runDiffKey = (id: string) => ['runs', id, 'diff'] as const

// Diff vs last green run — mirror backend runs_schemas.py (DiffEntry/DurationDelta/RunDiffOut).
export interface DiffEntry {
  play_name: string; task_name: string; host: string
  before: string | null   // status in baseline; null = absent in baseline
  after: string | null    // status in current run; null = absent now
  seq: number | null      // current-run seq (drawer-jump target); always set for emitted entries
}
export interface DurationDelta {
  play_name: string; task_name: string; seq: number
  before_s: number; after_s: number; delta_s: number
}
export interface RunDiffOut {
  baseline: RunCard | null
  reason: 'no_template' | 'no_green_run' | null
  newly_failing: DiffEntry[]
  fixed: DiffEntry[]
  still_failing: DiffEntry[]
  added_count: number
  removed_count: number
  hosts_newly_unreachable: string[]
  duration_delta_s: number | null
  slowest_changes: DurationDelta[]
}

export interface RunFilters {
  controller?: string; organization?: number; template?: string; awx_user?: string
  status?: string[]; launch_type?: string; source?: string; launched_after?: string; launched_before?: string; search?: string
}

const PAGE = 100

export function useInfiniteRuns(
  scope: 'mine' | 'shared' | 'team' = 'mine',
  filters: RunFilters = {},
  sort: string = 'when',
  dir: string = 'desc',
) {
  return useInfiniteQuery({
    queryKey: [...runsKey, 'infinite', { scope, filters, sort, dir }],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams()
      qs.set('scope', scope)
      qs.set('limit', String(PAGE))
      qs.set('offset', String(pageParam))
      if (filters.controller) qs.set('controller', filters.controller)
      if (filters.organization != null) qs.set('organization', String(filters.organization))
      if (filters.template) qs.set('template', filters.template)
      if (filters.awx_user) qs.set('awx_user', filters.awx_user)
      if (filters.status && filters.status.length) qs.set('status', filters.status.join(','))
      if (filters.launch_type) qs.set('launch_type', filters.launch_type)
      if (filters.source) qs.set('source', filters.source)
      if (filters.launched_after) qs.set('launched_after', filters.launched_after)
      if (filters.launched_before) qs.set('launched_before', filters.launched_before)
      if (filters.search) qs.set('search', filters.search)
      qs.set('sort', sort)
      qs.set('dir', dir)
      return apiFetch<RunListResponse>(`/runs?${qs.toString()}`)
    },
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((n, p) => n + p.items.length, 0)
      return loaded < lastPage.total ? loaded : undefined
    },
  })
}

export function useRun(id: string) {
  return useQuery<RunDetail>({ queryKey: runKey(id), queryFn: () => apiFetch<RunDetail>(`/runs/${id}`), enabled: !!id })
}
export function useRunTasks(id: string) {
  return useQuery<TaskLean[]>({ queryKey: runTasksKey(id), queryFn: () => apiFetch<TaskLean[]>(`/runs/${id}/tasks`), enabled: !!id })
}
export function useTask(id: string, seq: number | null) {
  return useQuery<TaskFull>({
    queryKey: seq == null ? ['runs', id, 'tasks', 'none'] : taskKey(id, seq),
    queryFn: () => apiFetch<TaskFull>(`/runs/${id}/tasks/${seq}`),
    enabled: !!id && seq != null,
  })
}
export function useRunDiff(id: string, enabled: boolean) {
  return useQuery<RunDiffOut>({
    queryKey: runDiffKey(id),
    queryFn: () => apiFetch<RunDiffOut>(`/runs/${id}/diff`),
    enabled: !!id && enabled,
  })
}
export function useUploadRun() {
  const qc = useQueryClient()
  return useMutation<{ id: string }, unknown, { file?: File; text?: string; template?: string; team_id?: string }>({
    mutationFn: (v) => {
      if (v.file) {
        const form = new FormData()
        form.append('file', v.file)
        if (v.template) form.append('template', v.template)
        if (v.team_id) form.append('team_id', v.team_id)
        return apiUpload<{ id: string }>('/runs', form)
      }
      return apiFetch<{ id: string }>('/runs', {
        method: 'POST',
        body: JSON.stringify({ text: v.text, template: v.template, team_id: v.team_id }),
      })
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: runsKey }) },
  })
}
export function useDeleteRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/runs/${id}`, { method: 'DELETE' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: runsKey }) },
  })
}
