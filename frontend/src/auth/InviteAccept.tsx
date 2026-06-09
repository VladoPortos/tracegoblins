import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { AuthLayout } from './AuthLayout'
import { Field } from '../components/atoms/Field'
import { PasswordFields, validateNewPassword } from '../components/auth/PasswordFields'
import { apiFetch, errorMessage, type InviteInfo } from '../api/client'
import { inviteKey, useAcceptInvite } from '../api/queries'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'

export function InviteAccept() {
  const { token = '' } = useParams()
  const nav = useNavigate()
  const info = useQuery<InviteInfo>({
    queryKey: inviteKey(token),
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
    const invalid = validateNewPassword(password, confirm)
    if (invalid) { setError(invalid); return }
    accept.mutate({ display_name: displayName, password }, {
      onSuccess: () => nav('/', { replace: true }),
      onError: (e) => setError(errorMessage(e, 'Could not accept this invite.')),
    })
  }

  return (
    <AuthLayout eyebrow="You're invited" title="Set up your account" sub={`Joining as ${info.data!.email}.`}>
      <form onSubmit={submit} className="col gap3">
        <Field label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
        <PasswordFields password={password} confirm={confirm} onPasswordChange={setPassword} onConfirmChange={setConfirm} />
        {error && <div className="tag tag-needs-fix" style={{ alignSelf: 'flex-start' }}>{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={accept.isPending} style={{ justifyContent: 'center', padding: 10 }}>
          {accept.isPending ? 'Joining…' : 'Accept invite'}
        </button>
      </form>
    </AuthLayout>
  )
}
