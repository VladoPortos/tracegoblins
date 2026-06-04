import { Glyph } from './Glyph'
import type { KbLink } from '../../api/kb'

// Belt-and-suspenders over the server allowlist: re-check the scheme client-side
// and render plain text (no anchor) if it isn't http/https/mailto. Plain text only —
// never dangerouslySetInnerHTML.
export function isSafeKbUrl(url: string): boolean {
  try {
    const scheme = new URL(url, window.location.origin).protocol.replace(':', '').toLowerCase()
    return scheme === 'http' || scheme === 'https' || scheme === 'mailto'
  } catch {
    return false
  }
}

export function KbLinkRow({ link }: { link: KbLink }) {
  const label = link.label || link.url
  if (!isSafeKbUrl(link.url)) {
    return <span className="chip" style={{ color: 'var(--text-3)' }}><Glyph name="link" size={11} />{label}</span>
  }
  return (
    <a className="chip" href={link.url} target="_blank" rel="noopener noreferrer nofollow" style={{ color: 'var(--accent)', textDecoration: 'none' }}>
      <Glyph name="link" size={11} />{label}
    </a>
  )
}
