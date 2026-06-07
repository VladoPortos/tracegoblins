import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router'
import { AuthLayout } from './AuthLayout'
import { Field } from '../components/atoms/Field'
import { useRunSetup, useSetupStatus } from '../api/queries'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'

export function SetupWizard() {
  const nav = useNavigate()
  const setup = useSetupStatus()
  const run = useRunSetup()
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)

  if (setup.isPending) return <FullScreenSpinner />
  if (setup.data && !setup.data.needs_setup) return <Navigate to="/login" replace />

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password.length < 12) { setError('Password must be at least 12 characters.'); return }
    if (password !== confirm) { setError('Passwords do not match.'); return }
    run.mutate({ email, display_name: displayName, password }, {
      onSuccess: () => nav('/', { replace: true }),
      onError: () => setError('Setup failed. It may already be completed.'),
    })
  }

  return (
    <AuthLayout eyebrow="First-run setup" title="Create the first administrator" sub="This one-time wizard creates your admin account and the default General team, then locks itself.">
      <form onSubmit={submit} className="col gap3">
        <Field label="Email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <Field label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
        <Field label="Password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} hint="At least 12 characters." required />
        <Field label="Confirm password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        {error && <div className="tag tag-needs-fix" style={{ alignSelf: 'flex-start' }}>{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={run.isPending} style={{ justifyContent: 'center', padding: 10 }}>
          {run.isPending ? 'Creating…' : 'Create admin'}
        </button>
      </form>
    </AuthLayout>
  )
}
