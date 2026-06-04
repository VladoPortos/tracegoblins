import { useState } from 'react'
import { AdminLayout } from '../admin/AdminLayout'
import { Modal } from '../components/atoms/Modal'
import { Field } from '../components/atoms/Field'
import { Badge } from '../components/atoms/Badge'
import { Glyph } from '../components/atoms/Glyph'
import { EmptyState } from '../components/atoms/EmptyState'
import { LastSyncChip } from '../components/atoms/LastSyncChip'
import { SyncProgress } from '../components/atoms/SyncProgress'
import {
  useControllers, useCreateController, useUpdateController, useDeleteController,
  useTestConnection, useTestConnectionAdhoc, useSyncController,
} from '../api/controllers'
import type { Controller, ControllerCreate, ControllerUpdate, TeamAssignment } from '../api/controllers'
import { useAdminTeams } from '../api/queries'

// ─── Team assignment row editor ───────────────────────────────────────────────

function TeamAssignmentEditor({
  assignments,
  onChange,
}: {
  assignments: TeamAssignment[]
  onChange: (v: TeamAssignment[]) => void
}) {
  const teams = useAdminTeams()
  const teamList = teams.data ?? []

  function add() {
    onChange([...assignments, { team_id: '', awx_organization_id: null }])
  }
  function remove(i: number) {
    onChange(assignments.filter((_, idx) => idx !== i))
  }
  function setTeam(i: number, team_id: string) {
    onChange(assignments.map((a, idx) => idx === i ? { ...a, team_id } : a))
  }
  function setOrg(i: number, raw: string) {
    const v = raw.trim() === '' ? null : parseInt(raw, 10)
    onChange(assignments.map((a, idx) => idx === i ? { ...a, awx_organization_id: isNaN(v as number) ? null : v } : a))
  }

  return (
    <div className="col" style={{ gap: 8 }}>
      <label className="field-label">Team assignments</label>
      {assignments.map((a, i) => (
        <div key={i} className="row gap2" style={{ alignItems: 'center' }}>
          <select
            className="input"
            style={{ flex: 1 }}
            value={a.team_id}
            onChange={(e) => setTeam(i, e.target.value)}
            aria-label="Team"
          >
            <option value="">Select team…</option>
            {teamList.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <input
            className="input"
            style={{ width: 110 }}
            placeholder="AWX org ID (all)"
            value={a.awx_organization_id ?? ''}
            onChange={(e) => setOrg(i, e.target.value)}
            aria-label="AWX organization ID"
            type="number"
          />
          <button className="btn btn-ghost sm" onClick={() => remove(i)} aria-label="Remove assignment">
            <Glyph name="close" size={14} />
          </button>
        </div>
      ))}
      <button className="btn btn-ghost sm" onClick={add} style={{ alignSelf: 'flex-start' }}>
        <Glyph name="plus" size={14} /> Add team
      </button>
    </div>
  )
}

// ─── Status LED ───────────────────────────────────────────────────────────────

function Led({ state }: { state: 'idle' | 'testing' | 'ok' | 'err' }) {
  const color =
    state === 'ok' ? 'var(--ok)' :
    state === 'err' ? 'var(--unreachable)' :
    state === 'testing' ? 'var(--accent)' : 'var(--text-3)'
  return (
    <span
      aria-hidden
      style={{
        width: 9, height: 9, borderRadius: '50%', flex: 'none', background: color,
        boxShadow: `0 0 0 3px color-mix(in srgb, ${color} 22%, transparent)`,
        animation: state === 'testing' ? 'pulse 1s ease-in-out infinite' : undefined,
      }}
    />
  )
}

// ─── Status badge ──────────────────────────────────────────────────────────────

function ControllerStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    connected: 'ok',
    error: 'failed',
    unconfigured: 'skipped',
  }
  return <Badge status={map[status] ?? 'skipped'} withLabel={false} />
}

// ─── Add / Edit modal ─────────────────────────────────────────────────────────

type ModalState =
  | { mode: 'add' }
  | { mode: 'edit'; controller: Controller }

