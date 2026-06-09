import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark'

export const ACCENT_HUE: Record<string, number> = {
  indigo: 270, blue: 245, teal: 195, green: 150, amber: 70, rose: 18,
}

type ThemeState = {
  theme: Theme; setTheme: (t: Theme) => void
  accent: string; setAccent: (a: string) => void
}
const Ctx = createContext<ThemeState | null>(null)

function read<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem('tg:' + key); return v ? (JSON.parse(v) as T) : fallback } catch { return fallback }
}
function write(key: string, value: unknown) {
  try { localStorage.setItem('tg:' + key, JSON.stringify(value)) } catch { /* ignore */ }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => read('theme', 'light'))
  const [accent, setAccent] = useState<string>(() => read('accent', 'indigo'))

  useEffect(() => { document.documentElement.setAttribute('data-theme', theme); write('theme', theme) }, [theme])
  useEffect(() => { document.documentElement.style.setProperty('--accent-h', String(ACCENT_HUE[accent] ?? 270)); write('accent', accent) }, [accent])

  return <Ctx.Provider value={{ theme, setTheme, accent, setAccent }}>{children}</Ctx.Provider>
}

export function useTheme() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useTheme must be used within ThemeProvider')
  return v
}
