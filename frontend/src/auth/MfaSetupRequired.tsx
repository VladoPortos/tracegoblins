import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { AuthLayout } from './AuthLayout'
import { TotpEnroll } from '../components/auth/TotpEnroll'
import { RecoveryCodesPanel } from '../components/auth/RecoveryCodesPanel'
import { meKey } from '../api/queries'
import type { Me } from '../api/client'

export function MfaSetupRequired() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)

  // 2FA is now enabled. Clear the stale mfa_setup_required flag (the server now reports it
  // false) BEFORE navigating, or ProtectedRoute reads the cached `true` and bounces us right
  // back to /security/setup — an infinite enrol loop. Optimistic patch + refetch.
  function continueToApp() {
    qc.setQueryData<Me | null>(meKey, (m) =>
      m ? { ...m, totp_enabled: true, mfa_setup_required: false } : m)
    void qc.invalidateQueries({ queryKey: meKey })
    nav('/', { replace: true })
  }

  // Phase 3 — show recovery codes once, then let user continue
  if (recoveryCodes) {
    return (
      <AuthLayout
        eyebrow="Two-factor authentication"
        title="Save your recovery codes"
        sub="Store these codes safely — they are shown only once. Use one to sign in if you lose your authenticator app."
      >
        <RecoveryCodesPanel
          codes={recoveryCodes}
          gap={16}
          warning="Each code can be used once."
          action={
            <button className="btn btn-primary" onClick={continueToApp}>
              Continue to app
            </button>
          }
        />
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      eyebrow="Admin security requirement"
      title="Two-factor authentication required"
      sub="Your admin account must enable 2FA before continuing."
    >
      <TotpEnroll
        intro={
          <p className="muted" style={{ fontSize: 13 }}>
            You will need an authenticator app (e.g. Google Authenticator, Authy, 1Password)
            to scan the QR code below.
          </p>
        }
        startLabel="Set up authenticator app"
        enableLabel="Enable & continue"
        onEnabled={setRecoveryCodes}
      />
    </AuthLayout>
  )
}
