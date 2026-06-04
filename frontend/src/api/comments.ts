import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'

export interface Comment {
  id: string; run_id: string; task_seq: number | null; annotation_id: string | null
  parent_id: string | null; author_user_id: string; author_name: string
  body: string | null; mentions: string[]; mention_names: string[]
  created_at: string; edited_at: string | null; deleted_at: string | null
}
export interface CommentCreate {
  body: string; mentions?: string[]; parent_id?: string | null; annotation_id?: string | null
}
export interface CommentUpdate { body: string; mentions?: string[] }

export interface MentionableUser {
  id: string; display_name: string; email: string
  initials: string | null; avatar_color: string | null
}

export const commentsKey = (runId: string, seq: number) => ['runs', runId, 'tasks', seq, 'comments'] as const

export function useTaskComments(runId: string, seq: number | null) {
  return useQuery<Comment[]>({
    queryKey: seq == null ? ['runs', runId, 'tasks', 'none', 'comments'] : commentsKey(runId, seq),
    queryFn: () => apiFetch<Comment[]>(`/runs/${runId}/tasks/${seq}/comments`),
    enabled: !!runId && seq != null,
  })
}
export function useCreateComment(runId: string, seq: number) {
  const qc = useQueryClient()
  return useMutation<Comment, unknown, CommentCreate>({
    mutationFn: (body) => apiFetch<Comment>(`/runs/${runId}/tasks/${seq}/comments`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: commentsKey(runId, seq) }) },
  })
}
export function useUpdateComment(runId: string, seq: number) {
  const qc = useQueryClient()
  return useMutation<Comment, unknown, { cid: string; patch: CommentUpdate }>({
    mutationFn: ({ cid, patch }) => apiFetch<Comment>(`/comments/${cid}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: commentsKey(runId, seq) }) },
  })
}
export function useDeleteComment(runId: string, seq: number) {
  const qc = useQueryClient()
  return useMutation<Comment, unknown, string>({
    mutationFn: (cid) => apiFetch<Comment>(`/comments/${cid}`, { method: 'DELETE' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: commentsKey(runId, seq) }) },
  })
}
export function useMentionable(runId: string, q: string) {
  return useQuery<MentionableUser[]>({
    queryKey: ['runs', runId, 'mentionable', q],
    queryFn: () => apiFetch<MentionableUser[]>(`/runs/${runId}/mentionable?q=${encodeURIComponent(q)}`),
    enabled: !!runId,
  })
}
