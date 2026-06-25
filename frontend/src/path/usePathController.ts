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
  zoomBy: (factor: number) => void
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

  // Keep a ref to the current layout so fitView / zoomBy / the native wheel
  // listener can read world dimensions without being recreated each render.
  // This keeps fitView a STABLE function: a previous bug put `layout` in
  // fitView's deps (and fitView in the fit-effect's deps), so an unstable
  // `layout` object identity re-ran fitView on every pan/zoom render and
  // clobbered the transform back to the fit value.
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

  // Fit ONLY on mount and when the world SIZE genuinely changes. Depends on the
  // primitive worldW/worldH numbers (NOT the layout object identity, and NOT the
  // fitView function), so pan/zoom setStates do not re-trigger a fit.
  const worldW = layout?.worldW
  const worldH = layout?.worldH
  useEffect(() => {
    if (worldW == null || worldH == null) return
    // rAF so the canvas element has been laid out and is measurable.
    const id = requestAnimationFrame(() => fitView())
    return () => cancelAnimationFrame(id)
  }, [worldW, worldH, fitView])

  const zoomBy = useCallback((factor: number) => {
    const el = canvasRef.current
    const { panX, panY, zoom } = stateRef.current
    const cwCur = el ? el.clientWidth : cw
    const chCur = el ? el.clientHeight : ch
    const mx = cwCur / 2
    const my = chCur / 2
    const z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom * factor))
    const wx = (mx - panX) / zoom
    const wy = (my - panY) / zoom
    setPanX(mx - wx * z)
    setPanY(my - wy * z)
    setZoom(z)
  }, [cw, ch])

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
  }, [layout != null])

  const onMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
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

  const transform = `translate(${panX}px,${panY}px) scale(${zoom})`

  return { panX, panY, zoom, transform, cw, ch, canvasRef, onMouseDown, fitView, zoomBy }
}
