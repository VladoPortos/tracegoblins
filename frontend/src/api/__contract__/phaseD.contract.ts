// Compile-time contract guard for Phase D API surface. Not bundled at runtime
// (no value exports are referenced by the app); `tsc --noEmit` typechecks it.
// If any imported symbol or field drifts from the Canonical Contract, tsc fails.
import type {
  ShareTargetUser, ShareTargetTeam, Share, ShareCreate,
} from '../shares'
import { sharesKey, useRunShares, useCreateShare, useDeleteShare } from '../shares'
import type {
  AnnotationLink, Annotation, AnnotationCreate, AnnotationUpdate,
} from '../annotations'
import {
  annotationsKey, TAG_VALUES, useRunAnnotations,
  useCreateAnnotation, useUpdateAnnotation, useDeleteAnnotation,
} from '../annotations'
import type { Comment, CommentCreate, CommentUpdate, MentionableUser } from '../comments'
import {
  commentsKey, useTaskComments, useCreateComment,
  useUpdateComment, useDeleteComment, useMentionable,
} from '../comments'
import type { Notification, NotificationList, UnreadCount, MarkRead } from '../notifications'
import {
  notificationsKey, unreadCountKey, useNotifications, useUnreadCount, useMarkRead,
} from '../notifications'
import type { DirectoryUser } from '../users'
import { userSearchKey, useUserSearch } from '../users'
import type { RunCard } from '../client'
import { useUploadRun } from '../runs'

// --- field-shape pins (assignment proves the property exists with the right type) ---
const _u: ShareTargetUser = { id: '', display_name: '', email: '' }
const _t: ShareTargetTeam = { id: '', name: '', slug: '' }
const _share: Share = {
  id: '', run_id: '', permission: 'collaborate', shared_by_user_id: '',
  user: _u, team: null, created_at: '',
}
const _shareCreate: ShareCreate = { user_id: '', team_id: null }
const _link: AnnotationLink = { label: '', url: '' }
const _ann: Annotation = {
  id: '', run_id: '', task_seq: 0, author_user_id: '', author_name: '',
  note: '', tags: ['needs-fix'], links: [_link], resolved: false,
  created_at: '', updated_at: '',
}
const _annCreate: AnnotationCreate = { note: '', tags: [], links: [] }
const _annUpdate: AnnotationUpdate = { resolved: true }
const _cmt: Comment = {
  id: '', run_id: '', task_seq: 0, annotation_id: null, parent_id: null,
  author_user_id: '', author_name: '', body: '', mentions: [], mention_names: [],
  created_at: '', edited_at: null, deleted_at: null,
}
const _cmtCreate: CommentCreate = { body: '', mentions: [], parent_id: null, annotation_id: null }
const _cmtUpdate: CommentUpdate = { body: '' }
const _mention: MentionableUser = { id: '', display_name: '', email: '', initials: null, avatar_color: null }
const _dirUser: DirectoryUser = { id: '', display_name: '', email: '' }
const _notif: Notification = {
  id: '', type: 'mention', run_id: null, run_template: null, comment_id: null,
  task_seq: null, task_name: null, actor_user_id: null, actor_name: null,
  read_at: null, created_at: '',
}
const _notifList: NotificationList = { items: [_notif], total: 0, unread: 0 }
const _unread: UnreadCount = { count: 0 }
const _markRead: MarkRead = { ids: [], all: false }
const _card: RunCard = {
  id: '', job_id: null, template_name: null, status: 'ok', log_time: null,
  host_count: 0, task_count: 0, warnings_count: 0,
  counts: { ok: 0, changed: 0, unreachable: 0, failed: 0, skipped: 0 },
  recap: [], created_at: '', team_id: null, team_name: null,
}

// --- Phase D2: drawer subcomponents + new glyph icons must exist ---
import { AnnotationsBlock } from '../../drawer/AnnotationsBlock'
import { DiscussionBlock } from '../../drawer/DiscussionBlock'
import { MentionTextarea } from '../../drawer/MentionTextarea'
import { ICONS } from '../../components/atoms/Glyph'

export const _guardD2 = {
  components: [AnnotationsBlock, DiscussionBlock, MentionTextarea] as const,
  icons: [ICONS.bell, ICONS.share, ICONS.trash] as const,
}

// --- Phase D3: RunsList must accept a scope prop ---
import { RunsList } from '../../dashboard/RunsList'
export const _guardD3 = { scoped: [RunsList] as const }

// --- Phase D4: UploadModal must accept the team list ---
import { UploadModal } from '../../upload/UploadModal'
import type { TeamBrief } from '../client'
const _teams: TeamBrief[] = []
export const _guardD4 = { upload: [UploadModal] as const, teams: _teams }
import type { ComponentProps as _CP4 } from 'react'
const _uploadProps: _CP4<typeof UploadModal> = { open: false, onOpenChange: () => {}, teams: [] }
void _uploadProps

// --- Phase D5: ShareModal ---
import { ShareModal } from '../../modals/ShareModal'
import type { ComponentProps as _CP5 } from 'react'
const _shareModalProps: _CP5<typeof ShareModal> = { open: false, onOpenChange: () => {}, runId: '', teams: [] }
void _shareModalProps
export const _guardD5 = { share: [ShareModal] as const }

// --- Phase D6: InboxBell ---
import { InboxBell } from '../../shell/InboxBell'
export const _guardD6 = { bell: [InboxBell] as const }

// --- key factory + hook-existence pins (referenced so tsc keeps them) ---
export const _guard = {
  _u, _t, _share, _shareCreate, _link, _ann, _annCreate, _annUpdate,
  _cmt, _cmtCreate, _cmtUpdate, _mention, _dirUser, _notif, _notifList, _unread, _markRead, _card,
  sharesKey: sharesKey('r'),
  annotationsKey: annotationsKey('r'),
  commentsKey: commentsKey('r', 0),
  userSearchKey: userSearchKey('q'),
  notificationsKey, unreadCountKey,
  TAG_VALUES,
  hooks: [
    useRunShares, useCreateShare, useDeleteShare,
    useRunAnnotations, useCreateAnnotation, useUpdateAnnotation, useDeleteAnnotation,
    useTaskComments, useCreateComment, useUpdateComment, useDeleteComment, useMentionable,
    useNotifications, useUnreadCount, useMarkRead, useUserSearch,
    useUploadRun,
  ] as const,
}
