import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  apiFetch, ApiError,
  type InviteCreated, type Me, type SetupStatus, type TeamOut, type UserOut,
} from './client'

export const meKey = ['auth', 'me'] as const
export const setupKey = ['setup', 'status'] as const
export const usersKey = ['admin', 'users'] as const
export const teamsKey = ['admin', 'teams'] as const
export const inviteKey = (token: string) => ['invite', token] as const

export function useMe() {
  return useQuery<Me | null>({
    queryKey: meKey,
    queryFn: async () => {
      try { return await apiFetch<Me>('/auth/me') }
      catch (e) { if (e instanceof ApiError && e.status === 401) return null; throw e }
    },
    staleTime: 60_000,
  })
}

export function useSetupStatus() {
  return useQuery<SetupStatus>({
    queryKey: setupKey,
    queryFn: () => apiFetch<SetupStatus>('/setup/status'),
    staleTime: Infinity,
  })
}

export type LoginResult = Me | { mfa_required: true }

export function useLogin() {
  const qc = useQueryClient()
  return useMutation<LoginResult, unknown, { email: string; password: string; remember: boolean }>({
    mutationFn: (body) => apiFetch<LoginResult>('/auth/login', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (res) => { if (!('mfa_required' in res)) qc.setQueryData(meKey, res) },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch<void>('/auth/logout', { method: 'POST' }),
    onSettled: () => { qc.setQueryData(meKey, null); qc.clear() },
  })
}

// Revokes ALL of the user's sessions server-side (this device included).
export function useLogoutEverywhere() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch<void>('/auth/logout-everywhere', { method: 'POST' }),
    onSettled: () => { qc.setQueryData(meKey, null); qc.clear() },
  })
}

export function useRunSetup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; display_name: string; password: string }) =>
      apiFetch<Me>('/setup', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (user) => {
      qc.setQueryData(meKey, user)
      void qc.invalidateQueries({ queryKey: setupKey })
    },
  })
}

export function useChangePassword() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      apiFetch<void>('/auth/change-password', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: meKey }) },
  })
}

export function useAcceptInvite(token: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { display_name: string; password: string }) =>
      apiFetch<Me>(`/invites/${token}/accept`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (user) => { qc.setQueryData(meKey, user) },
  })
}

export function useAdminUsers() {
  return useQuery<UserOut[]>({ queryKey: usersKey, queryFn: () => apiFetch<UserOut[]>('/admin/users') })
}
export function useAdminTeams() {
  return useQuery<TeamOut[]>({ queryKey: teamsKey, queryFn: () => apiFetch<TeamOut[]>('/admin/teams') })
}

export function useCreateInvite() {
  return useMutation({
    mutationFn: (body: { email: string; role?: string; team_ids?: string[] }) =>
      apiFetch<InviteCreated>('/admin/invites', { method: 'POST', body: JSON.stringify(body) }),
  })
}
export function useChangeRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; role: string }) =>
      apiFetch<UserOut>(`/admin/users/${v.id}/role`, { method: 'PATCH', body: JSON.stringify({ role: v.role }) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: usersKey }) },
  })
}
export function useSetActive() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; active: boolean }) =>
      apiFetch<UserOut>(`/admin/users/${v.id}/${v.active ? 'activate' : 'deactivate'}`, { method: 'POST' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: usersKey }) },
  })
}
export function useCreateTeam() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => apiFetch<TeamOut>('/admin/teams', { method: 'POST', body: JSON.stringify({ name }) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: teamsKey }) },
  })
}
export function useRenameTeam() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; name: string }) =>
      apiFetch<TeamOut>(`/admin/teams/${v.id}`, { method: 'PATCH', body: JSON.stringify({ name: v.name }) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: teamsKey }) },
  })
}
export function useDeleteTeam() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/admin/teams/${id}`, { method: 'DELETE' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: teamsKey }) },
  })
}
export function useAddTeamMember() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { teamId: string; userId: string }) =>
      apiFetch<void>(`/admin/teams/${v.teamId}/members`, { method: 'POST', body: JSON.stringify({ user_id: v.userId }) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: usersKey }); void qc.invalidateQueries({ queryKey: teamsKey }) },
  })
}
export function useRemoveTeamMember() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { teamId: string; userId: string }) =>
      apiFetch<void>(`/admin/teams/${v.teamId}/members/${v.userId}`, { method: 'DELETE' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: usersKey }); void qc.invalidateQueries({ queryKey: teamsKey }) },
  })
}
