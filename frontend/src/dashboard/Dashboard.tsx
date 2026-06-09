import { useState } from 'react'
import { Glyph } from '../components/atoms/Glyph'
import { PageShell } from '../components/atoms/PageShell'
import { RunsList } from './RunsList'
import { UploadModal } from '../upload/UploadModal'
import { useMe } from '../api/queries'
import { useLogsState, useLogsPersistence, type Tab } from './useLogsState'

export function Dashboard() {
  useLogsPersistence()
  const { tab, setTab } = useLogsState()
  const [upload, setUpload] = useState(false)
  const me = useMe()
  const tabs = [['mine', 'My logs', 'folder'], ['shared', 'Shared with me', 'inbox'], ['team', 'Team workspace', 'users']] as const

  return (
    <PageShell>
        <div className="row gap4" style={{ alignItems: 'flex-end', marginBottom: 22, flexWrap: 'wrap' }}>
          <div className="grow">
            <div className="eyebrow" style={{ marginBottom: 6 }}>Workspace</div>
            <h1 className="h1">Job logs</h1>
            <p className="muted" style={{ fontSize: 13.5, marginTop: 4 }}>Triage AWX / Ansible runs and spot what broke on the Status Map.</p>
          </div>
          <button className="btn btn-primary" onClick={() => setUpload(true)}><Glyph name="upload" size={16} />Upload log</button>
        </div>
        <div className="seg" style={{ marginBottom: 20 }}>
          {tabs.map(([id, label, ic]) => (
            <button key={id} aria-pressed={tab === id} onClick={() => setTab(id as Tab)}><Glyph name={ic} size={14} />{label}</button>
          ))}
        </div>
        {tab === 'mine' && <RunsList scope="mine" onUpload={() => setUpload(true)} />}
        {tab === 'shared' && <RunsList scope="shared" />}
        {tab === 'team' && <RunsList scope="team" />}
      <UploadModal open={upload} onOpenChange={setUpload} teams={me.data?.teams ?? []} />
    </PageShell>
  )
}
