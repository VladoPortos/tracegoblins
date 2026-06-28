// frontend/src/path/usePathController.ts
import { useCallback, useEffect, useRef, useState } from 'react'
import type { LaidOut } from './layout'

const ZOOM_MIN = 0.3
const ZOOM_MAX = 2.2
const PAD = 96

export interface PathController {
  panX: number
  panY: number
  zoom: number
  transform: string
  cw: number
  ch: number
  canvasRef: React.RefObject<HTMLDivElement | null>
  onMouseDown: (e: React.MouseEvent<HTMLDivElement>) => void
  fitView: () => void
  panTo: (worldX: number, worldY: number) => void
}

export function usePathController(
  layout: LaidOut | null,
  onEmptyClick?: () => void,
): PathController {
  // The hook owns this ref and it is attached DIRECTLY to the canvas host div in
  // PathView (no hand-merged callback ref), so canvasRef.current reliably holds
  // the DOM node across re-renders.
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const [panX, setPanX] = useState(40)
  const [panY, setPanY] = useState(40)
  const [zoom, setZoom] = useState(0.62)
  const [cw, setCw] = useState(0)
  const [ch, setCh] = useState(0)

  // Keep a ref to current pan/zoom so native event handlers can read without
  // capturing stale closure values.
  const stateRef = useRef({ panX, panY, zoom })
  useEffect(() => { stateRef.current = { panX, panY, zoom } }, [panX, panY, zoom])

  // Keep a stable ref to the empty-click callback so the mousedown handler does
  // not need to re-bind when the parent passes a new function identity.
  const onEmptyClickRef = useRef(onEmptyClick)
  useEffect(() => { onEmptyClickRef.current = onEmptyClick }, [onEmptyClick])

  // Keep a ref to the current layout so fitView / the native wheel
  // listener can read world dimensions without being recreated each render.
  // This keeps fitView a STABLE function: a previous bug put `layout` in
  // fitView's deps (and fitView in the fit-effect's deps), so an unstable
  // `layout` object identity re-ran fitView on every pan/zoom render and
  // clobbered the transform back to the fit value (net-zero pan/zoom).
  const layoutRef = useRef(layout)
  useEffect(() => { layoutRef.current = layout }, [layout])

  const fitView = useCallback(() => {
    const el = canvasRef.current
    const lo = layoutRef.current
    if (!el || !lo) return
    const cw = el.clientWidth
    const ch = el.clientHeight
    const { worldW, worldH } = lo
    const z = Math.max(ZOOM_MIN, Math.min(1.1, Math.min(cw / (worldW + PAD * 2), ch / (worldH + PAD * 2))))
    setPanX((cw - worldW * z) / 2)
    setPanY((ch - worldH * z) / 2)
    setZoom(z)
    setCw(cw)
    setCh(ch)
  }, [])

  const layoutMounted = layout != null

  // Fit on mount and on every VIEW SWITCH. The dep is a content signature of the
  // current layout (node count + first node id + rounded world size), NOT the
  // worldW/worldH primitives alone: two different views can share the same world
  // size (e.g. exiting back to a cached `main`), and keying on size alone would
  // skip the re-fit and leave the new view at the old pan/zoom. fitKey changes
  // only when layout CONTENT changes, so pan/zoom setStates (layout unchanged) do
  // NOT re-trigger a fit — no clobber loop. fitView stays stable (reads dims from
  // layoutRef), so it is safe in the dep array.
  const fitKey = layout
    ? `${layout.nodes.length}:${layout.nodes[0]?.id ?? ''}:${Math.round(layout.worldW)}x${Math.round(layout.worldH)}`
    : ''
  useEffect(() => {
    if (!fitKey) return
    // rAF so the canvas element has been laid out and is measurable.
    const id = requestAnimationFrame(() => fitView())
    return () => cancelAnimationFrame(id)
  }, [fitKey, fitView])

  // Wheel zoom: attached as a NON-PASSIVE native listener via useEffect so
  // e.preventDefault() actually suppresses page scroll. React 19 attaches the
  // JSX onWheel prop as a passive listener, where preventDefault is a no-op.
  useEffect(() => {
    const el = canvasRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const mx = e.clientX - r.left
      const my = e.clientY - r.top
      const { panX, panY, zoom } = stateRef.current
      const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1
      const z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom * factor))
      const wx = (mx - panX) / zoom
      const wy = (my - panY) / zoom
      setPanX(mx - wx * z)
      setPanY(my - wy * z)
      setZoom(z)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
    // Bind once the host div is mounted (layout present); subsequent reads come
    // from stateRef, so we key on a stable boolean rather than the layout object
    // to avoid needless re-binding on every pan/zoom render.
  }, [layoutMounted])

  const onMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    // Attached to the full-canvas BACKGROUND layer (see PathView) — the floating overlay panels are
    // siblings of that layer, so this handler only fires for background/node presses, never panel
    // clicks. That's what keeps the drawer open when switching to the Code tab.
    const { panX: startPanX, panY: startPanY } = stateRef.current
    const startX = e.clientX
    const startY = e.clientY
    let moved = false

    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX
      const dy = ev.clientY - startY
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true
      setPanX(startPanX + dx)
      setPanY(startPanY + dy)
    }

    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      // A press that didn't move = click on empty canvas → clear selection.
      if (!moved) onEmptyClickRef.current?.()
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [])

  // Center the canvas on a world-space point (mirrors prototype onMinimapClick lines 833–838).
  const panTo = useCallback((worldX: number, worldY: number) => {
    const el = canvasRef.current
    const cwCur = el ? el.clientWidth : cw
    const chCur = el ? el.clientHeight : ch
    const { zoom } = stateRef.current
    setPanX(cwCur / 2 - worldX * zoom)
    setPanY(chCur / 2 - worldY * zoom)
  }, [cw, ch])

  const transform = `translate(${panX}px,${panY}px) scale(${zoom})`

  return { panX, panY, zoom, transform, cw, ch, canvasRef, onMouseDown, fitView, panTo }
}
