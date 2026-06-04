import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { Glyph } from '../components/atoms/Glyph'
import { RunsList } from './RunsList'
import { UploadModal } from '../upload/UploadModal'
import { useMe } from '../api/queries'

type Tab = 'mine' | 'shared' | 'team'
const TABS: Tab[] = ['mine', 'shared', 'team']

export function Dashboard() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab')
  const tab: Tab = (TABS as string[]).includes(raw ?? '') ? (raw as Tab) : 'mine'
  const [upload, setUpload] = useState(false)
  const me = useMe()
  const tabs = [['mine', 'My logs', 'folder'], ['shared', 'Shared with me', 'inbox'], ['team', 'Team workspace', 'users']] as const

  const setTab = (t: Tab) => {
    const next = new URLSearchParams(params)
    next.set('tab', t)
    if (t !== 'team') next.delete('src')   // source chip (added later) only meaningful in team scope
    setParams(next, { replace: false })
  }

  return (
    <div className="col scroll" style={{ height: '100%' }}>
      <div style={{ maxWidth: 'var(--maxw)', width: '100%', margin: '0 auto', padding: '28px clamp(20px,4vw,40px) 64px' }}>
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
      </div>
      <UploadModal open={upload} onOpenChange={setUpload} teams={me.data?.teams ?? []} />
    </div>
  )
}
