import type { ReactNode } from 'react'
import { Glyph } from '../atoms/Glyph'
import { useCopied } from '../atoms/useCopied'

// Recovery-codes grid + copy-all button, shown once after enable/regenerate.
// Warning copy, the optional explanatory note and the primary action differ per page.
export function RecoveryCodesPanel({ codes, warning, note, action, gap = 14 }: {
  codes: string[]
  warning: string
  note?: ReactNode
  action: ReactNode
  gap?: number
}) {
  const { copied, copy } = useCopied()
  return (
    <div className="col" style={{ gap }}>
      <div className="row gap2" style={{ alignItems: 'center' }}>
        <Glyph name="alert" size={18} style={{ color: 'var(--warn)' }} />
        <span style={{ fontWeight: 600 }}>{warning}</span>
      </div>
      {note}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 24px',
        fontFamily: 'var(--font-mono)', fontSize: 14,
        background: 'var(--surface-2)', borderRadius: 8, padding: '14px 18px',
      }}>
        {codes.map((c) => (
          <span key={c} style={{ userSelect: 'all', letterSpacing: '0.05em' }}>{c}</span>
        ))}
      </div>
      <div className="row gap3">
        <button className="btn btn-secondary" onClick={() => copy(codes.join('\n'))}>
          <Glyph name="copy" size={15} />
          {copied ? 'Copied!' : 'Copy all'}
        </button>
        {action}
      </div>
    </div>
  )
}
