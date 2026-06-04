import { useCallback, useState } from 'react'

const KEY = 'tg.drawerWidth'
const MIN = 320
const MAX = 720
const DEFAULT = 420

export function useDrawerWidth() {
  const [width, setWidth] = useState<number>(() => {
    const raw = Number(localStorage.getItem(KEY))
    return raw >= MIN && raw <= MAX ? raw : DEFAULT
  })
  const set = useCallback((w: number) => {
    const clamped = Math.max(MIN, Math.min(MAX, w))
    setWidth(clamped)
    localStorage.setItem(KEY, String(clamped))
  }, [])
  return { width, set, MIN, MAX }
}
