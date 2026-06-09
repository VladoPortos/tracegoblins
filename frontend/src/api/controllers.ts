import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'
import { runsKey } from './runs'

export interface TeamAssignment { team_id: string; awx_organization_id: number | null }
export interface ControllerTeamOut { team_id: string; team_name: string | null; awx_organization_id: number | null }
export interface Controller {
  id: string; name: string; base_url: string; verify_ssl: boolean
  sync_mode: 'manual' | 'auto'; sync_interval_minutes: number | null
  status: 'unconfigured' | 'connected' | 'error'
  last_sync_status: 'never' | 'running' | 'ok' | 'error'
  last_sync_at: string | null; last_sync_error: string | null
  sync_total: number | null; sync_done: number | null; sync_current_job: string | null
  token_masked: string; team_assignments: ControllerTeamOut[]; created_at: string
}
export interface ControllerCreate {
  name: string; base_url: string; token: string; verify_ssl: boolean
  sync_mode: 'manual' | 'auto'; sync_interval_minutes?: number | null
  team_assignments: TeamAssignment[]
}
export interface ControllerUpdate {
  name?: string; base_url?: string; token?: string; verify_ssl?: boolean
  sync_mode?: 'manual' | 'auto'; sync_interval_minutes?: number | null
  team_assignments?: TeamAssignment[]
}
export interface TestConnectionResult { ok: boolean; version: string | null; identity: string | null; error: string | null }

export const controllersKey = ['controllers'] as const

export function useControllers(options?: { enabled?: boolean }) {
  return useQuery<Controller[]>({
    queryKey: controllersKey,
    queryFn: () => apiFetch<Controller[]>('/controllers'),
    // Skippable: callers that only need controllers in some states (e.g. RunsList only
    // in the team scope) pass { enabled: false } to avoid a wasted request + the 1.5s poll.
    enabled: options?.enabled ?? true,
    // "Sync now" returns 202 and runs in the background; poll while any controller is
    // mid-sync so the Last-sync chip flips from "running" to ok/error on its own.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((c) => c.last_sync_status === 'running') ? 1500 : false,
  })
}
export function useCreateController() {
  const qc = useQueryClient()
  return useMutation<Controller, unknown, ControllerCreate>({
    mutationFn: (body) => apiFetch<Controller>('/controllers', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: controllersKey }) },
  })
}
export function useUpdateController(id: string) {
  const qc = useQueryClient()
  return useMutation<Controller, unknown, ControllerUpdate>({
    mutationFn: (body) => apiFetch<Controller>(`/controllers/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: controllersKey }) },
  })
}
export function useDeleteController() {
  const qc = useQueryClient()
  return useMutation<void, unknown, string>({
    mutationFn: (id) => apiFetch<void>(`/controllers/${id}`, { method: 'DELETE' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: controllersKey }) },
  })
}
export function useTestConnection(id: string) {
  return useMutation<TestConnectionResult, unknown, { base_url?: string; token?: string; verify_ssl?: boolean } | void>({
    mutationFn: (body) =>
      apiFetch<TestConnectionResult>(`/controllers/${id}/test`, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  })
}
// Ad-hoc test BEFORE the controller is saved (no id) — used by the add modal.
export function useTestConnectionAdhoc() {
  return useMutation<TestConnectionResult, unknown, { base_url: string; token: string; verify_ssl: boolean }>({
    mutationFn: (body) =>
      apiFetch<TestConnectionResult>(`/controllers/test`, { method: 'POST', body: JSON.stringify(body) }),
  })
}
export function useSyncController() {
  const qc = useQueryClient()
  return useMutation<{ status: string }, unknown, string>({
    mutationFn: (id) => apiFetch<{ status: string }>(`/controllers/${id}/sync`, { method: 'POST' }),
    onSuccess: (_data, id) => {
      // The 202 fires before the background task flips status to "running", so mark it
      // optimistically. That both shows the spinner immediately AND arms the
      // refetchInterval poll in useControllers, which converges to ok/error.
      qc.setQueryData<Controller[]>(controllersKey, (prev) =>
        prev?.map((c) => (c.id === id ? { ...c, last_sync_status: 'running' } : c)),
      )
      void qc.invalidateQueries({ queryKey: runsKey })
    },
  })
}
