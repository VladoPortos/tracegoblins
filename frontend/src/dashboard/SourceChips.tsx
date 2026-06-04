import { useSearchParams } from 'react-router'
import { Glyph } from '../components/atoms/Glyph'
import { LastSyncChip } from '../components/atoms/LastSyncChip'
import { SyncProgress } from '../components/atoms/SyncProgress'
import { useControllers, useSyncController } from '../api/controllers'

/** Source value: 'all' | 'uploads' | a controller id. Backed by ?src=. */
export function useSourceSelection(): [string, (v: string) => void] {
  const [params, setParams] = useSearchParams()
  const src = params.get('src') || 'all'
  const setSrc = (v: string) => {
    const next = new URLSearchParams(params)
    if (v === 'all') next.delete('src')
    else next.set('src', v)
    setParams(next, { replace: false })
  }
  return [src, setSrc]
}

export function SourceChips() {
  const controllers = useControllers()
  const syncCtl = useSyncController()
  const [src, setSrc] = useSourceSelection()
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
          <LastSyncChip status={active.last_sync_status} at={active.last_sync_at} error={active.last_sync_error} />
          <button
            className="btn btn-ghost sm"
            onClick={() => void syncCtl.mutateAsync(active.id)}
            disabled={syncCtl.isPending || active.last_sync_status === 'running'}
            title="Sync now"
          >
            <Glyph name="spinner" size={13} />Sync now
          </button>
          {active.last_sync_status === 'running' && <SyncProgress c={active} />}
        </div>
      )}
    </div>
  )
}
