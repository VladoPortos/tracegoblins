import { Glyph } from './Glyph'
export function FullScreenSpinner() {
  return (
    <div className="col" style={{ height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--text-3)' }}>
      <span className="spin"><Glyph name="spinner" size={22} /></span>
    </div>
  )
}
