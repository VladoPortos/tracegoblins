// Compile-time contract guard for Phase F. Not bundled at runtime; tsc --noEmit
// typechecks it. If any imported symbol or field drifts from the Canonical
// Contract (§9), tsc fails.
import type {
  TeamAssignment, ControllerTeamOut, Controller,
  ControllerCreate, ControllerUpdate, TestConnectionResult,
} from '../controllers'
import {
  controllersKey, useControllers, useCreateController, useUpdateController,
  useDeleteController, useTestConnection, useSyncController,
} from '../controllers'

const _assign: TeamAssignment = { team_id: '', awx_organization_id: null }
const _ctOut: ControllerTeamOut = { team_id: '', team_name: null, awx_organization_id: null }
const _ctrl: Controller = {
  id: '', name: '', base_url: '', verify_ssl: true,
  sync_mode: 'manual', sync_interval_minutes: null,
  status: 'unconfigured', last_sync_status: 'never',
  last_sync_at: null, last_sync_error: null,
  sync_total: null, sync_done: null, sync_current_job: null,
  token_masked: '', team_assignments: [_ctOut], created_at: '',
}
const _create: ControllerCreate = {
  name: '', base_url: '', token: '', verify_ssl: true,
  sync_mode: 'manual', sync_interval_minutes: null, team_assignments: [_assign],
}
const _update: ControllerUpdate = { name: '', team_assignments: [_assign] }
const _test: TestConnectionResult = { ok: true, version: null, identity: null, error: null }

export const _guardF1 = {
  _assign, _ctOut, _ctrl, _create, _update, _test,
  controllersKey,
  hooks: [
    useControllers, useCreateController, useUpdateController,
    useDeleteController, useTestConnection, useSyncController,
  ] as const,
}

// --- F2: facets hook + RunFilters + RunCard AWX fields ---
import type { FacetOrg, FacetController, RunFacets } from '../runFilters'
import { runFiltersKey, useRunFilters } from '../runFilters'
import type { RunFilters } from '../runs'
import type { RunCard } from '../client'

const _fOrg: FacetOrg = { id: 0, name: null }
const _fCtrl: FacetController = { id: '', name: null }
const _facets: RunFacets = {
  organizations: [_fOrg], templates: [], controllers: [_fCtrl],
  statuses: [], launch_types: [], users: [],
}
const _filters: RunFilters = {
  controller: '', organization: 0, template: '', awx_user: '',
  status: ['failed'], launch_type: 'manual',
  launched_after: '', launched_before: '', search: '',
}
const _cardAwx: RunCard = {
  id: '', job_id: null, template_name: null, status: 'ok', log_time: null,
  host_count: 0, task_count: 0,
  counts: { ok: 0, changed: 0, unreachable: 0, failed: 0, skipped: 0 },
  recap: [], created_at: '', team_id: null, team_name: null,
  controller_id: null, controller_name: null,
  awx_organization_name: null,
  awx_launch_type: null,
}

export const _guardF2 = {
  _fOrg, _fCtrl, _facets, _filters, _cardAwx,
  runFiltersKey: runFiltersKey('team'),
  hooks: [useRunFilters] as const,
}

// --- F3: server glyph + LastSyncChip atom ---
import { ICONS } from '../../components/atoms/Glyph'
import { LastSyncChip } from '../../components/atoms/LastSyncChip'
import type { ComponentProps as _CPchip } from 'react'
const _chipProps: _CPchip<typeof LastSyncChip> = { status: 'ok', at: null, error: null }
void _chipProps
export const _guardF3 = { icon: [ICONS.server] as const, chip: [LastSyncChip] as const }
