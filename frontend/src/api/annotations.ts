import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'

export const TAG_VALUES = ['needs-fix', 'known-issue', 'resolved', 'note'] as const

export interface AnnotationLink { label: string; url: string }
export interface Annotation {
  id: string; run_id: string; task_seq: number; author_user_id: string; author_name: string
  note: string; tags: string[]; links: AnnotationLink[]; resolved: boolean
  created_at: string; updated_at: string
}
export interface AnnotationCreate { note?: string; tags?: string[]; links?: AnnotationLink[] }
export interface AnnotationUpdate {
  note?: string | null; tags?: string[] | null; links?: AnnotationLink[] | null; resolved?: boolean | null
}

export const annotationsKey = (runId: string) => ['runs', runId, 'annotations'] as const

export function useRunAnnotations(runId: string) {
  return useQuery<Annotation[]>({
    queryKey: annotationsKey(runId),
    queryFn: () => apiFetch<Annotation[]>(`/runs/${runId}/annotations`),
    enabled: !!runId,
  })
}
export function useCreateAnnotation(runId: string, seq: number) {
  const qc = useQueryClient()
  return useMutation<Annotation, unknown, AnnotationCreate>({
    mutationFn: (body) => apiFetch<Annotation>(`/runs/${runId}/tasks/${seq}/annotations`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: annotationsKey(runId) }) },
  })
}
export function useUpdateAnnotation(runId: string) {
  const qc = useQueryClient()
  return useMutation<Annotation, unknown, { aid: string; patch: AnnotationUpdate }>({
    mutationFn: ({ aid, patch }) => apiFetch<Annotation>(`/annotations/${aid}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: annotationsKey(runId) }) },
  })
}
export function useDeleteAnnotation(runId: string) {
  const qc = useQueryClient()
  return useMutation<void, unknown, string>({
    mutationFn: (aid) => apiFetch<void>(`/annotations/${aid}`, { method: 'DELETE' }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: annotationsKey(runId) }) },
  })
}
