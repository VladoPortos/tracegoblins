import { useState } from 'react'
import { SettingsLayout } from './SettingsLayout'
import { Field } from '../components/atoms/Field'
import { Avatar } from '../components/atoms/Avatar'
import { useMe } from '../api/queries'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'

export function ProfileSettings() {
  const me = useMe()
  const [name, setName] = useState(me.data?.display_name ?? '')
  if (me.isPending || !me.data) return <FullScreenSpinner />
  const u = me.data
  return (
    <SettingsLayout>
      <div className="col" style={{ gap: 16 }}>
        <div className="row gap3">
          <Avatar name={u.display_name} color={u.avatar_color} initials={u.initials} size="lg" />
          <div className="col" style={{ gap: 2 }}>
            <span className="h2">{u.display_name}</span>
            <span className="muted" style={{ fontSize: 13 }}>{u.email}</span>
          </div>
        </div>
        <div className="hr" />
        <Field label="Display name" value={name} onChange={(e) => setName(e.target.value)} />
        <div>
          <label className="field-label">Email</label>
          <input className="input" value={u.email} disabled />
        </div>
        <div>
          <label className="field-label">Teams</label>
          <div className="row gap2 wrap">
            {u.teams.map((t) => <span className="chip" key={t.id}>{t.name}{t.is_default ? ' · default' : ''}</span>)}
          </div>
        </div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button className="btn btn-primary" disabled title="Profile editing lands in a later milestone">Save changes</button>
        </div>
      </div>
    </SettingsLayout>
  )
}
