// Compile-time contract guard for Phase E API surface. Not bundled at runtime
// (no value exports are referenced by the app); `tsc --noEmit` typechecks it.
// If any imported symbol or field drifts from the Canonical Contract (§6), tsc fails.
import type {
  KbLink, KbStatus, KbSignatureOut, KbSuggest,
  KbDrawerSuggestion, KbPromote, KbSignatureUpdate,
} from '../kb'
import {
  kbKey, kbSignatureKey, taskKbKey,
  useKbSignatures, useTaskKbSuggestion, useKbSuggest,
  usePromoteKb, useUpdateKbSignature,
  useDeleteKbSignature, usePromoteKbGlobal,
} from '../kb'

// --- field-shape pins (assignment proves the property exists with the right type) ---
const _link: KbLink = { label: '', url: '' }
const _status: KbStatus = 'needs-fix'
const _sig: KbSignatureOut = {
  id: '', team_id: null, signature_key: '', title: '', status: 'known-issue',
  category: null, description: null, is_problem: null, where_it_lives: null,
  representative_text: '', links: [_link],
  occurrence_count: 0, created_at: '', updated_at: '',
}
const _suggest: KbSuggest = { signature_key: '', representative_text: '', category: null }
const _drawer: KbDrawerSuggestion = { signature: _sig, exact: true, score: 1 }
const _promote: KbPromote = {
  run_id: '', task_seq: 0, team_id: null, title: '', status: 'needs-fix',
  description: null, is_problem: null, where_it_lives: null, links: [_link],
}
const _update: KbSignatureUpdate = { title: '', status: 'resolved' }

export const _guardE1 = {
  _link, _status, _sig, _suggest, _drawer, _promote, _update,
  kbKey,
  kbSignatureKey: kbSignatureKey('id'),
  taskKbKey: taskKbKey('r', 0),
  hooks: [
    useKbSignatures, useTaskKbSuggestion, useKbSuggest,
    usePromoteKb, useUpdateKbSignature,
    useDeleteKbSignature, usePromoteKbGlobal,
  ] as const,
}

// --- E2: shared KB link renderer ---
import { KbLinkRow } from '../../components/atoms/KbLinkRow'
import type { ComponentProps as _CPlink } from 'react'
const _kbLinkRowProps: _CPlink<typeof KbLinkRow> = { link: { label: '', url: '' } }
void _kbLinkRowProps
export const _guardE2 = { row: [KbLinkRow] as const }

// --- E3: drawer "Known issue" card ---
import { KbSuggestion } from '../../drawer/KbSuggestion'
import type { ComponentProps as _CPsug } from 'react'
const _kbSuggestionProps: _CPsug<typeof KbSuggestion> = { runId: '', seq: 0, onPromote: () => {} }
void _kbSuggestionProps
export const _guardE3 = { card: [KbSuggestion] as const }

// --- E4: promote modal ---
import { PromoteKbModal } from '../../modals/PromoteKbModal'
import type { ComponentProps as _CPpromo } from 'react'
import type { TeamBrief } from '../client'
const _promoteTeams: TeamBrief[] = []
const _promoteModalProps: _CPpromo<typeof PromoteKbModal> = {
  open: false, onOpenChange: () => {}, runId: '', seq: 0, teams: _promoteTeams, isAdmin: false,
}
void _promoteModalProps
export const _guardE4 = { promote: [PromoteKbModal] as const, _promoteTeams }

// --- E5: TaskDrawer gains teams + isAdmin props (for the promote modal) ---
import { TaskDrawer } from '../../drawer/TaskDrawer'
import type { ComponentProps as _CPdrawer } from 'react'
import type { TaskLean } from '../client'
const _leanE5: TaskLean = {
  seq: 0, play_name: '', role: null, name: '', status: 'failed', hosts: {},
  items_count: 0, line_no: null, duration_s: null,
}
const _drawerProps: _CPdrawer<typeof TaskDrawer> = {
  runId: '', lean: _leanE5, width: '', onClose: () => {},
  runOwnerId: '', currentUserId: '', teams: [], isAdmin: false,
}
void _drawerProps
export const _guardE5 = { drawer: [TaskDrawer] as const }

// --- E6: KB browse page replaces the KbEmpty stub ---
import { KbBrowse } from '../../kb/KbBrowse'
export const _guardE6 = { browse: [KbBrowse] as const }
