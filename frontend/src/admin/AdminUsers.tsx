import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AdminLayout } from './AdminLayout'
import { Modal } from '../components/atoms/Modal'
import { Field } from '../components/atoms/Field'
import { Glyph } from '../components/atoms/Glyph'
import { Avatar } from '../components/atoms/Avatar'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { ApiError } from '../api/client'
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
  const [link, setLink] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const generate = (e: React.FormEvent) => {
    e.preventDefault()
    createInvite.mutate({ email, role }, { onSuccess: (r) => setLink(r.link) })
  }
  const closeModal = () => { setOpen(false); setLink(null); setEmail(''); setRole('user') }

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
            {!u.is_active && <span className="tag tag-needs-fix">Deactivated</span>}
            <span className={`tag ${u.totp_enabled ? 'tag-ok' : 'tag-skip'}`} title={u.totp_enabled ? '2FA enabled' : '2FA disabled'}>
              {u.totp_enabled ? '2FA on' : '2FA off'}
            </span>
            {u.totp_enabled && (
              <button
                className="btn sm"
                title="Reset this user's 2FA (lost-device recovery)"
                onClick={() => {
                  if (window.confirm(`Reset 2FA for ${u.display_name}? They will need to re-enroll.`)) {
                    resetUser2fa.mutate(u.id, { onSuccess: () => { void qc.invalidateQueries({ queryKey: usersKey }) } })
                  }
                }}
              >
                Reset 2FA
              </button>
            )}
            <select className="select" style={{ width: 110 }} value={u.role} onChange={(e) => { setError(null); changeRole.mutate({ id: u.id, role: e.target.value }, { onError: (err) => setError(err instanceof ApiError && typeof err.detail === 'string' ? err.detail : 'Could not change role.') }) }}>
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
            <button className="btn sm" onClick={() => setActive.mutate({ id: u.id, active: !u.is_active })}>
              {u.is_active ? 'Deactivate' : 'Activate'}
            </button>
          </div>
        ))}
      </div>

      <Modal open={open} onOpenChange={(o) => (o ? setOpen(true) : closeModal())} title="Invite a user">
        {!link ? (
          <form onSubmit={generate} className="col gap3">
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
            <p className="muted" style={{ fontSize: 13 }}>Copy this link and send it to the invitee. It expires in 72 hours.</p>
            <div className="row gap2">
              <input className="input mono" data-testid="invite-link" readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
              <button className="btn" onClick={() => navigator.clipboard?.writeText(link)} aria-label="Copy link"><Glyph name="copy" size={15} /></button>
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
