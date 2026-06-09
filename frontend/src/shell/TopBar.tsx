import { useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Glyph } from '../components/atoms/Glyph'
import { Avatar } from '../components/atoms/Avatar'
import { useTheme } from './ThemeProvider'
import { useLogout } from '../api/queries'
import type { Me } from '../api/client'
import { InboxBell } from './InboxBell'

export function TopBar({ me }: { me: Me }) {
  const nav = useNavigate()
  const loc = useLocation()
  const { theme, setTheme } = useTheme()
  const logout = useLogout()
  const [open, setOpen] = useState(false)

  const navStyle = (active: boolean) =>
    active ? { background: 'var(--surface-2)', border: '1px solid var(--border)' } : { color: 'var(--text-2)' }

  const navItem = (to: string, label: string, icon: string, active: boolean) => (
    <button key={to} onClick={() => nav(to)} className={'btn sm' + (active ? '' : ' btn-ghost')} style={navStyle(active)}>
      <Glyph name={icon} size={15} />{label}
    </button>
  )

  // Real anchor (role=link) so it is reachable as a link and middle-clickable.
  const navLink = (to: string, label: string, icon: string, active: boolean) => (
    <Link key={to} to={to} className={'btn sm' + (active ? '' : ' btn-ghost')} style={{ ...navStyle(active), textDecoration: 'none' }}>
      <Glyph name={icon} size={15} />{label}
    </Link>
  )

  return (
    <div className="row gap3" style={{ height: 56, flex: 'none', padding: '0 18px', borderBottom: '1px solid var(--border)', background: 'var(--surface)', position: 'relative', zIndex: 30 }}>
      <button className="row gap2" onClick={() => nav('/')} style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 0 }}>
        <span style={{ color: 'var(--accent)' }}><Glyph name="logo" size={22} /></span>
        <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: '-.01em', color: 'var(--text)' }}>Tracegoblins</span>
        <span className="chip" style={{ fontSize: 10.5 }}>M1</span>
      </button>
      <div className="row gap1" style={{ marginLeft: 8 }}>
        {navItem('/', 'Logs', 'inbox', loc.pathname === '/')}
        {navLink('/analytics', 'Analytics', 'chart', loc.pathname.startsWith('/analytics'))}
        {navLink('/kb', 'Knowledge base', 'sparkle', loc.pathname.startsWith('/kb'))}
        {me.role === 'admin' && navItem('/admin/users', 'Admin', 'users', loc.pathname.startsWith('/admin'))}
      </div>
      <div className="grow" />
      <button className="btn icon btn-ghost" aria-label="Toggle theme" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
        <Glyph name={theme === 'dark' ? 'sun' : 'moon'} size={17} />
      </button>
      <InboxBell />
      <DropdownMenu.Root open={open} onOpenChange={setOpen}>
        <DropdownMenu.Trigger asChild>
          <button aria-label="Account menu" style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 2, borderRadius: '50%' }}>
            <Avatar name={me.display_name} color={me.avatar_color} initials={me.initials} />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content align="end" sideOffset={6} className="card" style={{ minWidth: 208, padding: 6, boxShadow: 'var(--shadow-2)', zIndex: 40 }}>
            <div className="col" style={{ gap: 1, padding: '6px 8px 8px' }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{me.display_name}</span>
              <span className="dim" style={{ fontSize: 11.5 }}>{me.email}</span>
            </div>
            <div className="hr" style={{ margin: '2px 0 4px' }} />
            <DropdownMenu.Item asChild>
              <button className="btn btn-ghost sm" style={{ width: '100%', justifyContent: 'flex-start' }} onClick={() => nav('/settings')}>
                <Glyph name="settings" size={15} />Settings
              </button>
            </DropdownMenu.Item>
            <DropdownMenu.Item asChild>
              <button className="btn btn-ghost sm" style={{ width: '100%', justifyContent: 'flex-start' }} onClick={() => logout.mutate(undefined, { onSettled: () => nav('/login') })}>
                <Glyph name="logout" size={15} />Sign out
              </button>
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  )
}
