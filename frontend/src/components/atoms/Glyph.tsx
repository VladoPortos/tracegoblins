import type { CSSProperties, JSX } from 'react'

type IconProps = { size?: number; stroke?: number; style?: CSSProperties }
const stroke = (d: string | string[], extra?: (p: IconProps) => JSX.Element) => (p: IconProps) => {
  const { size = 16, stroke: sw = 2, style } = p
  const paths = Array.isArray(d) ? d : [d]
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={style}>
      {paths.map((dd, i) => <path key={i} d={dd} />)}
      {extra?.(p)}
    </svg>
  )
}

export const ICONS: Record<string, (p: IconProps) => JSX.Element> = {
  logo: ({ size = 22, style }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={style}>
      <path d="M3 6.5 8 11l-5 4.5" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" />
      <path d="M11 17h9" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" opacity={0.5} />
      <circle cx="18.5" cy="6.5" r="2.4" fill="currentColor" />
    </svg>
  ),
  search: stroke('m21 21-4.3-4.3', () => <circle cx={11} cy={11} r={7} />),
  inbox: stroke(['M3 13h5l2 3h4l2-3h5', 'M5 5h14l2 8v6H3v-6z']),
  sparkle: stroke('M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z'),
  sun: stroke('M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19', () => <circle cx={12} cy={12} r={4} />),
  moon: stroke('M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z'),
  settings: stroke('M19.4 13a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1v.2a2 2 0 0 1-4 0v-.2A1.6 1.6 0 0 0 7 17.6a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H1a2 2 0 0 1 0-4h.2A1.6 1.6 0 0 0 2.4 7a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 7 2.4h.1A1.6 1.6 0 0 0 8 1a2 2 0 0 1 4 0a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.6 1.6 0 0 0 21.6 9H22a2 2 0 0 1 0 4h-.2', () => <circle cx={12} cy={12} r={3} />),
  logout: stroke(['M14 4h5v16h-5', 'M10 12H3', 'm6 8-4 4 4 4']),
  users: stroke(['M3 20a6 6 0 0 1 12 0', 'M16 5.5a3 3 0 0 1 0 5.8', 'M18 14a6 6 0 0 1 3 5.2'], () => <circle cx={9} cy={8} r={3} />),
  host: stroke(['M3 6.5h18M3 13.5h18', 'M7 10h.01M7 17h.01'], () => <><rect x={3} y={3.5} width={18} height={7} rx={1.5} /><rect x={3} y={13.5} width={18} height={7} rx={1.5} /></>),
  server: stroke(['M7 7h.01M7 17h.01', 'M3 4.5h18v6H3zM3 13.5h18v6H3z'], () => <><rect x={3} y={4.5} width={18} height={6} rx={1.5} /><rect x={3} y={13.5} width={18} height={6} rx={1.5} /></>),
  folder: stroke('M3 6a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z'),
  check: stroke('m5 12 5 5L20 6'),
  alert: stroke(['M12 3 2 20h20z', 'M12 10v4', 'M12 17.5h.01']),
  arrowR: stroke(['M5 12h14', 'm13 6 6 6-6 6']),
  chevL: stroke('m15 6-6 6 6 6'),
  chevR: stroke('m9 6 6 6-6 6'),
  chevD: stroke('m6 9 6 6 6-6'),
  plus: stroke(['M12 5v14', 'M5 12h14']),
  close: stroke(['M18 6 6 18', 'M6 6l12 12']),
  copy: stroke('M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1', () => <rect x={9} y={9} width={11} height={11} rx={2} />),
  link: stroke(['M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1', 'M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1']),
  clock: stroke('M12 8v4l3 2', () => <circle cx={12} cy={12} r={8} />),
  dots: stroke([], () => <><circle cx={5} cy={12} r={1.4} fill="currentColor" /><circle cx={12} cy={12} r={1.4} fill="currentColor" /><circle cx={19} cy={12} r={1.4} fill="currentColor" /></>),
  spinner: stroke('M12 3a9 9 0 1 0 9 9'),
  layers: stroke(['m12 3 9 5-9 5-9-5z', 'm3 13 9 5 9-5', 'm3 17 9 5 9-5']),
  grid: stroke([], () => <><rect x={4} y={4} width={7} height={7} rx={1.5} /><rect x={13} y={4} width={7} height={7} rx={1.5} /><rect x={4} y={13} width={7} height={7} rx={1.5} /><rect x={13} y={13} width={7} height={7} rx={1.5} /></>),
  rows: stroke(['M4 7h16', 'M4 12h16', 'M4 17h16']),
  map:    stroke(['M9 4 3 6.5v13L9 17l6 2.5 6-2.5v-13L15 6.5 9 4z', 'M9 4v13', 'M15 6.5v13']),
  upload: stroke(['M12 15V4', 'm7 9 5-5 5 5', 'M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2']),
  filter: stroke('M3 5h18l-7 8v6l-4-2v-4z'),
  bell:   stroke(['M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9', 'M13.7 21a2 2 0 0 1-3.4 0']),
  share:  stroke(['M8.6 13.5l6.8 4M15.4 6.5l-6.8 4'], () => <><circle cx={18} cy={5} r={3} /><circle cx={6} cy={12} r={3} /><circle cx={18} cy={19} r={3} /></>),
  trash:  stroke(['M4 7h16', 'M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2', 'M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13', 'M10 11v6M14 11v6']),
  expand: stroke(['M8 3H5a2 2 0 0 0-2 2v3', 'M21 8V5a2 2 0 0 0-2-2h-3', 'M3 16v3a2 2 0 0 0 2 2h3', 'M16 21h3a2 2 0 0 0 2-2v-3']),
  shield: stroke('M12 2 3 6.5v5c0 4.7 3.8 9.1 9 10.5 5.2-1.4 9-5.8 9-10.5v-5z'),
}

export function Glyph({ name, ...rest }: { name: keyof typeof ICONS | string } & IconProps) {
  const C = ICONS[name]
  return C ? <C {...rest} /> : null
}
