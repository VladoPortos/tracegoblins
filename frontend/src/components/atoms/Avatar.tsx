const PALETTE = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']
function colorFor(seed: string) {
  let h = 0
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}
function initialsFor(name: string) {
  const parts = name.trim().split(/\s+/)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?'
}
export function Avatar({ name, color, initials, size }: { name: string; color?: string | null; initials?: string | null; size?: 'sm' | 'lg' }) {
  const cls = 'avatar' + (size ? ' ' + size : '')
  return (
    <div className={cls} style={{ background: color || colorFor(name) }} title={name}>
      {initials || initialsFor(name)}
    </div>
  )
}
