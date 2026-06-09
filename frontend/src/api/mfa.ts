import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch, type Me } from './client'
import { meKey } from './queries'

export interface SetupOut { secret: string; otpauth_uri: string; qr_svg: string }
export interface RecoveryOut { recovery_codes: string[] }

export function useMfaSetup() {
  return useMutation<SetupOut, unknown, void>({
    mutationFn: () => apiFetch<SetupOut>('/auth/2fa/setup', { method: 'POST' }),
  })
}
export function useMfaEnable() {
  // NOTE: intentionally no mutation-level onSuccess/invalidation here.
  // invalidateQueries(meKey) must fire AFTER the call-site onSuccess sets
  // recoveryCodes state; otherwise the useMe refetch flips SecuritySettings
  // from <EnrollSection> (which owns recoveryCodes state) to <EnrolledSection>
  // before the codes can be displayed.  TotpEnroll surfaces the codes via its
  // onEnabled callback; SecuritySettings invalidates meKey only in the
  // RecoveryCodesPanel onDone handler, after the user clicks Done.
  return useMutation<RecoveryOut, unknown, { code: string }>({
    mutationFn: (b) => apiFetch<RecoveryOut>('/auth/2fa/enable', { method: 'POST', body: JSON.stringify(b) }),
  })
}
export function useMfaDisable() {
  const qc = useQueryClient()
  return useMutation<void, unknown, { code: string }>({
    mutationFn: (b) => apiFetch<void>('/auth/2fa/disable', { method: 'POST', body: JSON.stringify(b) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: meKey }) },
  })
}
export function useRegenRecovery() {
  return useMutation<RecoveryOut, unknown, { code: string }>({
    mutationFn: (b) => apiFetch<RecoveryOut>('/auth/2fa/recovery-codes/regenerate', { method: 'POST', body: JSON.stringify(b) }),
  })
}
export function useLoginVerify() {
  const qc = useQueryClient()
  return useMutation<Me, unknown, { code: string }>({
    mutationFn: (b) => apiFetch<Me>('/auth/login/verify', { method: 'POST', body: JSON.stringify(b) }),
    onSuccess: (user) => { qc.setQueryData(meKey, user) },
  })
}
export function useResetUser2fa() {
  return useMutation<void, unknown, string>({
    mutationFn: (userId) => apiFetch<void>(`/users/${userId}/reset-2fa`, { method: 'POST' }),
  })
}
