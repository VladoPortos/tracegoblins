import { useQuery } from '@tanstack/react-query'
import { apiFetch } from './client'

export interface DirectoryUser { id: string; display_name: string; email: string }

export const userSearchKey = (q: string) => ['users', 'search', q] as const

export function useUserSearch(q: string) {
  const enabled = q.trim().length >= 1
  return useQuery<DirectoryUser[]>({
    queryKey: userSearchKey(q),
    queryFn: () => apiFetch<DirectoryUser[]>(`/users?q=${encodeURIComponent(q)}`),
    enabled,            // q min length 1 (matches the backend 422 guard); skip empties
  })
}
