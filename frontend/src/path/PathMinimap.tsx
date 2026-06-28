// PathMinimap — thumbnail overview with viewport rect + click-to-jump.
// Math mirrors prototype Run Flow.dc.html lines 606–636 + onMinimapClick 833–838.
import type { LaidOut } from './layout'
import type { PathStatus } from '../api/path'

const MINI_W = 210
const MINI_H = 124
const PAD = 10

function statusFill(type: string, status: PathStatus | undefined): string {
  // mirror PathNodeCard exactly (PATH4): containers + decision = included, loop = changed, item = dim
  if (type === 'role' || type === 'block' || type === 'include' || type === 'play' || type === 'when') return 'var(--included)'
  if (type === 'loop') return 'var(--changed)'
  if (type === 'item') return 'var(--dim)'
  const s = status === 'unreachable' ? 'failed' : status === 'never_run' ? 'skipped' : (status ?? 'skipped')
  return `var(--${s})`
}

export function PathMinimap({
  layout,
  panX,
  panY,
  zoom,
  cw,
  ch,
  onJump,
}: {
  layout: LaidOut
  panX: number
  panY: number
  zoom: number
  cw: number
  ch: number
  onJump: (worldX: number, worldY: number) => void
}) {
  // Guard against zero-size layout: division below would yield Infinity/NaN.
  if (!layout.worldW || !layout.worldH) return null
  const ms = Math.min((MINI_W - PAD * 2) / layout.worldW, (MINI_H - PAD * 2) / layout.worldH)
  const offx = (MINI_W - layout.worldW * ms) / 2
  const offy = (MINI_H - layout.worldH * ms) / 2

  // Viewport rect in mini-space
  const vx = offx + (-panX / zoom) * ms
  const vy = offy + (-panY / zoom) * ms
  const vw = (cw / zoom) * ms
  const vh = (ch / zoom) * ms

  function handleClick(e: React.MouseEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX - r.left
    const my = e.clientY - r.top
    const wx = (mx - offx) / ms
    const wy = (my - offy) / ms
    onJump(wx, wy)
  }

  return (
    <div
      data-testid="path-minimap"
      style={{
        position: 'absolute',
        right: 14,
        bottom: 14,
        padding: 6,
        background: 'var(--panel-glass)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        backdropFilter: 'blur(8px)',
        zIndex: 4,
        pointerEvents: 'auto',
      }}
    >
      <svg
        width={MINI_W}
        height={MINI_H}
        onClick={handleClick}
        style={{ display: 'block', cursor: 'pointer', borderRadius: 5 }}
      >
        {/* Canvas background */}
        <rect x={0} y={0} width={MINI_W} height={MINI_H} fill="var(--canvas)" />

        {/* Node rects */}
        {layout.nodes.map((n, i) => (
          <rect
            key={i}
            x={offx + n.x * ms}
            y={offy + n.y * ms}
            width={Math.max(3, n.w * ms)}
            height={Math.max(2, n.h * ms)}
            rx={1.5}
            fill={statusFill(n.type, n.status)}
          />
        ))}

        {/* Viewport rect */}
        <rect
          x={vx}
          y={vy}
          width={Math.max(0, vw)}
          height={Math.max(0, vh)}
          fill="none"
          stroke="var(--flow)"
          strokeWidth={1.5}
          rx={2}
        />
      </svg>
    </div>
  )
}
