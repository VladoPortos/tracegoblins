import { useMemo, useState } from 'react'
import { Modal } from '../components/atoms/Modal'
import { Glyph } from '../components/atoms/Glyph'
import { Avatar } from '../components/atoms/Avatar'
import { PersonRow } from '../components/atoms/PersonRow'
import { useCopied } from '../components/atoms/useCopied'
import { ApiError, errorMessage, type TeamBrief } from '../api/client'
import { useUserSearch } from '../api/users'
import { useRunShares, useCreateShare, useDeleteShare, type Share, type ShareCreate } from '../api/shares'

function ShareRow({ runId, share }: { runId: string; share: Share }) {
  const del = useDeleteShare(runId)
  const label = share.user ? share.user.display_name : (share.team?.name ?? 'Unknown')
  const sub = share.user ? share.user.email : 'Team'
  return (
    <div className="row gap2" style={{ padding: '7px 8px', border: '1px solid var(--border)', borderRadius: 'var(--r-md)' }}>
      {share.user ? <Avatar name={label} size="sm" /> : <span className="avatar sm" style={{ background: 'var(--accent)' }}><Glyph name="users" size={14} /></span>}
      <div className="col" style={{ gap: 0, minWidth: 0 }}>
        <span className="truncate" style={{ fontSize: 12.5, fontWeight: 600 }}>{label}</span>
        <span className="dim truncate" style={{ fontSize: 11 }}>{sub}</span>
      </div>
      <div className="grow" />
      <button className="btn icon sm btn-ghost" aria-label={`Revoke share with ${label}`} onClick={() => del.mutate(share.id)}><Glyph name="trash" size={14} /></button>
    </div>
  )
}

// One option in the combined "Add people or teams" autocomplete.
type Candidate =
  | { kind: 'user'; id: string; label: string; sub: string }
  | { kind: 'team'; id: string; label: string; sub: string }

export function ShareModal({ open, onOpenChange, runId, teams }: { open: boolean; onOpenChange: (o: boolean) => void; runId: string; teams: TeamBrief[] }) {
  const shares = useRunShares(runId)
  const create = useCreateShare(runId)
  const [q, setQ] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { copied, copy } = useCopied()
  // PEOPLE from the directory (NOT visibility-gated) so the FIRST share is possible.
  const people = useUserSearch(q)

  // Merge directory users + name-matching teams into ONE option list.
  const candidates: Candidate[] = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const teamMatches: Candidate[] = teams
      .filter((t) => needle.length > 0 && t.name.toLowerCase().includes(needle))
      .map((t) => ({ kind: 'team', id: t.id, label: t.name, sub: 'Team' }))
    const userMatches: Candidate[] = (people.data ?? []).map((u) => ({
      kind: 'user', id: u.id, label: u.display_name, sub: u.email,
    }))
    return [...userMatches, ...teamMatches].slice(0, 8)
  }, [q, teams, people.data])

  const add = (c: Candidate) => {
    setError(null)
    const body: ShareCreate = c.kind === 'user' ? { user_id: c.id } : { team_id: c.id }
    setQ('')
    create.mutate(body, {
      onError: (e) => setError(
        e instanceof ApiError && e.status === 409
          ? `Already shared with that ${c.kind === 'user' ? 'person' : 'team'}.`
          : errorMessage(e, 'Could not share.'),
      ),
    })
  }
  const copyLink = () => copy(window.location.origin + '/runs/' + runId)

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Share this run" width={520}>
      {error && <div className="tag tag-needs-fix" role="alert" style={{ marginBottom: 12 }}>{error}</div>}
      <div className="col" style={{ gap: 8 }}>
        <input className="input" aria-label="Add people or teams"
          placeholder="Add people or teams — search by name, email, or team…"
          value={q} onChange={(e) => setQ(e.target.value)} />
        {q.trim() && (
          <div className="col" role="listbox" aria-label="Share suggestions" style={{ gap: 4 }}>
            {candidates.map((c) => (
              <button key={`${c.kind}:${c.id}`} type="button" role="option" aria-selected={false}
                className="btn btn-ghost sm" style={{ width: '100%', justifyContent: 'flex-start', gap: 8 }}
                onClick={() => add(c)}>
                <PersonRow
                  name={c.label}
                  sub={c.sub}
                  avatar={c.kind === 'team'
                    ? <span className="avatar sm" style={{ background: 'var(--accent)' }}><Glyph name="users" size={14} /></span>
                    : undefined}
                />
                <span className="grow" /><Glyph name="plus" size={14} />
              </button>
            ))}
            {candidates.length === 0 && <span className="dim" style={{ fontSize: 12, padding: '4px 6px' }}>No matching people or teams.</span>}
          </div>
        )}
      </div>

      <div className="hr" style={{ margin: '16px 0 12px' }} />
      <div className="row gap2" style={{ marginBottom: 8 }}>
        <span className="eyebrow">Shared with</span>
        <span className="chip mono" style={{ fontSize: 10.5 }}>{shares.data?.length ?? 0}</span>
        <div className="grow" />
        <button className="btn sm btn-ghost" onClick={copyLink}><Glyph name="copy" size={13} />{copied ? 'Link copied' : 'Copy link'}</button>
      </div>
      <div className="col" style={{ gap: 6 }}>
        {(shares.data ?? []).map((s) => <ShareRow key={s.id} runId={runId} share={s} />)}
        {(shares.data?.length ?? 0) === 0 && <span className="dim" style={{ fontSize: 12 }}>Not shared with anyone yet.</span>}
      </div>

      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
        <button className="btn" onClick={() => onOpenChange(false)}>Close</button>
      </div>
    </Modal>
  )
}
