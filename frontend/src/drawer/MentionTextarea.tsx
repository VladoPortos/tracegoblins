import { useMemo, useRef, useState } from 'react'
import { useMentionable } from '../api/comments'
import { PersonRow } from '../components/atoms/PersonRow'

// Detects "@token" immediately before the caret (no whitespace inside the token).
function activeMention(value: string, caret: number): { start: number; query: string } | null {
  const upto = value.slice(0, caret)
  const at = upto.lastIndexOf('@')
  if (at < 0) return null
  if (at > 0 && !/\s/.test(upto[at - 1])) return null // must be at start or after whitespace
  const token = upto.slice(at + 1)
  if (/\s/.test(token)) return null
  return { start: at, query: token }
}

export function MentionTextarea({
  runId, value, onChange, onPickMention, placeholder, ariaLabel, autoFocus, rows = 3,
}: {
  runId: string
  value: string
  onChange: (v: string) => void
  onPickMention: (id: string) => void
  placeholder?: string
  ariaLabel?: string
  autoFocus?: boolean
  rows?: number
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const [caret, setCaret] = useState(0)
  const [open, setOpen] = useState(false)
  const active = useMemo(() => (open ? activeMention(value, caret) : null), [open, value, caret])
  const q = active?.query ?? ''
  const mentionable = useMentionable(runId, q)
  const options = (mentionable.data ?? []).slice(0, 6)

  const sync = (el: HTMLTextAreaElement) => { setCaret(el.selectionStart ?? el.value.length) }

  const pick = (u: { id: string; display_name: string }) => {
    if (!active) return
    const before = value.slice(0, active.start)
    const after = value.slice(active.start + 1 + active.query.length)
    const inserted = `@${u.display_name} `
    onChange(before + inserted + after)
    onPickMention(u.id)
    setOpen(false)
    requestAnimationFrame(() => ref.current?.focus())
  }

  return (
    <div style={{ position: 'relative' }}>
      <textarea
        ref={ref}
        className="textarea"
        placeholder={placeholder}
        value={value}
        rows={rows}
        autoFocus={autoFocus}
        aria-label={ariaLabel ?? placeholder ?? 'Comment body'}
        onChange={(e) => { onChange(e.target.value); setOpen(true); sync(e.target) }}
        onClick={(e) => sync(e.currentTarget)}
        onKeyUp={(e) => sync(e.currentTarget)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        style={{ minHeight: 64, fontSize: 12.5 }}
      />
      {active && options.length > 0 && (
        <div className="card" role="listbox" aria-label="Mention suggestions"
          style={{ position: 'absolute', left: 6, right: 6, top: '100%', marginTop: 4, zIndex: 5, padding: 4, boxShadow: 'var(--shadow-2)', maxHeight: 220, overflow: 'auto' }}>
          {options.map((u) => (
            <button key={u.id} role="option" type="button" className="btn btn-ghost sm"
              style={{ width: '100%', justifyContent: 'flex-start', gap: 8 }}
              onMouseDown={(e) => { e.preventDefault(); pick(u) }}>
              <PersonRow name={u.display_name} sub={u.email} initials={u.initials} avatarColor={u.avatar_color} />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
