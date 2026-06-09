import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'

export interface Notification {
  id: string; type: string; run_id: string | null; run_template: string | null
  task_seq: number | null; task_name: string | null
  actor_user_id: string | null; actor_name: string | null
  read_at: string | null; created_at: string
}
export interface NotificationList { items: Notification[] }
export interface UnreadCount { count: number }
export interface MarkRead { ids?: string[] | null; all?: boolean }

export const notificationsKey = ['notifications'] as const
export const unreadCountKey = ['notifications', 'unread_count'] as const

export function useNotifications(opts?: { unreadOnly?: boolean; limit?: number; offset?: number }) {
  const unreadOnly = opts?.unreadOnly ?? false
  const limit = opts?.limit ?? 30
  const offset = opts?.offset ?? 0
  return useQuery<NotificationList>({
    queryKey: [...notificationsKey, { unreadOnly, limit, offset }],
    queryFn: () => apiFetch<NotificationList>(`/notifications?unread_only=${unreadOnly}&limit=${limit}&offset=${offset}`),
  })
}
export function useUnreadCount() {
  return useQuery<UnreadCount>({
    queryKey: unreadCountKey,
    queryFn: () => apiFetch<UnreadCount>('/notifications/unread_count'),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}
export function useMarkRead() {
  const qc = useQueryClient()
  return useMutation<UnreadCount, unknown, MarkRead>({
    mutationFn: (body) => apiFetch<UnreadCount>('/notifications/read', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: notificationsKey })
      void qc.invalidateQueries({ queryKey: unreadCountKey })
    },
  })
}
