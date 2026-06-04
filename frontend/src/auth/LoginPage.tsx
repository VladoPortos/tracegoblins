import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router'
import { AuthLayout } from './AuthLayout'
import { Field } from '../components/atoms/Field'
import { Glyph } from '../components/atoms/Glyph'
import { useLogin } from '../api/queries'
import { useLoginVerify } from '../api/mfa'
import { ApiError } from '../api/client'

export function LoginPage() {
  const nav = useNavigate()
  const loc = useLocation() as { state?: { from?: string } }
  const login = useLogin()
  const verify = useLoginVerify()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [step, setStep] = useState<'password' | 'code'>('password')
  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    login.mutate({ email, password, remember }, {
      onSuccess: (res) => {
        if (res && typeof res === 'object' && 'mfa_required' in res) {
          setError(null)
          setStep('code')
          return
        }
        nav(loc.state?.from ?? '/', { replace: true })
      },
      onError: (err) => setError(err instanceof ApiError && err.status === 429
        ? 'Too many attempts. Try again later.' : 'Invalid email or password.'),
    })
  }

  const submitCode = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    verify.mutate({ code }, {
      onSuccess: () => nav(loc.state?.from ?? '/', { replace: true }),
      onError: (err) => setError(err instanceof ApiError && err.status === 429
        ? 'Too many attempts. Try again later.' : 'Invalid code. Try again or use a recovery code.'),
    })
  }

  if (step === 'code') {
    return (
      <AuthLayout eyebrow="Two-factor authentication" title="Verify your identity" sub="Enter the code from your authenticator app to continue.">
        <form onSubmit={submitCode} className="col gap3">
          <Field
            label={useRecovery ? 'Recovery code' : 'Authenticator code'}
            type="text"
            inputMode={useRecovery ? undefined : 'numeric'}
            autoComplete={useRecovery ? 'off' : 'one-time-code'}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />
          {error && <div className="tag tag-needs-fix" style={{ alignSelf: 'flex-start' }}>{error}</div>}
          <button className="btn btn-primary" type="submit" disabled={verify.isPending} style={{ justifyContent: 'center', padding: 10 }}>
            {verify.isPending ? 'Verifying…' : 'Verify'} <Glyph name="arrowR" size={16} />
          </button>
        </form>
        <p className="muted" style={{ fontSize: 13, marginTop: 18, textAlign: 'center' }}>
          <button
            type="button"
            className="btn-link"
            style={{ fontSize: 13, color: 'var(--text-2)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
            onClick={() => { setUseRecovery(!useRecovery); setCode('') }}
          >
            {useRecovery ? 'Use your authenticator app' : 'Use a recovery code instead'}
          </button>
        </p>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout eyebrow="Welcome back" title="Sign in to your workspace" sub="Triage AWX/Ansible runs and collaborate with your team.">
      <form onSubmit={submit} className="col gap3">
        <Field label="Email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <Field label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <label className="row gap1 muted" style={{ fontSize: 12.5, cursor: 'pointer' }}>
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Keep me signed in
        </label>
        {error && <div className="tag tag-needs-fix" style={{ alignSelf: 'flex-start' }}>{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={login.isPending} style={{ justifyContent: 'center', padding: 10 }}>
          {login.isPending ? 'Signing in…' : 'Sign in'} <Glyph name="arrowR" size={16} />
        </button>
      </form>
      <div className="row gap2" style={{ margin: '18px 0', color: 'var(--text-3)', fontSize: 12 }}>
        <div className="grow" style={{ height: 1, background: 'var(--border)' }} />or<div className="grow" style={{ height: 1, background: 'var(--border)' }} />
      </div>
      <button className="btn" disabled style={{ justifyContent: 'center', width: '100%', opacity: 0.6 }} title="SSO is configured by your administrator (coming soon)">
        <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>SSO</span> Continue with SSO
      </button>
      <p className="muted" style={{ fontSize: 13, marginTop: 24, textAlign: 'center' }}>
        Need an account? Ask an administrator for an invite link.
      </p>
    </AuthLayout>
  )
}
