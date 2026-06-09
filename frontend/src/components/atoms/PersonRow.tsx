import type { ReactNode } from 'react'
import { Avatar } from './Avatar'

// Avatar + name/sub-line row used by people pickers (mention autocomplete, share
// suggestions). Picker logic stays in the parents — this is the row markup only.
// `avatar` overrides the default <Avatar> (e.g. the team glyph in ShareModal).
export function PersonRow({ name, sub, initials, avatarColor, avatar }: {
  name: string
  sub: string
  initials?: string | null
  avatarColor?: string | null
  avatar?: ReactNode
}) {
  return (
    <>
      {avatar ?? <Avatar name={name} color={avatarColor} initials={initials} size="sm" />}
      <span className="col" style={{ gap: 0, alignItems: 'flex-start', minWidth: 0 }}>
        <span className="truncate" style={{ fontSize: 12.5, fontWeight: 600 }}>{name}</span>
        <span className="dim truncate" style={{ fontSize: 11 }}>{sub}</span>
      </span>
    </>
  )
}
