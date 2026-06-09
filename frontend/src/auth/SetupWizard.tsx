import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router'
import { AuthLayout } from './AuthLayout'
import { Field } from '../components/atoms/Field'
import { PasswordFields, validateNewPassword } from '../components/auth/PasswordFields'
import { errorMessage } from '../api/client'
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
    const invalid = validateNewPassword(password, confirm)
    if (invalid) { setError(invalid); return }
    run.mutate({ email, display_name: displayName, password }, {
      onSuccess: () => nav('/', { replace: true }),
      onError: (e) => setError(errorMessage(e, 'Setup failed. It may already be completed.')),
    })
  }

  return (
    <AuthLayout eyebrow="First-run setup" title="Create the first administrator" sub="This one-time wizard creates your admin account and the default General team, then locks itself.">
      <form onSubmit={submit} className="col gap3">
        <Field label="Email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <Field label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
        <PasswordFields password={password} confirm={confirm} onPasswordChange={setPassword} onConfirmChange={setConfirm} />
        {error && <div className="tag tag-needs-fix" style={{ alignSelf: 'flex-start' }}>{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={run.isPending} style={{ justifyContent: 'center', padding: 10 }}>
          {run.isPending ? 'Creating…' : 'Create admin'}
        </button>
      </form>
    </AuthLayout>
  )
}
