import { Glyph } from './Glyph'

// Belt-and-suspenders over the server allowlist: re-check the scheme client-side and render plain
// text (no anchor) for anything that isn't http/https/mailto. Plain text only — never
// dangerouslySetInnerHTML. Shared by the KB + annotation link chips (FECMP4).
export function isSafeLinkUrl(url: string): boolean {
  try {
    const scheme = new URL(url, window.location.origin).protocol.replace(':', '').toLowerCase()
    return scheme === 'http' || scheme === 'https' || scheme === 'mailto'
  } catch {
    return false
  }
}

export function SafeLinkChip({ link }: { link: { label?: string; url: string } }) {
  const label = link.label || link.url
  if (!isSafeLinkUrl(link.url)) {
    return <span className="chip" style={{ color: 'var(--text-3)' }}><Glyph name="link" size={11} />{label}</span>
  }
  return (
    <a className="chip" href={link.url} target="_blank" rel="noopener noreferrer nofollow" style={{ color: 'var(--accent)', textDecoration: 'none' }}>
      <Glyph name="link" size={11} />{label}
    </a>
  )
}
