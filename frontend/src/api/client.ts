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
// Shows the server detail when it is a plain string, otherwise the caller's fallback.
export function errorMessage(e: unknown, fallback = 'Something went wrong.'): string {
  if (typeof e === 'string' && e) return e
  if (e instanceof ApiError) return typeof e.detail === 'string' && e.detail ? e.detail : fallback
  if (e instanceof Error && e.message) return e.message
  return fallback
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

// CSRF double-submit names. These MUST match the backend constants (app/core/config.py
// csrf_cookie_name / csrf_header_name), which are intentionally NOT env-overridable precisely
// because this built-in SPA hard-codes them and has no channel to learn an overridden name.
const CSRF_COOKIE = 'csrf_token'
const CSRF_HEADER = 'X-CSRF-Token'

export async function apiFetch<T>(path: string, init: RequestInit & { method?: string } = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (init.body != null && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (MUTATING.has(method)) {
    const csrf = readCookie(CSRF_COOKIE)
    if (csrf) headers.set(CSRF_HEADER, csrf)
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
export interface InviteCreated { link: string; expires_at: string }
export interface InviteInfo { email: string; valid: boolean }

export interface HostRecap {
  host: string; ok: number; changed: number; unreachable: number
  failed: number; skipped: number
}
export interface RunCounts { ok: number; changed: number; unreachable: number; failed: number; skipped: number }
export interface RunCard {
  id: string; job_id: string | null; template_name: string | null
  status: string; log_time: string | null
  launched_at?: string | null
  host_count: number; task_count: number
  counts: RunCounts; recap: HostRecap[]; created_at: string
  team_id: string | null; team_name: string | null
  controller_id?: string | null; controller_name?: string | null
  awx_organization_name?: string | null
  awx_launch_type?: string | null
  elapsed?: number | null
  scm_revision?: string | null
}
export interface RunDetail extends RunCard { owner_user_id: string | null }
export interface TaskLean {
  seq: number; play_name: string; role: string | null; name: string
  status: string; hosts: Record<string, string>; items_count: number
  line_no: number | null
  duration_s: number | null  // job_events durations; null for stdout runs
}
export interface TaskFull extends TaskLean { output: string | null; error: string | null; included_path: string | null }
export interface RunListResponse { items: RunCard[]; total: number }

// Multipart upload: do NOT set Content-Type (browser adds the boundary); reuse CSRF + credentials.
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const headers = new Headers()
  const csrf = readCookie(CSRF_COOKIE)
  if (csrf) headers.set(CSRF_HEADER, csrf)
  const res = await fetch('/api' + path, { method: 'POST', body: form, headers, credentials: 'include' })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data = parseBody(text)
  if (!res.ok) throwApiError(res.status, data, text)
  return data as T
}
