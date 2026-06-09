import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { SettingsLayout } from './SettingsLayout'
import { Field } from '../components/atoms/Field'
import { Glyph } from '../components/atoms/Glyph'
import { useMe, meKey, useLogoutEverywhere } from '../api/queries'
import { useMfaDisable, useRegenRecovery } from '../api/mfa'
import { TotpEnroll } from '../components/auth/TotpEnroll'
import { RecoveryCodesPanel } from '../components/auth/RecoveryCodesPanel'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { errorMessage } from '../api/client'

// ── Recovery codes display (shown once after enable or regen) ─────────────────
function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  return (
    <RecoveryCodesPanel
      codes={codes}
      warning="Save these recovery codes — they are shown only once."
      note={
        <p className="muted" style={{ fontSize: 13 }}>
          Each code can be used once to sign in if you lose access to your authenticator app.
          Store them somewhere safe (password manager, printed copy, etc.).
        </p>
      }
      action={<button className="btn btn-primary" onClick={onDone}>Done</button>}
    />
  )
}

// ── Enrolment flow (not yet enrolled) ────────────────────────────────────────
function EnrollSection() {
  const qc = useQueryClient()
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)

  if (recoveryCodes) {
    return (
      <RecoveryCodes
        codes={recoveryCodes}
        onDone={() => {
          setRecoveryCodes(null)
          // Invalidate only after the user has seen and dismissed the codes,
          // so useMe re-fetch doesn't destroy the recoveryCodes state early.
          void qc.invalidateQueries({ queryKey: meKey })
        }}
      />
    )
  }

  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="col" style={{ gap: 6 }}>
        <span className="h2">Two-factor authentication</span>
        <p className="muted" style={{ fontSize: 13 }}>
          Add an extra layer of security to your account. You will need an authenticator app
          (e.g. Google Authenticator, Authy, 1Password) to scan the QR code.
        </p>
      </div>

      {/* NOTE: meKey invalidation is deferred to the onDone callback above
          so the RecoveryCodes panel stays mounted until the user clicks Done. */}
      <TotpEnroll
        startLabel="Enable two-factor authentication"
        enableLabel="Enable"
        dividerBeforeQr
        onEnabled={setRecoveryCodes}
      />
    </div>
  )
}

