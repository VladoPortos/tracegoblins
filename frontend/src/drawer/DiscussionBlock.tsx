import { useMemo, useState } from 'react'
import { Glyph } from '../components/atoms/Glyph'
import { Avatar } from '../components/atoms/Avatar'
import { MentionTextarea } from './MentionTextarea'
import { shortTime } from '../components/atoms/format'
import {
  useTaskComments, useCreateComment, useUpdateComment, useDeleteComment, type Comment,
} from '../api/comments'

function Composer({
  runId, seq, parentId, placeholder, autoFocus, onSent,
}: { runId: string; seq: number; parentId?: string | null; placeholder?: string; autoFocus?: boolean; onSent?: () => void }) {
  const create = useCreateComment(runId, seq)
  const [body, setBody] = useState('')
  const [mentions, setMentions] = useState<string[]>([])
  const addMention = (id: string) => setMentions((m) => (m.includes(id) ? m : [...m, id]))

  const send = () => {
    if (!body.trim()) return
    create.mutate(
      { body: body.trim(), mentions, parent_id: parentId ?? null },
      { onSuccess: () => { setBody(''); setMentions([]); onSent?.() } },
    )
  }
  const isReply = parentId != null
  return (
    <div className="col" style={{ gap: 8 }}>
      <MentionTextarea runId={runId} value={body} onChange={setBody} onPickMention={addMention}
        ariaLabel={isReply ? 'Reply' : 'Add a comment'}
        placeholder={placeholder ?? 'Write a comment… use @ to mention'} autoFocus={autoFocus} />
      <div className="row gap2" style={{ justifyContent: 'flex-end' }}>
        {onSent && <button type="button" className="btn sm btn-ghost" onClick={onSent}>Cancel</button>}
        <button type="button" className="btn sm btn-primary" disabled={create.isPending || !body.trim()} onClick={send}>
          <Glyph name="arrowR" size={13} />{isReply ? 'Post reply' : 'Post comment'}
        </button>
      </div>
    </div>
  )
}

function CommentRow({
  runId, seq, c, currentUserId, runOwnerId, onReply,
}: { runId: string; seq: number; c: Comment; currentUserId: string; runOwnerId: string; onReply: (id: string) => void }) {
  const update = useUpdateComment(runId, seq)
  const del = useDeleteComment(runId, seq)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(c.body ?? '')
  const [editMentions, setEditMentions] = useState<string[]>(c.mentions ?? [])
  const addEditMention = (id: string) => setEditMentions((m) => (m.includes(id) ? m : [...m, id]))
  const deleted = c.deleted_at != null
  const mine = c.author_user_id === currentUserId
  const canModerate = mine || runOwnerId === currentUserId

  if (deleted) {
    return (
      <div className="row gap2" style={{ padding: '8px 10px', fontSize: 12, color: 'var(--text-3)', fontStyle: 'italic' }}>
        <Glyph name="trash" size={12} />comment deleted
      </div>
    )
  }
  return (
    <div className="col" style={{ gap: 6, padding: 10, border: '1px solid var(--border)', borderRadius: 'var(--r-md)' }}>
      <div className="row gap2">
        <Avatar name={c.author_name} size="sm" />
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{c.author_name}</span>
        <span className="dim mono" style={{ fontSize: 10.5 }}>{shortTime(c.created_at)}{c.edited_at && ' · edited'}</span>
        <div className="grow" />
        {mine && !editing && <button className="btn icon sm btn-ghost" aria-label="Edit comment" onClick={() => { setEditing(true); setDraft(c.body ?? ''); setEditMentions(c.mentions ?? []) }}><Glyph name="settings" size={13} /></button>}
        {canModerate && <button className="btn icon sm btn-ghost" aria-label="Delete comment" onClick={() => { if (confirm('Delete this comment?')) del.mutate(c.id) }}><Glyph name="trash" size={13} /></button>}
      </div>
      {editing ? (
        <div className="col" style={{ gap: 8 }}>
          <MentionTextarea runId={runId} value={draft} onChange={setDraft} onPickMention={addEditMention}
            ariaLabel="Edit comment" placeholder="Edit your comment… use @ to mention" rows={3} />
          <div className="row gap2" style={{ justifyContent: 'flex-end' }}>
            <button className="btn sm btn-ghost" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn sm btn-primary" disabled={update.isPending || !draft.trim()} onClick={() => update.mutate({ cid: c.id, patch: { body: draft.trim(), mentions: editMentions } }, { onSuccess: () => setEditing(false) })}><Glyph name="check" size={13} />Save</button>
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 12.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-2)' }}>{c.body}</div>
      )}
      {!editing && c.parent_id == null && (
        <button className="btn sm btn-ghost" style={{ alignSelf: 'flex-start' }} onClick={() => onReply(c.id)}><Glyph name="arrowR" size={12} />Reply</button>
      )}
    </div>
  )
}

export function DiscussionBlock({
  runId, seq, currentUserId, runOwnerId,
}: { runId: string; seq: number; currentUserId: string; runOwnerId: string }) {
  const comments = useTaskComments(runId, seq)
  const [replyTo, setReplyTo] = useState<string | null>(null)
  const all = comments.data ?? []
  // Single visual level: roots are parent_id == null; everything else is a child of its parent.
  const roots = useMemo(() => all.filter((c) => c.parent_id == null), [all])
  const childrenOf = useMemo(() => {
    const m: Record<string, Comment[]> = {}
    for (const c of all) if (c.parent_id) (m[c.parent_id] ??= []).push(c)
    return m
  }, [all])
  const visibleCount = all.filter((c) => c.deleted_at == null).length

  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="row gap2">
        <span className="eyebrow">Discussion</span>
        <span className="chip mono" style={{ fontSize: 10.5 }}>{visibleCount}</span>
      </div>
      {roots.map((c) => (
        <div key={c.id} className="col" style={{ gap: 6 }}>
          <CommentRow runId={runId} seq={seq} c={c} currentUserId={currentUserId} runOwnerId={runOwnerId} onReply={setReplyTo} />
          {(childrenOf[c.id] ?? []).map((child) => (
            <div key={child.id} style={{ marginLeft: 22 }}>
              <CommentRow runId={runId} seq={seq} c={child} currentUserId={currentUserId} runOwnerId={runOwnerId} onReply={setReplyTo} />
            </div>
          ))}
          {replyTo === c.id && (
            <div style={{ marginLeft: 22 }}>
              <Composer runId={runId} seq={seq} parentId={c.id} placeholder="Write a reply…" autoFocus onSent={() => setReplyTo(null)} />
            </div>
          )}
        </div>
      ))}
      {roots.length === 0 && <span className="dim" style={{ fontSize: 12 }}>No comments yet — start the discussion.</span>}
      <div className="hr" />
      <Composer runId={runId} seq={seq} />
    </div>
  )
}
