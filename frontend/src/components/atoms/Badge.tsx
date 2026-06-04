import type { ReactNode } from 'react'
export function Chip({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return <span className="chip" style={style}>{children}</span>
}
export function StatusChip({ kind, children }: { kind: 'ok' | 'changed' | 'unreachable' | 'included'; children: ReactNode }) {
  return <span className={`badge st-${kind}`}><span className="dot" />{children}</span>
}
import { STATUS } from './status'
export function Badge({ status, count, withLabel = true }: { status: string; count?: number; withLabel?: boolean }) {
  const m = (STATUS as Record<string, { label: string; cls: string }>)[status]
  if (!m) return null
  return (
    <span className={'badge ' + m.cls}>
      <span className="dot" />{withLabel && m.label}
      {count != null && <span className="tnum" style={{ opacity: 0.8 }}>{count}</span>}
    </span>
  )
}
