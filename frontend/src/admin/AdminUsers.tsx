import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AdminLayout } from './AdminLayout'
import { Modal } from '../components/atoms/Modal'
import { Field } from '../components/atoms/Field'
import { Glyph } from '../components/atoms/Glyph'
import { Avatar } from '../components/atoms/Avatar'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { shortTime } from '../components/atoms/format'
import { useCopied } from '../components/atoms/useCopied'
import { errorMessage, type InviteCreated } from '../api/client'
import { useAdminUsers, useChangeRole, useCreateInvite, useSetActive, usersKey } from '../api/queries'
import { useResetUser2fa } from '../api/mfa'

export function AdminUsers() {
  const users = useAdminUsers()
  const createInvite = useCreateInvite()
  const changeRole = useChangeRole()
  const setActive = useSetActive()
  const resetUser2fa = useResetUser2fa()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('user')
  const [invite, setInvite] = useState<InviteCreated | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const { copied, copy } = useCopied()

  const generate = (e: React.FormEvent) => {
    e.preventDefault()
    setInviteError(null)
    createInvite.mutate({ email, role }, {
      onSuccess: (r) => setInvite(r),
      onError: (err) => setInviteError(errorMessage(err, 'Could not create the invite.')),
    })
  }
  const closeModal = () => { setOpen(false); setInvite(null); setEmail(''); setRole('user'); setInviteError(null) }
  const expireHrs = invite
    ? Math.max(1, Math.round((new Date(invite.expires_at).getTime() - Date.now()) / 3600000))
    : 0

  const action = (
    <button className="btn btn-primary" onClick={() => setOpen(true)}><Glyph name="plus" size={16} />Invite user</button>
  )

  if (users.isPending) return <AdminLayout action={action}><FullScreenSpinner /></AdminLayout>

  return (
    <AdminLayout action={action}>
      {error && <div className="tag tag-needs-fix" role="alert" style={{ marginBottom: 12 }}>{error}</div>}
      <div className="card" style={{ overflow: 'hidden' }}>
        {(users.data ?? []).map((u, i) => (
          <div key={u.id} className="row gap3" style={{ padding: '12px 16px', borderTop: i ? '1px solid var(--border)' : 'none' }}>
            <Avatar name={u.display_name} color={u.avatar_color} />
            <div className="grow col" style={{ gap: 1, minWidth: 0 }}>
              <span style={{ fontSize: 13.5, fontWeight: 500 }}>{u.display_name}</span>
              <span className="dim mono truncate" style={{ fontSize: 11.5 }}>{u.email}</span>
            </div>
            <span className="dim" style={{ fontSize: 11.5, whiteSpace: 'nowrap' }} title="Last login">
              {u.last_login_at ? shortTime(u.last_login_at) : '—'}
            </span>
            {!u.is_active && <span className="tag tag-needs-fix">Deactivated</span>}
            <span className={`tag ${u.totp_enabled ? 'tag-resolved' : 'tag-note'}`} title={u.totp_enabled ? '2FA enabled' : '2FA disabled'}>
              {u.totp_enabled ? '2FA on' : '2FA off'}
            </span>
            {u.totp_enabled && (
              <button
                className="btn sm"
                title="Reset this user's 2FA (lost-device recovery)"
                onClick={() => {
                  if (window.confirm(`Reset 2FA for ${u.display_name}? They will need to re-enroll.`)) {
                    setError(null)
                    resetUser2fa.mutate(u.id, {
                      onSuccess: () => { void qc.invalidateQueries({ queryKey: usersKey }) },
                      onError: (err) => setError(errorMessage(err, 'Could not reset 2FA.')),  // ADMIN1
                    })
                  }
                }}
              >
                Reset 2FA
              </button>
            )}
            <select className="select" style={{ width: 110 }} value={u.role} onChange={(e) => { setError(null); changeRole.mutate({ id: u.id, role: e.target.value }, { onError: (err) => setError(errorMessage(err, 'Could not change role.')) }) }}>
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
            <button className="btn sm" onClick={() => { setError(null); setActive.mutate({ id: u.id, active: !u.is_active }, { onError: (err) => setError(errorMessage(err, 'Could not update this user.')) }) }}>
              {u.is_active ? 'Deactivate' : 'Activate'}
            </button>
          </div>
        ))}
      </div>

      <Modal open={open} onOpenChange={(o) => (o ? setOpen(true) : closeModal())} title="Invite a user">
        {!invite ? (
          <form onSubmit={generate} className="col gap3">
            {inviteError && <div className="tag tag-needs-fix" role="alert" style={{ alignSelf: 'flex-start' }}>{inviteError}</div>}
            <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <div>
              <label className="field-label">Role</label>
              <select className="select" value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            </div>
            <div className="row gap2" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-ghost" onClick={closeModal}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={createInvite.isPending}>
                <Glyph name="link" size={15} />Generate link
              </button>
            </div>
          </form>
        ) : (
          <div className="col gap3">
            <p className="muted" style={{ fontSize: 13 }}>Copy this link and send it to the invitee. It expires in {expireHrs} hour{expireHrs === 1 ? '' : 's'}.</p>
            <div className="row gap2">
              <input className="input mono" data-testid="invite-link" readOnly value={invite.link} onFocus={(e) => e.currentTarget.select()} />
              <button className="btn" onClick={() => copy(invite.link)} aria-label="Copy link" title={copied ? 'Copied' : 'Copy link'}><Glyph name={copied ? 'check' : 'copy'} size={15} /></button>
            </div>
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-primary" onClick={closeModal}>Done</button>
            </div>
          </div>
        )}
      </Modal>
    </AdminLayout>
  )
}
