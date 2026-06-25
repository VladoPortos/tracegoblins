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
  onWheel: (e: React.WheelEvent<HTMLDivElement>) => void
  fitView: () => void
  zoomBy: (factor: number) => void
}

export function usePathController(layout: LaidOut | null): PathController {
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const [panX, setPanX] = useState(40)
  const [panY, setPanY] = useState(40)
  const [zoom, setZoom] = useState(0.62)
  const [cw, setCw] = useState(0)
  const [ch, setCh] = useState(0)

  // Keep a ref to current pan/zoom so event handlers can read without stale closure
  const stateRef = useRef({ panX, panY, zoom })
  useEffect(() => { stateRef.current = { panX, panY, zoom } }, [panX, panY, zoom])

  const fitView = useCallback(() => {
    const el = canvasRef.current
    if (!el || !layout) return
    const cw = el.clientWidth
    const ch = el.clientHeight
    const { worldW, worldH } = layout
    const z = Math.max(ZOOM_MIN, Math.min(1.1, Math.min(cw / (worldW + PAD * 2), ch / (worldH + PAD * 2))))
    setPanX((cw - worldW * z) / 2)
    setPanY((ch - worldH * z) / 2)
    setZoom(z)
    setCw(cw)
    setCh(ch)
  }, [layout])

  // Fit on mount and when layout world dimensions change
  useEffect(() => {
    if (!layout) return
    // Use rAF so the canvas element has been rendered and measured
    const id = requestAnimationFrame(() => fitView())
    return () => cancelAnimationFrame(id)
  }, [layout?.worldW, layout?.worldH, fitView])

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

  const onWheel = useCallback((e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault()
    const el = canvasRef.current
    if (!el) return
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
  }, [])

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
      // If not moved, this was a click on empty canvas — signal via custom event
      // PathView reads this to clear selection
      if (!moved) {
        const el = canvasRef.current
        if (el) el.dispatchEvent(new CustomEvent('canvas:emptyclick', { bubbles: true }))
      }
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [])

  const transform = `translate(${panX}px,${panY}px) scale(${zoom})`

  return { panX, panY, zoom, transform, cw, ch, canvasRef, onMouseDown, onWheel, fitView, zoomBy }
}
