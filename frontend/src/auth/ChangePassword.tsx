import { useState } from 'react'
import { useNavigate } from 'react-router'
import { AuthLayout } from './AuthLayout'
import { Field } from '../components/atoms/Field'
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
    if (next.length < 12) { setError('New password must be at least 12 characters.'); return }
    if (next !== confirm) { setError('Passwords do not match.'); return }
    change.mutate({ current_password: current, new_password: next }, {
      onSuccess: () => nav('/', { replace: true }),
      onError: () => setError('Current password is incorrect.'),
    })
  }

  const forced = me.data?.must_change_password
  return (
    <AuthLayout eyebrow="Account security" title="Change your password" sub={forced ? 'You must set a new password before continuing.' : undefined}>
      <form onSubmit={submit} className="col gap3">
        <Field label="Current password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        <Field label="New password" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} hint="At least 12 characters." required />
        <Field label="Confirm new password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        {error && <div className="tag tag-needs-fix" style={{ alignSelf: 'flex-start' }}>{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={change.isPending} style={{ justifyContent: 'center', padding: 10 }}>
          {change.isPending ? 'Updating…' : 'Update password'}
        </button>
      </form>
    </AuthLayout>
  )
}
