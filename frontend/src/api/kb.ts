import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'

export interface KbLink { label: string; url: string }
export type KbStatus = 'needs-fix' | 'known-issue' | 'resolved' | 'note'
export const KB_STATUS_VALUES: KbStatus[] = ['needs-fix', 'known-issue', 'resolved', 'note']

export interface KbSignatureOut {
  id: string; team_id: string | null; signature_key: string; title: string
  status: KbStatus; category: string | null; description: string | null
  is_problem: string | null; where_it_lives: string | null; representative_text: string
  links: KbLink[]
  occurrence_count: number; created_at: string; updated_at: string
}
export interface KbSignatureList { items: KbSignatureOut[]; total: number }
export interface KbSuggest { signature_key: string; representative_text: string; category: string | null }
export interface KbDrawerSuggestion {
  signature: KbSignatureOut; exact: boolean; score: number
}
export interface KbSignatureUpdate {
  title?: string | null; status?: KbStatus | null; representative_text?: string | null
  category?: string | null; description?: string | null; is_problem?: string | null
  where_it_lives?: string | null; links?: KbLink[] | null
}
export interface KbPromote {
  run_id: string; task_seq: number; team_id?: string | null; title: string
  status?: KbStatus; description?: string | null; is_problem?: string | null
  where_it_lives?: string | null; links?: KbLink[]
}

export const kbKey = ['kb'] as const
export const kbSignatureKey = (id: string) => ['kb', id] as const
export const taskKbKey = (runId: string, seq: number) => ['runs', runId, 'tasks', seq, 'kb'] as const

export const KB_PAGE_SIZE = 50

export function useKbSignatures(scope: 'team' | 'global' | 'all', status?: string, q?: string) {
  return useInfiniteQuery({
    queryKey: [...kbKey, { scope, status: status ?? null, q: q ?? null }],
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams()
      qs.set('scope', scope)
      if (status) qs.set('status', status)
      if (q) qs.set('q', q)
      qs.set('limit', String(KB_PAGE_SIZE))
      qs.set('offset', String(pageParam))
      return apiFetch<KbSignatureList>(`/kb/signatures?${qs.toString()}`)
    },
    initialPageParam: 0,
    getNextPageParam: (last: KbSignatureList, all: KbSignatureList[]) => {
      const got = all.reduce((n, p) => n + p.items.length, 0)
      return got < last.total ? got : undefined
    },
  })
}

export function useTaskKbSuggestion(runId: string, seq: number, enabled: boolean) {
  return useQuery<KbDrawerSuggestion | null>({
    queryKey: taskKbKey(runId, seq),
    queryFn: async () => (await apiFetch<KbDrawerSuggestion | null>(`/runs/${runId}/tasks/${seq}/kb`)) ?? null,
    enabled: enabled && !!runId,
  })
}

export function useKbSuggest(runId: string, seq: number, enabled: boolean) {
  return useQuery<KbSuggest>({
    queryKey: ['kb', 'suggest', runId, seq],
    queryFn: () => apiFetch<KbSuggest>(`/kb/suggest?run_id=${encodeURIComponent(runId)}&task_seq=${seq}`),
    enabled: enabled && !!runId,
  })
}

export function usePromoteKb() {
  const qc = useQueryClient()
  return useMutation<KbSignatureOut, unknown, KbPromote>({
    mutationFn: (body) => apiFetch<KbSignatureOut>('/kb/promote', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: kbKey })
      void qc.invalidateQueries({ queryKey: taskKbKey(vars.run_id, vars.task_seq) })
    },
  })
}

export function useUpdateKbSignature() {
  const qc = useQueryClient()
  return useMutation<KbSignatureOut, unknown, { id: string; patch: KbSignatureUpdate }>({
    mutationFn: ({ id, patch }) => apiFetch<KbSignatureOut>(`/kb/signatures/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: kbKey })
      void qc.invalidateQueries({ queryKey: kbSignatureKey(vars.id) })
    },
  })
}

export function useDeleteKbSignature() {
  const qc = useQueryClient()
  return useMutation<void, unknown, string>({
    mutationFn: (id) => apiFetch<void>(`/kb/signatures/${id}`, { method: 'DELETE' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: kbKey }) },
  })
}

export function usePromoteKbGlobal() {
  const qc = useQueryClient()
  return useMutation<KbSignatureOut, unknown, string>({
    mutationFn: (id) => apiFetch<KbSignatureOut>(`/kb/signatures/${id}/promote-global`, { method: 'POST' }),
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: kbKey })
      void qc.invalidateQueries({ queryKey: kbSignatureKey(id) })
    },
  })
}
