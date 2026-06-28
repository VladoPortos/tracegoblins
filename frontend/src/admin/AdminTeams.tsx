import { useState } from 'react'
import { AdminLayout } from './AdminLayout'
import { Modal } from '../components/atoms/Modal'
import { Field } from '../components/atoms/Field'
import { Glyph } from '../components/atoms/Glyph'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { errorMessage, type TeamOut } from '../api/client'
import {
  useAddTeamMember, useAdminTeams, useAdminUsers, useCreateTeam,
  useDeleteTeam, useRemoveTeamMember, useRenameTeam,
} from '../api/queries'

// Team detail: rename, members (add/remove), delete — exercises the full §14 "membership"
// surface and surfaces the last-team / default-team 409s inline.
function TeamDetail({ team, onClose }: { team: TeamOut; onClose: () => void }) {
  const users = useAdminUsers()
  const rename = useRenameTeam()
  const del = useDeleteTeam()
  const addM = useAddTeamMember()
  const removeM = useRemoveTeamMember()
  const [name, setName] = useState(team.name)
  const [addId, setAddId] = useState('')
  const [error, setError] = useState<string | null>(null)

  const all = users.data ?? []
  const members = all.filter((u) => u.teams.some((t) => t.id === team.id))
  const nonMembers = all.filter((u) => !u.teams.some((t) => t.id === team.id))
  const fail = (e: unknown) => setError(errorMessage(e, 'Action failed.'))

  return (
    <Modal open onOpenChange={(o) => { if (!o) onClose() }} title={`Team · ${team.name}`} width={520}>
      <div className="col gap4">
        {error && <div className="tag tag-needs-fix" role="alert" style={{ alignSelf: 'flex-start' }}>{error}</div>}
        <div className="row gap2" style={{ alignItems: 'flex-end' }}>
          <div className="grow"><Field label="Team name" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <button className="btn btn-primary" disabled={team.is_default || rename.isPending}
            onClick={() => { setError(null); rename.mutate({ id: team.id, name }, { onError: fail }) }}>Save</button>
        </div>
        <div>
          <div className="field-label">Members ({members.length})</div>
          <div className="col" style={{ gap: 4 }}>
            {members.map((m) => (
              <div key={m.id} className="row gap2" style={{ padding: '6px 0' }}>
                <span className="grow" style={{ fontSize: 13 }}>{m.display_name}{' '}
                  <span className="dim mono" style={{ fontSize: 11 }}>{m.email}</span></span>
                <button className="btn sm btn-danger"
                  onClick={() => { setError(null); removeM.mutate({ teamId: team.id, userId: m.id }, { onError: fail }) }}>Remove</button>
              </div>
            ))}
            {members.length === 0 && <div className="dim" style={{ fontSize: 12.5 }}>No members yet.</div>}
          </div>
        </div>
        <div className="row gap2" style={{ alignItems: 'flex-end' }}>
          <div className="grow">
            <label className="field-label" htmlFor="add-member">Add member</label>
            <select id="add-member" className="select" value={addId} onChange={(e) => setAddId(e.target.value)}>
              <option value="">Select a user…</option>
              {nonMembers.map((u) => <option key={u.id} value={u.id}>{u.display_name} ({u.email})</option>)}
            </select>
          </div>
          <button className="btn" disabled={!addId}
            onClick={() => { setError(null); addM.mutate({ teamId: team.id, userId: addId }, { onSuccess: () => setAddId(''), onError: fail }) }}>Add</button>
        </div>
        <div className="hr" />
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <button className="btn btn-danger" disabled={team.is_default}
            onClick={() => { setError(null); del.mutate(team.id, { onSuccess: onClose, onError: fail }) }}>Delete team</button>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </Modal>
  )
}

export function AdminTeams() {
  const teams = useAdminTeams()
  const createTeam = useCreateTeam()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [createErr, setCreateErr] = useState<string | null>(null)
  const [detail, setDetail] = useState<TeamOut | null>(null)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setCreateErr(null)
    createTeam.mutate(name, {
      onSuccess: () => { setOpen(false); setName('') },
      onError: (err) => setCreateErr(errorMessage(err, 'Could not create this team.')),  // ADMIN1
    })
  }
  const action = <button className="btn btn-primary" onClick={() => setOpen(true)}><Glyph name="plus" size={16} />New team</button>

  if (teams.isPending) return <AdminLayout action={action}><FullScreenSpinner /></AdminLayout>

  return (
    <AdminLayout action={action}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px,1fr))', gap: 16 }}>
        {(teams.data ?? []).map((t) => (
          <button key={t.id} className="card" aria-label={t.name} onClick={() => setDetail(t)}
            style={{ padding: 16, textAlign: 'left', cursor: 'pointer' }}>
            <div className="row gap2">
              <Glyph name="users" size={16} />
              <span className="h2" style={{ fontSize: 15 }}>{t.name}</span>
              {t.is_default && <span className="chip" style={{ fontSize: 10.5 }}>default</span>}
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>{t.member_count} member{t.member_count === 1 ? '' : 's'}</div>
          </button>
        ))}
      </div>

      <Modal open={open} onOpenChange={setOpen} title="Create a team">
        <form onSubmit={submit} className="col gap3">
          <Field label="Team name" value={name} onChange={(e) => setName(e.target.value)} required />
          {createErr && <div className="tag tag-needs-fix" role="alert">{createErr}</div>}
          <div className="row gap2" style={{ justifyContent: 'flex-end' }}>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={createTeam.isPending}>Create</button>
          </div>
        </form>
      </Modal>

      {detail && <TeamDetail team={detail} onClose={() => setDetail(null)} />}
    </AdminLayout>
  )
}
