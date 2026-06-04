import type { KbStatus } from '../../api/kb'

// KB signature statuses are a distinct vocabulary from task statuses
// ({needs-fix, known-issue, resolved, note}). They render with the dedicated
// .tag-<status> classes defined in theme.css, showing the literal status text.
export function KbStatusBadge({ status }: { status: KbStatus | string }) {
  return <span className={'tag tag-' + status}>{status}</span>
}
