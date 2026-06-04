import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'

export interface ShareTargetUser { id: string; display_name: string; email: string }
export interface ShareTargetTeam { id: string; name: string; slug: string }
export interface Share {
  id: string; run_id: string; permission: string; shared_by_user_id: string
  user: ShareTargetUser | null; team: ShareTargetTeam | null; created_at: string
}
export interface ShareCreate { user_id?: string | null; team_id?: string | null }

export const sharesKey = (runId: string) => ['runs', runId, 'shares'] as const

export function useRunShares(runId: string) {
  return useQuery<Share[]>({
    queryKey: sharesKey(runId),
    queryFn: () => apiFetch<Share[]>(`/runs/${runId}/shares`),
    enabled: !!runId,
  })
}
export function useCreateShare(runId: string) {
  const qc = useQueryClient()
  return useMutation<Share, unknown, ShareCreate>({
    mutationFn: (body) => apiFetch<Share>(`/runs/${runId}/shares`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: sharesKey(runId) }) },
  })
}
export function useDeleteShare(runId: string) {
  const qc = useQueryClient()
  return useMutation<void, unknown, string>({
    mutationFn: (shareId) => apiFetch<void>(`/runs/${runId}/shares/${shareId}`, { method: 'DELETE' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: sharesKey(runId) }) },
  })
}
