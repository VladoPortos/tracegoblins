import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiUpload } from './client'
import type { RunCard } from './client'

export interface ProjectListItem {
  id: string; name: string; controller_id: string; controller_name: string | null
  scm_type: string; scm_branch: string | null
  status: 'unlinked' | 'pending' | 'cloning' | 'cloned' | 'error'
  linked_run_count: number
}
export interface ProjectListResponse { items: ProjectListItem[]; total: number }

export interface Project {
  id: string; controller_id: string; controller_name: string | null
  awx_project_id: number; name: string; scm_type: string
  scm_url: string | null; scm_branch: string | null; scm_revision: string | null
  description: string | null; organization_id: number | null; organization_name: string | null
  status: ProjectListItem['status']
  effective_git_url: string | null; git_url_override: string | null
  git_auth_type: 'none' | 'token' | 'userpass' | null; git_username: string | null
  has_git_secret: boolean
  last_clone_at: string | null; last_clone_error: string | null; clone_size_bytes: number | null
  linked_run_count: number; created_at: string; updated_at: string
}
export interface ProjectGitIn {
  git_url_override?: string | null; auth_type: 'none' | 'token' | 'userpass'
  username?: string | null; secret?: string
}
export interface TreeEntry { name: string; type: 'blob' | 'tree'; size: number | null; mode: string }
export interface TreeResponse { ref: string; path: string; entries: TreeEntry[] }
export interface BlobResponse {
  ref: string; path: string; content: string | null; size: number; too_large: boolean; binary: boolean
}
export interface ProjectRunsResponse { items: RunCard[]; total: number }

export const projectsKey = ['projects'] as const
export const projectKey = (id: string) => ['projects', id] as const

export function useProjects(params: { controller?: string; q?: string } = {}) {
  const qs = new URLSearchParams()
  if (params.controller) qs.set('controller', params.controller)
  if (params.q) qs.set('q', params.q)
  const suffix = qs.toString() ? `?${qs}` : ''
  return useQuery<ProjectListResponse>({
    queryKey: [...projectsKey, params],
    queryFn: () => apiFetch<ProjectListResponse>(`/projects${suffix}`),
    // poll while any project is mid-clone so the status badge converges on its own
    refetchInterval: (query) =>
      (query.state.data?.items ?? []).some((p) => p.status === 'cloning' || p.status === 'pending') ? 1500 : false,
  })
}
export function useProject(id: string) {
  return useQuery<Project>({
    queryKey: projectKey(id),
    queryFn: () => apiFetch<Project>(`/projects/${id}`),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data && ['cloning', 'pending'].includes(query.state.data.status) ? 1500 : false,
  })
}
export function useProjectRuns(id: string) {
  return useQuery<ProjectRunsResponse>({
    queryKey: [...projectKey(id), 'runs'],
    queryFn: () => apiFetch<ProjectRunsResponse>(`/projects/${id}/runs`),
    enabled: !!id,
  })
}
export function useProjectTree(id: string, ref: string, path: string, enabled = true) {
  return useQuery<TreeResponse>({
    queryKey: [...projectKey(id), 'tree', ref, path],
    queryFn: () => apiFetch<TreeResponse>(`/projects/${id}/tree?ref=${encodeURIComponent(ref)}&path=${encodeURIComponent(path)}`),
    enabled: !!id && !!ref && enabled,
  })
}
export function fetchProjectBlob(id: string, ref: string, path: string) {
  return apiFetch<BlobResponse>(`/projects/${id}/blob?ref=${encodeURIComponent(ref)}&path=${encodeURIComponent(path)}`)
}
export function useSetProjectGit(id: string) {
  const qc = useQueryClient()
  return useMutation<Project, unknown, ProjectGitIn>({
    mutationFn: (body) => apiFetch<Project>(`/projects/${id}/git`, { method: 'PUT', body: JSON.stringify(body) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: projectKey(id) }); void qc.invalidateQueries({ queryKey: projectsKey }) },
  })
}
export function useCloneProject(id: string) {
  const qc = useQueryClient()
  return useMutation<{ status: string }, unknown, void>({
    mutationFn: () => apiFetch<{ status: string }>(`/projects/${id}/clone`, { method: 'POST' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: projectKey(id) }); void qc.invalidateQueries({ queryKey: projectsKey }) },
  })
}
export function useRefreshMirror(id: string) {
  const qc = useQueryClient()
  return useMutation<Project, unknown, void>({
    mutationFn: () => apiFetch<Project>(`/projects/${id}/refresh-mirror`, { method: 'POST' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: projectKey(id) }); void qc.invalidateQueries({ queryKey: projectsKey }) },
  })
}
export function useUploadProjectFiles(id: string) {
  const qc = useQueryClient()
  return useMutation<{ uploaded: number }, unknown, { files: File[]; paths: string[] }>({
    mutationFn: ({ files, paths }) => {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      paths.forEach((p) => form.append('paths', p))
      return apiUpload<{ uploaded: number }>(`/projects/${id}/uploads`, form)
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: [...projectKey(id), 'tree', 'uploads'] }) },
  })
}
