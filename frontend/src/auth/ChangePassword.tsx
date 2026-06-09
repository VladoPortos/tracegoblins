import { useState } from 'react'
import { useNavigate } from 'react-router'
import { AuthLayout } from './AuthLayout'
import { Field } from '../components/atoms/Field'
import { PasswordFields, validateNewPassword } from '../components/auth/PasswordFields'
import { errorMessage } from '../api/client'
import { useChangePassword, useMe } from '../api/queries'

export function ChangePassword() {
  const nav = useNavigate()
  const me = useMe()
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    const invalid = validateNewPassword(next, confirm)
    if (invalid) { setError(invalid); return }
    change.mutate({ current_password: current, new_password: next }, {
      onSuccess: () => nav('/', { replace: true }),
      onError: (e) => setError(errorMessage(e, 'Current password is incorrect.')),
    })
  }

  const forced = me.data?.must_change_password
  return (
    <AuthLayout eyebrow="Account security" title="Change your password" sub={forced ? 'You must set a new password before continuing.' : undefined}>
      <form onSubmit={submit} className="col gap3">
        <Field label="Current password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        <PasswordFields password={next} confirm={confirm} onPasswordChange={setNext} onConfirmChange={setConfirm} label="New password" confirmLabel="Confirm new password" />
        {error && <div className="tag tag-needs-fix" style={{ alignSelf: 'flex-start' }}>{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={change.isPending} style={{ justifyContent: 'center', padding: 10 }}>
          {change.isPending ? 'Updating…' : 'Update password'}
        </button>
      </form>
    </AuthLayout>
  )
}