// ── Enrolled flow ─────────────────────────────────────────────────────────────
function EnrolledSection() {
  const disable = useMfaDisable()
  const regen = useRegenRecovery()

  const [disableCode, setDisableCode] = useState('')
  const [regenCode, setRegenCode] = useState('')
  const [showDisable, setShowDisable] = useState(false)
  const [showRegen, setShowRegen] = useState(false)
  const [newCodes, setNewCodes] = useState<string[] | null>(null)

  if (newCodes) {
    return <RecoveryCodes codes={newCodes} onDone={() => { setNewCodes(null); setShowRegen(false); setRegenCode('') }} />
  }

  function handleDisable() {
    disable.mutate({ code: disableCode }, {
      onSuccess: () => { setDisableCode(''); setShowDisable(false) },
    })
  }

  function handleRegen() {
    regen.mutate({ code: regenCode }, {
      onSuccess: (data) => { setNewCodes(data.recovery_codes) },
    })
  }

  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="col" style={{ gap: 6 }}>
        <span className="h2">Two-factor authentication</span>
        <div className="row gap2" style={{ alignItems: 'center' }}>
          <Glyph name="check" size={16} style={{ color: 'var(--ok)' }} />
          <span style={{ fontWeight: 600, color: 'var(--ok)' }}>2FA is enabled on your account.</span>
        </div>
        <p className="muted" style={{ fontSize: 13 }}>
          Your account is protected with an authenticator app.
        </p>
      </div>

      <div className="hr" />

      {/* Regenerate recovery codes */}
      {!showRegen ? (
        <div className="col" style={{ gap: 6 }}>
          <span style={{ fontWeight: 600 }}>Recovery codes</span>
          <p className="muted" style={{ fontSize: 13 }}>
            Lost your recovery codes? Generate a new set — your old codes will be invalidated.
          </p>
          <div>
            <button className="btn btn-secondary" onClick={() => setShowRegen(true)}>
              <Glyph name="copy" size={15} />
              Regenerate recovery codes
            </button>
          </div>
        </div>
      ) : (
        <div className="col" style={{ gap: 10 }}>
          <span style={{ fontWeight: 600 }}>Confirm to regenerate recovery codes</span>
          <p className="muted" style={{ fontSize: 13 }}>
            Enter your current authenticator code to generate a new set of recovery codes.
            Your existing codes will no longer work.
          </p>
          <div className="row gap3" style={{ alignItems: 'flex-end' }}>
            <div style={{ width: 160 }}>
              <Field
                label="Authenticator code"
                value={regenCode}
                onChange={(e) => setRegenCode(e.target.value)}
                placeholder="000000"
                maxLength={6}
                inputMode="numeric"
                autoComplete="one-time-code"
              />
            </div>
            <button
              className="btn btn-primary"
              onClick={handleRegen}
              disabled={regen.isPending || regenCode.length < 6}
              style={{ marginBottom: 1 }}
            >
              {regen.isPending ? 'Regenerating…' : 'Regenerate'}
            </button>
            <button className="btn btn-ghost" onClick={() => { setShowRegen(false); setRegenCode('') }} style={{ marginBottom: 1 }}>
              Cancel
            </button>
          </div>
          {regen.isError && (
            <p style={{ color: 'var(--unreachable)', fontSize: 13 }}>
              {errorMessage(regen.error)}
            </p>
          )}
        </div>
      )}

      <div className="hr" />

      {/* Disable 2FA */}
      {!showDisable ? (
        <div className="col" style={{ gap: 6 }}>
          <span style={{ fontWeight: 600 }}>Disable two-factor authentication</span>
          <p className="muted" style={{ fontSize: 13 }}>
            Removing 2FA will make your account less secure.
          </p>
          <div>
            <button className="btn btn-danger" onClick={() => setShowDisable(true)}>
              Disable 2FA
            </button>
          </div>
        </div>
      ) : (
        <div className="col" style={{ gap: 10 }}>
          <span style={{ fontWeight: 600 }}>Confirm to disable 2FA</span>
          <p className="muted" style={{ fontSize: 13 }}>
            Enter your current authenticator code or a recovery code to disable 2FA.
          </p>
          <div className="row gap3" style={{ alignItems: 'flex-end' }}>
            <div style={{ width: 200 }}>
              <Field
                label="Authenticator or recovery code"
                value={disableCode}
                onChange={(e) => setDisableCode(e.target.value)}
                placeholder="000000 or recovery code"
                autoComplete="one-time-code"
              />
            </div>
            <button
              className="btn btn-danger"
              onClick={handleDisable}
              disabled={disable.isPending || !disableCode.trim()}
              style={{ marginBottom: 1 }}
            >
              {disable.isPending ? 'Disabling…' : 'Disable'}
            </button>
            <button className="btn btn-ghost" onClick={() => { setShowDisable(false); setDisableCode('') }} style={{ marginBottom: 1 }}>
              Cancel
            </button>
          </div>
          {disable.isError && (
            <p style={{ color: 'var(--unreachable)', fontSize: 13 }}>
              {errorMessage(disable.error)}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Sign out everywhere ───────────────────────────────────────────────────────
function SignOutEverywhere() {
  const nav = useNavigate()
  const logoutEverywhere = useLogoutEverywhere()
  return (
    <div className="col" style={{ gap: 6 }}>
      <span style={{ fontWeight: 600 }}>Sign out everywhere</span>
      <p className="muted" style={{ fontSize: 13 }}>
        End every active session for your account on all devices, including this one.
      </p>
      <div>
        <button
          className="btn btn-danger"
          disabled={logoutEverywhere.isPending}
          onClick={() => {
            if (window.confirm('Sign out on all devices?')) {
              logoutEverywhere.mutate(undefined, { onSettled: () => nav('/login') })
            }
          }}
        >
          Sign out everywhere
        </button>
      </div>
    </div>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────
export function SecuritySettings() {
  const me = useMe()
  if (me.isPending || !me.data) return <FullScreenSpinner />
  return (
    <SettingsLayout>
      <div className="col" style={{ gap: 18 }}>
        {me.data.totp_enabled ? <EnrolledSection /> : <EnrollSection />}
        <div className="hr" />
        <SignOutEverywhere />
      </div>
    </SettingsLayout>
  )
}
