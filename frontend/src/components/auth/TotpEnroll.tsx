import { useState, type CSSProperties, type ReactNode } from 'react'
import { Field } from '../atoms/Field'
import { Glyph } from '../atoms/Glyph'
import { useMfaSetup, useMfaEnable } from '../../api/mfa'
import { errorMessage } from '../../api/client'

// Shared TOTP enrolment flow: start-setup mutation → QR + manual secret →
// 6-digit code field → enable mutation. Copy strings and surrounding layout
// differ per page and arrive as props; the recovery codes produced on success
// go back to the caller via onEnabled (the caller owns what happens next —
// see api/mfa.ts for why meKey invalidation is deferred to the caller).
export function TotpEnroll({ intro, startLabel, enableLabel, dividerBeforeQr = false, onEnabled }: {
  intro?: ReactNode
  startLabel: string
  enableLabel: string
  dividerBeforeQr?: boolean
  onEnabled: (recoveryCodes: string[]) => void
}) {
  const setup = useMfaSetup()
  const enable = useMfaEnable()
  const [code, setCode] = useState('')

  function handleEnable() {
    enable.mutate({ code }, {
      onSuccess: (data) => {
        setCode('')
        setup.reset()
        onEnabled(data.recovery_codes)
      },
    })
  }

  const startButton = (
    <button
      className="btn btn-primary"
      onClick={() => setup.mutate()}
      disabled={setup.isPending}
    >
      <Glyph name="shield" size={15} />
      {setup.isPending ? 'Generating…' : startLabel}
    </button>
  )
  const startError = (style?: CSSProperties) => setup.isError && (
    <p style={{ color: 'var(--unreachable)', fontSize: 13, ...style }}>
      {errorMessage(setup.error)}
    </p>
  )

  return (
    <div className="col" style={{ gap: 18 }}>
      {/* Phase 1 — trigger setup */}
      {!setup.data && (intro ? (
        <div className="col" style={{ gap: 8 }}>
          {intro}
          {startButton}
          {startError()}
        </div>
      ) : (
        <div>
          {startButton}
          {startError({ marginTop: 8 })}
        </div>
      ))}

      {/* Phase 2 — QR + code entry */}
      {setup.data && (
        <div className="col" style={{ gap: 16 }}>
          {dividerBeforeQr && <div className="hr" />}
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
              {enable.isPending ? 'Verifying…' : enableLabel}
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
  )
}
