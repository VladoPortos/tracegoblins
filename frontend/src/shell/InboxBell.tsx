import { useState } from 'react'
import { useNavigate } from 'react-router'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Glyph } from '../components/atoms/Glyph'
import { EmptyState } from '../components/atoms/EmptyState'
import { shortTime } from '../components/atoms/format'
import { useNotifications, useUnreadCount, useMarkRead, type Notification } from '../api/notifications'

function describe(n: Notification): string {
  const who = n.actor_name ?? 'Someone'
  const where = n.run_template ?? 'a run'
  if (n.type === 'mention') {
    const task = n.task_name ? `"${n.task_name}"` : 'a task'
    return `${who} mentioned you in a comment on ${task} in ${where}`
  }
  return `${who} shared ${where} with you`
}

export function InboxBell() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const unread = useUnreadCount()
  const list = useNotifications({ limit: 30 })
  const markRead = useMarkRead()
  const count = unread.data?.count ?? 0
  const items = list.data?.items ?? []

  const openItem = (n: Notification) => {
    setOpen(false)
    if (n.read_at == null) markRead.mutate({ ids: [n.id] })
    if (n.run_id) {
      const q = n.task_seq != null ? `?task=${n.task_seq}` : ''
      nav(`/runs/${n.run_id}${q}`)
    }
  }

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button className="btn icon btn-ghost" aria-label="Notifications" style={{ position: 'relative' }}>
          <Glyph name="bell" size={17} />
          {count > 0 && (
            <span data-testid="unread-badge" aria-label={`${count} unread`} style={{ position: 'absolute', top: 2, right: 2, minWidth: 15, height: 15, padding: '0 3px', borderRadius: 8, background: 'var(--unreachable)', color: '#fff', fontSize: 9.5, fontWeight: 700, display: 'grid', placeItems: 'center', lineHeight: 1 }}>
              {count > 9 ? '9+' : count}
            </span>
          )}
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className="card" style={{ width: 340, padding: 0, boxShadow: 'var(--shadow-2)', zIndex: 40, overflow: 'hidden' }}>
          <div className="row gap2" style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
            <span className="h3" style={{ fontSize: 13 }}>Notifications</span>
            <div className="grow" />
            {count > 0 && <button className="btn sm btn-ghost" onClick={(e) => { e.preventDefault(); markRead.mutate({ all: true }) }}><Glyph name="check" size={13} />Mark all read</button>}
          </div>
          <div className="scroll" style={{ maxHeight: 360 }}>
            {items.length === 0
              ? <EmptyState icon="bell" title="You're all caught up" sub="Mentions and shares will show up here." />
              : items.map((n) => (
                  <DropdownMenu.Item key={n.id} asChild>
                    <button className="row gap2" onClick={() => openItem(n)}
                      style={{ width: '100%', textAlign: 'left', padding: '10px 12px', border: 'none', borderBottom: '1px solid var(--border)', background: n.read_at == null ? 'var(--surface-2)' : 'transparent', cursor: 'pointer', alignItems: 'flex-start' }}>
                      <span style={{ color: 'var(--accent)', marginTop: 1 }}><Glyph name={n.type === 'mention' ? 'inbox' : 'share'} size={15} /></span>
                      <span className="col" style={{ gap: 2, minWidth: 0 }}>
                        <span style={{ fontSize: 12.5, color: 'var(--text)', whiteSpace: 'normal', wordBreak: 'break-word' }}>{describe(n)}</span>
                        <span className="dim mono" style={{ fontSize: 10.5 }}>{shortTime(n.created_at)}</span>
                      </span>
                      {n.read_at == null && <span aria-hidden="true" style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--accent)', flex: 'none', marginTop: 4 }} />}
                    </button>
                  </DropdownMenu.Item>
                ))}
          </div>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
