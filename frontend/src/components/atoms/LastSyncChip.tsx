import { Glyph } from './Glyph'
import { shortTime } from './format'

type Sync = 'never' | 'running' | 'ok' | 'error'

const META: Record<Sync, { label: string; cls: string; icon: string }> = {
  never:   { label: 'Never synced', cls: '',                 icon: 'clock' },
  running: { label: 'Syncing…',     cls: 'tag-known-issue',  icon: 'spinner' },
  ok:      { label: 'Synced',       cls: 'tag-resolved',     icon: 'check' },
  error:   { label: 'Sync failed',  cls: 'tag-needs-fix',    icon: 'alert' },
}

export function LastSyncChip({ status, at, error }: { status: string; at: string | null; error: string | null }) {
  const m = META[(status as Sync)] ?? META.never
  const title = status === 'error' && error ? error : status === 'ok' && at ? shortTime(at) : undefined
  return (
    <span className={'tag ' + m.cls} role="status" aria-label={m.label} title={title}>
      <Glyph name={m.icon} size={12} style={status === 'running' ? { animation: 'spin360 1s linear infinite' } : undefined} />
      {m.label}
      {status === 'ok' && at && <span className="mono dim" style={{ fontSize: 10.5, marginLeft: 2 }}>{shortTime(at)}</span>}
    </span>
  )
}
