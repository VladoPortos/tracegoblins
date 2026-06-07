// Render an ISO-8601 timestamp as a compact "YYYY-MM-DD HH:MM".
// We slice the ISO string rather than constructing a Date so the AWX-reported
// wall-clock time is shown verbatim (no browser-timezone shift).
export function shortTime(iso: string | null | undefined): string {
  if (!iso) return ''
  return iso.slice(0, 16).replace('T', ' ')
}

// Seconds -> "42s" / "3m 12s" / "3m"; em dash for missing values.
export function fmtDuration(s: number | null | undefined): string {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)}s`
  const m = Math.floor(s / 60)
  const r = Math.round(s % 60)
  return r > 0 ? `${m}m ${r}s` : `${m}m`
}

// Strip the collection prefix from Ansible role names for display.
export const roleLabel = (r: string | null) => (r ? r.replace(/^dxc\.xaas\./, '') : 'play tasks')

export const runWord = (n: number) => (n === 1 ? 'run' : 'runs')
