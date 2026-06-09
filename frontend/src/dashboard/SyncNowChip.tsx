import type { CSSProperties } from 'react'
import { Glyph } from '../components/atoms/Glyph'
import { LastSyncChip } from '../components/atoms/LastSyncChip'
import type { Controller } from '../api/controllers'

// LastSyncChip + "Sync now" button pair shown next to a controller in the
// dashboard (source chips and grouped team cards). The AwxControllers admin
// page keeps its own variant.
export function SyncNowChip({ controller: c, onSync, syncing, ariaLabel, buttonStyle }: {
  controller: Controller
  onSync: (id: string) => void
  syncing: boolean
  ariaLabel?: string
  buttonStyle?: CSSProperties
}) {
  return (
    <>
      <LastSyncChip status={c.last_sync_status} at={c.last_sync_at} error={c.last_sync_error} />
      <button
        className="btn btn-ghost sm"
        onClick={() => onSync(c.id)}
        disabled={syncing || c.last_sync_status === 'running'}
        title="Sync now"
        aria-label={ariaLabel}
        style={buttonStyle}
      >
        <Glyph name="spinner" size={13} />Sync now
      </button>
    </>
  )
}