interface FormState {
  name: string
  base_url: string
  token: string
  verify_ssl: boolean
  sync_mode: 'manual' | 'auto'
  sync_interval_minutes: string
  team_assignments: TeamAssignment[]
}

function initForm(c?: Controller): FormState {
  return {
    name: c?.name ?? '',
    base_url: c?.base_url ?? '',
    token: '',
    verify_ssl: c?.verify_ssl ?? true,
    sync_mode: c?.sync_mode ?? 'manual',
    sync_interval_minutes: c?.sync_interval_minutes != null ? String(c.sync_interval_minutes) : '',
    // New controller: start with one empty assignment row so the Team picker is
    // visible immediately (a controller with no team assignment is useless — runs
    // would be invisible). Empty rows are filtered out on submit.
    team_assignments: c
      ? c.team_assignments.map((t) => ({ team_id: t.team_id, awx_organization_id: t.awx_organization_id }))
      : [{ team_id: '', awx_organization_id: null }],
  }
}

function ControllerModal({
  state,
  onClose,
}: {
  state: ModalState
  onClose: () => void
}) {
  const isEdit = state.mode === 'edit'
  const controller = isEdit ? state.controller : undefined

  const [form, setForm] = useState<FormState>(() => initForm(controller))
  const [testResult, setTestResult] = useState<{ ok: boolean; version: string | null; identity: string | null; error: string | null } | null>(null)
  const [testPending, setTestPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const createCtl = useCreateController()
  const updateCtl = useUpdateController(controller?.id ?? '')
  const testConn = useTestConnection(controller?.id ?? '')
  const testConnAdhoc = useTestConnectionAdhoc()

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => {
    setForm((prev) => ({ ...prev, [k]: v }))
    // A prior test result no longer reflects the edited form — clear the LED so a
    // green/red dot can't linger against changed URL/token/SSL values.
    if (k === 'base_url' || k === 'token' || k === 'verify_ssl') setTestResult(null)
  }

  async function handleTest() {
    setTestPending(true)
    setTestResult(null)
    try {
      // Edit: test the SAVED controller (id), optionally overriding fields the user changed.
      // Add: no controller exists yet, so test ad-hoc straight from the form values.
      const res = isEdit
        ? await testConn.mutateAsync({
            base_url: form.base_url || undefined,
            token: form.token || undefined,
            verify_ssl: form.verify_ssl,
          })
        : await testConnAdhoc.mutateAsync({
            base_url: form.base_url,
            token: form.token,
            verify_ssl: form.verify_ssl,
          })
      setTestResult(res)
    } catch (e) {
      setTestResult({ ok: false, version: null, identity: null, error: String(e) })
    } finally {
      setTestPending(false)
    }
  }

  async function handleSubmit() {
    setError(null)
    try {
      const interval = form.sync_interval_minutes.trim() !== '' ? parseInt(form.sync_interval_minutes, 10) : null
      // Drop blank rows the user left empty (e.g. an extra "Add team" they never filled);
      // an empty team_id would otherwise be a 422 from the API.
      const teamAssignments = form.team_assignments.filter((a) => a.team_id !== '')
      if (isEdit && controller) {
        const body: ControllerUpdate = {
          name: form.name || undefined,
          base_url: form.base_url || undefined,
          verify_ssl: form.verify_ssl,
          sync_mode: form.sync_mode,
          sync_interval_minutes: interval,
          team_assignments: teamAssignments,
        }
        if (form.token) body.token = form.token
        await updateCtl.mutateAsync(body)
      } else {
        const body: ControllerCreate = {
          name: form.name,
          base_url: form.base_url,
          token: form.token,
          verify_ssl: form.verify_ssl,
          sync_mode: form.sync_mode,
          sync_interval_minutes: interval,
          team_assignments: teamAssignments,
        }
        await createCtl.mutateAsync(body)
      }
      onClose()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    }
  }

  const isPending = createCtl.isPending || updateCtl.isPending

  return (
    <Modal
      open
      onOpenChange={(o) => { if (!o) onClose() }}
      title={isEdit ? `Edit "${controller!.name}"` : 'New controller'}
      width={520}
    >
      <div className="col" style={{ gap: 14 }}>
        <Field
          label="Name"
          placeholder="Production AWX"
          value={form.name}
          onChange={(e) => set('name', e.target.value)}
        />
        <Field
          label="Base URL"
          placeholder="https://awx.example.com"
          value={form.base_url}
          onChange={(e) => set('base_url', e.target.value)}
        />
        <Field
          label={isEdit ? 'Token (leave blank to keep existing)' : 'Token'}
          type="password"
          placeholder={isEdit ? (controller?.token_masked ?? '••••••••') : 'AWX personal access token'}
          value={form.token}
          onChange={(e) => set('token', e.target.value)}
          autoComplete="new-password"
        />

        {/* Test connection button + LED result */}
        <div className="col" style={{ gap: 6 }}>
          <div className="row gap2" style={{ alignItems: 'center' }}>
            <Led state={testPending ? 'testing' : testResult ? (testResult.ok ? 'ok' : 'err') : 'idle'} />
            <button
              className="btn btn-ghost sm"
              onClick={handleTest}
              disabled={testPending || (!isEdit && (!form.base_url || !form.token))}
              aria-label="Test connection"
            >
              <Glyph name={testPending ? 'spinner' : 'server'} size={14} />
              {testPending ? 'Testing…' : 'Test connection'}
            </button>
          </div>
          {testResult && (
            <div style={{ fontSize: 12.5, padding: '6px 10px', borderRadius: 6, background: testResult.ok ? 'var(--surface-ok, var(--surface-2))' : 'var(--surface-err, var(--surface-2))' }}>
              {testResult.ok
                ? <>Connected — AWX {testResult.version} · {testResult.identity}</>
                : <span style={{ color: 'var(--unreachable)' }}>{testResult.error ?? 'Connection failed'}</span>}
            </div>
          )}
        </div>

        {/* verify_ssl toggle */}
        <div className="row gap2" style={{ alignItems: 'center' }}>
          <input
            id="verify-ssl"
            type="checkbox"
            checked={form.verify_ssl}
            onChange={(e) => set('verify_ssl', e.target.checked)}
          />
          <label htmlFor="verify-ssl" style={{ fontSize: 13.5 }}>Verify SSL</label>
        </div>

        {/* Sync mode */}
        <div className="col" style={{ gap: 6 }}>
          <label className="field-label">Sync mode</label>
          <div className="row gap2">
            {(['manual', 'auto'] as const).map((m) => (
              <label key={m} className="row gap2" style={{ alignItems: 'center', fontSize: 13.5 }}>
                <input
                  type="radio"
                  name="sync-mode"
                  value={m}
                  checked={form.sync_mode === m}
                  onChange={() => set('sync_mode', m)}
                />
                {m === 'manual' ? 'Manual' : 'Auto'}
              </label>
            ))}
          </div>
          {form.sync_mode === 'auto' && (
            <Field
              label="Sync interval (minutes)"
              type="number"
              min={1}
              placeholder="60"
              value={form.sync_interval_minutes}
              onChange={(e) => set('sync_interval_minutes', e.target.value)}
            />
          )}
        </div>

        {/* Team assignments */}
        <TeamAssignmentEditor
          assignments={form.team_assignments}
          onChange={(v) => set('team_assignments', v)}
        />

        {error && (
          <div style={{ fontSize: 12.5, color: 'var(--unreachable)', padding: '6px 10px', borderRadius: 6, background: 'var(--surface-2)' }}>
            {error}
          </div>
        )}

        <div className="row gap2" style={{ justifyContent: 'flex-end', marginTop: 4 }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={isPending}>
            {isPending ? 'Saving…' : isEdit ? 'Save' : 'Add controller'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export function AwxControllers() {
  const controllers = useControllers()
  const deleteCtl = useDeleteController()
  const syncCtl = useSyncController()
  const [modal, setModal] = useState<ModalState | null>(null)
  const [syncError, setSyncError] = useState<Record<string, string>>({})

  const list = controllers.data ?? []

  async function handleSync(id: string) {
    setSyncError((prev) => { const n = { ...prev }; delete n[id]; return n })
    try {
      await syncCtl.mutateAsync(id)
    } catch (e) {
      setSyncError((prev) => ({ ...prev, [id]: e instanceof Error ? e.message : String(e) }))
    }
  }

  return (
    <AdminLayout>
      <div className="col" style={{ gap: 16 }}>
        <div className="row gap2" style={{ alignItems: 'center' }}>
          <div className="grow">
            <h2 className="h2" style={{ margin: 0 }}>AWX Controllers</h2>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>
              Connect Tracegoblins to one or more AWX controllers to import job runs.
            </div>
          </div>
          <button
            className="btn btn-primary sm"
            onClick={() => setModal({ mode: 'add' })}
            aria-label="Add controller"
          >
            <Glyph name="plus" size={14} /> New controller
          </button>
        </div>

        {controllers.isPending && (
          <div className="muted" style={{ padding: 16 }}>Loading…</div>
        )}

        {!controllers.isPending && list.length === 0 && (
          <div className="card">
            <EmptyState
              icon="server"
              title="No controllers yet"
              sub="Add an AWX controller to start syncing job runs."
              action={
                <button className="btn btn-primary" onClick={() => setModal({ mode: 'add' })} style={{ marginTop: 6 }}>
                  <Glyph name="plus" size={15} /> Add controller
                </button>
              }
            />
          </div>
        )}

        {list.map((c) => (
          <div key={c.id} className="card" style={{ padding: '14px 16px' }}>
            <div className="row gap2" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px 12px' }}>
              {/* Name + URL */}
              <div className="grow col" style={{ gap: 3, minWidth: 180 }}>
                <div className="row gap2" style={{ alignItems: 'center' }}>
                  <Glyph name="server" size={15} style={{ color: 'var(--accent)' }} />
                  <span className="h3" style={{ fontSize: 14 }}>{c.name}</span>
                  <ControllerStatusBadge status={c.status} />
                </div>
                <div className="mono muted" style={{ fontSize: 11.5 }}>{c.base_url}</div>
                {c.team_assignments.length > 0 && (
                  <div className="row gap1 wrap" style={{ marginTop: 2 }}>
                    {c.team_assignments.map((t, i) => (
                      <span key={i} className="chip" style={{ fontSize: 10.5 }}>
                        <Glyph name="users" size={11} />{t.team_name ?? t.team_id}
                        {t.awx_organization_id != null && <span className="mono dim" style={{ marginLeft: 2 }}>org:{t.awx_organization_id}</span>}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Last sync chip */}
              <div style={{ flexShrink: 0 }}>
                <LastSyncChip
                  status={c.last_sync_status}
                  at={c.last_sync_at}
                  error={c.last_sync_error}
                />
              </div>

              {/* Actions */}
              <div className="row gap1" style={{ flexShrink: 0 }}>
                <button
                  className="btn btn-ghost sm"
                  onClick={() => handleSync(c.id)}
                  disabled={syncCtl.isPending || c.last_sync_status === 'running'}
                  aria-label="Sync now"
                  title="Sync now"
                >
                  <Glyph name="spinner" size={14} />
                  Sync now
                </button>
                <button
                  className="btn btn-ghost sm"
                  onClick={() => setModal({ mode: 'edit', controller: c })}
                  aria-label={`Edit ${c.name}`}
                  title="Edit"
                >
                  <Glyph name="settings" size={14} />
                </button>
                <button
                  className="btn btn-ghost sm"
                  onClick={() => { if (confirm(`Delete "${c.name}"?`)) void deleteCtl.mutateAsync(c.id) }}
                  aria-label={`Delete ${c.name}`}
                  title="Delete"
                >
                  <Glyph name="trash" size={14} />
                </button>
              </div>

              {c.last_sync_status === 'running' && (
                <div style={{ flexBasis: '100%' }}>
                  <SyncProgress c={c} />
                </div>
              )}
            </div>

            {syncError[c.id] && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--unreachable)' }}>
                Sync error: {syncError[c.id]}
              </div>
            )}
          </div>
        ))}
      </div>

      {modal && (
        <ControllerModal state={modal} onClose={() => setModal(null)} />
      )}
    </AdminLayout>
  )
}
