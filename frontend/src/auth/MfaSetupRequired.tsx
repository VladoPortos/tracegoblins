import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { AuthLayout } from './AuthLayout'
import { Field } from '../components/atoms/Field'
import { Glyph } from '../components/atoms/Glyph'
import { useMfaSetup, useMfaEnable } from '../api/mfa'
import { meKey } from '../api/queries'
import { errorMessage } from '../api/client'
import type { Me } from '../api/client'

export function MfaSetupRequired() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const setup = useMfaSetup()
  const enable = useMfaEnable()
  const [code, setCode] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)
  const [copied, setCopied] = useState(false)

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
    function copyAll() {
      void navigator.clipboard.writeText(recoveryCodes!.join('\n')).then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      })
    }
    return (
      <AuthLayout
        eyebrow="Two-factor authentication"
        title="Save your recovery codes"
        sub="Store these codes safely — they are shown only once. Use one to sign in if you lose your authenticator app."
      >
        <div className="col" style={{ gap: 16 }}>
          <div className="row gap2" style={{ alignItems: 'center' }}>
            <Glyph name="alert" size={18} style={{ color: 'var(--warn)' }} />
            <span style={{ fontWeight: 600 }}>Each code can be used once.</span>
          </div>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 24px',
            fontFamily: 'var(--font-mono)', fontSize: 14,
            background: 'var(--surface-2)', borderRadius: 8, padding: '14px 18px',
          }}>
            {recoveryCodes.map((c) => (
              <span key={c} style={{ userSelect: 'all', letterSpacing: '0.05em' }}>{c}</span>
            ))}
          </div>
          <div className="row gap3">
            <button className="btn btn-secondary" onClick={copyAll}>
              <Glyph name="copy" size={15} />
              {copied ? 'Copied!' : 'Copy all'}
            </button>
            <button
              className="btn btn-primary"
              onClick={continueToApp}
            >
              Continue to app
            </button>
          </div>
        </div>
      </AuthLayout>
    )
  }

  function handleEnable() {
    enable.mutate({ code }, {
      onSuccess: (data) => {
        setRecoveryCodes(data.recovery_codes)
        setCode('')
        setup.reset()
      },
    })
  }

  return (
    <AuthLayout
      eyebrow="Admin security requirement"
      title="Two-factor authentication required"
      sub="Your admin account must enable 2FA before continuing."
    >
      <div className="col" style={{ gap: 18 }}>
        {/* Phase 1 — trigger setup */}
        {!setup.data && (
          <div className="col" style={{ gap: 8 }}>
            <p className="muted" style={{ fontSize: 13 }}>
              You will need an authenticator app (e.g. Google Authenticator, Authy, 1Password)
              to scan the QR code below.
            </p>
            <button
              className="btn btn-primary"
              onClick={() => setup.mutate()}
              disabled={setup.isPending}
            >
              <Glyph name="shield" size={15} />
              {setup.isPending ? 'Generating…' : 'Set up authenticator app'}
            </button>
            {setup.isError && (
              <p style={{ color: 'var(--unreachable)', fontSize: 13 }}>
                {errorMessage(setup.error)}
              </p>
            )}
          </div>
        )}

        {/* Phase 2 — QR + code entry */}
        {setup.data && (
          <div className="col" style={{ gap: 16 }}>
            <span style={{ fontWeight: 600 }}>1. Scan this QR code in your authenticator app</span>
            <img
              alt="Scan this QR code in your authenticator app"
              src={`data:image/svg+xml;utf8,${encodeURIComponent(setup.data.qr_svg)}`}
              style={{ width: 200, height: 200, background: '#fff', borderRadius: 8, padding: 8 }}
            />

            <div className="col" style={{ gap: 4 }}>
              <span style={{ fontSize: 13, color: 'var(--text-2)' }}>
                Or enter this secret key manually:
              </span>
              <span
                data-testid="totp-secret"
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 14,
                  userSelect: 'all',
                  background: 'var(--surface-2)',
                  borderRadius: 6,
                  padding: '6px 10px',
                  display: 'inline-block',
                  letterSpacing: '0.1em',
                }}
              >
                {setup.data.secret}
              </span>
            </div>

            <div className="hr" />
            <span style={{ fontWeight: 600 }}>2. Enter the 6-digit code from your app</span>
            <div className="row gap3" style={{ alignItems: 'flex-end' }}>
              <div style={{ width: 160 }}>
                <Field
                  label="Verification code"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="000000"
                  maxLength={6}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                />
              </div>
              <button
                className="btn btn-primary"
                onClick={handleEnable}
                disabled={enable.isPending || code.length < 6}
                style={{ marginBottom: 1 }}
              >
                {enable.isPending ? 'Verifying…' : 'Enable & continue'}
              </button>
            </div>
            {enable.isError && (
              <p style={{ color: 'var(--unreachable)', fontSize: 13 }}>
                {errorMessage(enable.error)}
              </p>
            )}
          </div>
        )}
      </div>
    </AuthLayout>
  )
}
