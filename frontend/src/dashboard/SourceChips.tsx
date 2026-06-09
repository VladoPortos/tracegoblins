import { Glyph } from '../components/atoms/Glyph'
import { SyncProgress } from '../components/atoms/SyncProgress'
import { SyncNowChip } from './SyncNowChip'
import { useControllers, useSyncController } from '../api/controllers'
import { useLogsState } from './useLogsState'

export function SourceChips() {
  const controllers = useControllers()
  const syncCtl = useSyncController()
  const { src, setSrc } = useLogsState()
  const list = controllers.data ?? []

  const chip = (value: string, label: string, icon?: string) => (
    <button
      key={value}
      className={'btn sm' + (src === value ? ' btn-primary' : ' btn-ghost')}
      aria-pressed={src === value}
      onClick={() => setSrc(value)}
    >
      {icon && <Glyph name={icon} size={13} />}{label}
    </button>
  )

  const active = list.find((c) => c.id === src)

  return (
    <div className="col" style={{ gap: 10, position: 'sticky', top: 0, zIndex: 5, background: 'var(--bg)', paddingBottom: 4 }}>
      <div className="row gap1 wrap" style={{ alignItems: 'center' }}>
        {chip('all', 'All')}
        {list.map((c) => chip(c.id, c.name, 'server'))}
        {chip('uploads', 'Uploads', 'folder')}
      </div>
      {active && (
        <div className="row gap2 wrap" style={{ alignItems: 'center' }}>
          <SyncNowChip controller={active} onSync={(id) => void syncCtl.mutateAsync(id)} syncing={syncCtl.isPending} />
          {active.last_sync_status === 'running' && <SyncProgress c={active} />}
        </div>
      )}
    </div>
  )
}
