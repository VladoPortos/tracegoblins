export type Status = 'ok' | 'changed' | 'skipped' | 'included' | 'unreachable' | 'failed'

export const STATUS: Record<Status, { label: string; cls: string; glyph: string }> = {
  ok:          { label: 'OK',          cls: 'st-ok',          glyph: 'check' },
  changed:     { label: 'Changed',     cls: 'st-changed',     glyph: 'sparkle' },
  skipped:     { label: 'Skipped',     cls: 'st-skipped',     glyph: 'chevR' },
  included:    { label: 'Included',    cls: 'st-included',    glyph: 'layers' },
  unreachable: { label: 'Unreachable', cls: 'st-unreachable', glyph: 'alert' },
  failed:      { label: 'Failed',      cls: 'st-failed',      glyph: 'alert' },
}
export const STATUS_ORDER: Status[] = ['unreachable', 'failed', 'changed', 'ok', 'included', 'skipped']
export const isErr = (s: string): boolean => s === 'unreachable' || s === 'failed'
export const stCls = (s: string): string => 'st-' + (s === 'skipped' ? 'skipped' : s)

export function dominantStatus(statuses: Record<string, string>): Status {
  const vals = Object.values(statuses)
  for (const s of STATUS_ORDER) if (vals.includes(s)) return s
  return 'ok'
}
