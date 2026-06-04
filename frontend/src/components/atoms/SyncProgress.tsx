import type { Controller } from '../../api/controllers'

/** N/M progress bar shown while a controller sync is running. Falls back to an
 *  indeterminate bar when the total isn't known yet (first tick of a sync). */
export function SyncProgress({ c }: { c: Controller }) {
  if (c.last_sync_status !== 'running') return null
  const done = c.sync_done ?? 0
  const total = c.sync_total ?? 0
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : null
  return (
    <div className="col" style={{ gap: 4, minWidth: 180 }}>
      <div className="row gap2" style={{ fontSize: 11.5, color: 'var(--text-2)' }}>
        <span>Syncing…</span>
        <div className="grow" />
        {total > 0
          ? <span className="mono tnum">{done} / {total}</span>
          : <span className="mono tnum">{done}</span>}
      </div>
      <div style={{ height: 6, borderRadius: 3, background: 'var(--surface-2)', overflow: 'hidden' }}>
        <div
          style={{
            height: '100%', borderRadius: 3, background: 'var(--accent)',
            width: pct == null ? '40%' : `${pct}%`,
            transition: 'width .3s ease',
            animation: pct == null ? 'indeterminate 1.1s ease-in-out infinite' : undefined,
          }}
        />
      </div>
      {c.sync_current_job && (
        <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-3)' }}>
          importing job #{c.sync_current_job}
        </div>
      )}
      <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>
        Safe to navigate away — sync continues in the background.
      </div>
    </div>
  )
}
