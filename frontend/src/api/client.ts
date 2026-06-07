export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `API ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

// Human-readable message from an unknown thrown value (ApiError carries the server detail).
export function errorMessage(e: unknown): string {
  if (!e) return ''
  if (typeof e === 'string') return e
  if (e instanceof Error) return e.message
  return 'An error occurred.'
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return m ? decodeURIComponent(m[1]) : null
}

// Parse a response body without assuming it is JSON. A reverse proxy or the backend can return
// HTML/plain-text on 5xx/timeouts; JSON.parse on that would throw SyntaxError and mask the real
// status. Returns the parsed value, or the raw text when it isn't JSON.
function parseBody(text: string): unknown {
  if (!text) return undefined
  try { return JSON.parse(text) } catch { return text }
}

function throwApiError(status: number, data: unknown, fallbackText: string): never {
  const detail =
    data && typeof data === 'object' && 'detail' in data
      ? (data as { detail: unknown }).detail
      : (data ?? (fallbackText || null))
  const message = typeof detail === 'string' ? detail : undefined
  throw new ApiError(status, detail ?? null, message)
}

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export async function apiFetch<T>(path: string, init: RequestInit & { method?: string } = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (init.body != null && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (MUTATING.has(method)) {
    const csrf = readCookie('csrf_token')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  const res = await fetch('/api' + path, { ...init, method, headers, credentials: 'include' })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data = parseBody(text)
  if (!res.ok) throwApiError(res.status, data, text)
  return data as T
}

// Response shapes — mirror the backend Pydantic response_models (Canonical Contract).
export interface TeamBrief { id: string; name: string; slug: string; is_default: boolean }
export interface Me {
  id: string; email: string; display_name: string; role: 'admin' | 'user'
  initials: string | null; avatar_color: string | null; must_change_password: boolean
  totp_enabled: boolean; mfa_setup_required: boolean
  teams: TeamBrief[]
}
export interface SetupStatus { needs_setup: boolean }
export interface UserOut {
  id: string; email: string; display_name: string; role: string; is_active: boolean
  created_at: string; last_login_at: string | null; teams: TeamBrief[]
  initials?: string | null; avatar_color?: string | null
  totp_enabled: boolean
}
export interface TeamOut { id: string; name: string; slug: string; is_default: boolean; member_count: number }
export interface InviteCreated { invite_id: string; token: string; link: string; expires_at: string }
export interface InviteInfo { email: string; role: string; valid: boolean }

export interface HostRecap {
  host: string; ok: number; changed: number; unreachable: number
  failed: number; skipped: number; rescued: number; ignored: number
}
export interface RunCounts { ok: number; changed: number; unreachable: number; failed: number; skipped: number }
export interface RunCard {
  id: string; job_id: string | null; template_name: string | null
  status: string; log_time: string | null
  launched_at?: string | null
  host_count: number; task_count: number; warnings_count: number
  counts: RunCounts; recap: HostRecap[]; created_at: string
  team_id: string | null; team_name: string | null
  controller_id?: string | null; controller_name?: string | null
  awx_organization_id?: number | null; awx_organization_name?: string | null
  awx_launch_type?: string | null; awx_workflow_name?: string | null
  elapsed?: number | null
}
export interface RunDetail extends RunCard { source: string; owner_user_id: string | null }
export interface TaskLean {
  seq: number; play_name: string; role: string | null; name: string
  status: string; hosts: Record<string, string>; items_count: number
  line_no: number | null; has_output: boolean; has_error: boolean
  duration_s: number | null  // job_events durations; null for stdout runs
}
export interface TaskFull extends TaskLean { output: string | null; error: string | null; included_path: string | null }
export interface RunListResponse { items: RunCard[]; total: number }

// Multipart upload: do NOT set Content-Type (browser adds the boundary); reuse CSRF + credentials.
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const headers = new Headers()
  const csrf = readCookie('csrf_token')
  if (csrf) headers.set('X-CSRF-Token', csrf)
  const res = await fetch('/api' + path, { method: 'POST', body: form, headers, credentials: 'include' })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data = parseBody(text)
  if (!res.ok) throwApiError(res.status, data, text)
  return data as T
}
