export type Status = 'ok' | 'changed' | 'skipped' | 'included' | 'unreachable' | 'failed'

export const STATUS: Record<Status, { label: string; cls: string }> = {
  ok:          { label: 'OK',          cls: 'st-ok' },
  changed:     { label: 'Changed',     cls: 'st-changed' },
  skipped:     { label: 'Skipped',     cls: 'st-skipped' },
  included:    { label: 'Included',    cls: 'st-included' },
  unreachable: { label: 'Unreachable', cls: 'st-unreachable' },
  failed:      { label: 'Failed',      cls: 'st-failed' },
}
export const isErr = (s: string): boolean => s === 'unreachable' || s === 'failed'
export const stCls = (s: string): string => 'st-' + (s === 'skipped' ? 'skipped' : s)
