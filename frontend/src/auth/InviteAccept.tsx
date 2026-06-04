import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { AuthLayout } from './AuthLayout'
import { Field } from '../components/atoms/Field'
import { apiFetch, type InviteInfo } from '../api/client'
import { useAcceptInvite } from '../api/queries'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'

export function InviteAccept() {
  const { token = '' } = useParams()
  const nav = useNavigate()
  const info = useQuery<InviteInfo>({
    queryKey: ['invite', token],
    queryFn: () => apiFetch<InviteInfo>(`/invites/${token}`),
    retry: false,
  })
  const accept = useAcceptInvite(token)
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)

  if (info.isPending) return <FullScreenSpinner />
  if (info.isError) {
    return <AuthLayout eyebrow="Invite" title="This invite is invalid or expired" sub="Ask an administrator for a fresh invite link." children={null} />
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password.length < 12) { setError('Password must be at least 12 characters.'); return }
    if (password !== confirm) { setError('Passwords do not match.'); return }
    accept.mutate({ display_name: displayName, password }, {
      onSuccess: () => nav('/', { replace: true }),
      onError: () => setError('Could not accept this invite.'),
    })
  }

  return (
    <AuthLayout eyebrow="You're invited" title="Set up your account" sub={`Joining as ${info.data!.email}.`}>
      <form onSubmit={submit} className="col gap3">
        <Field label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
        <Field label="Password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} hint="At least 12 characters." required />
        <Field label="Confirm password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        {error && <div className="tag tag-needs-fix" style={{ alignSelf: 'flex-start' }}>{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={accept.isPending} style={{ justifyContent: 'center', padding: 10 }}>
          {accept.isPending ? 'Joining…' : 'Accept invite'}
        </button>
      </form>
    </AuthLayout>
  )
}
