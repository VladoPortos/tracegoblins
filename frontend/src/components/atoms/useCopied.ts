import { useRef, useState } from 'react'

// Clipboard copy with a transient "copied" flag for button feedback.
export function useCopied(timeoutMs = 2000) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const copy = (text: string) => {
    // Optional chain + catch: clipboard is undefined in non-secure contexts
    // (plain-HTTP LAN) and writeText can reject on permission denial.
    void navigator.clipboard?.writeText(text).catch(() => {})
    setCopied(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setCopied(false), timeoutMs)
  }
  return { copied, copy }
}
