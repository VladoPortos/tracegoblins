import { useQuery } from '@tanstack/react-query'
import { apiFetch } from './client'

export interface FacetOrg { id: number; name: string | null }
export interface FacetController { id: string; name: string | null }
export interface RunFacets {
  organizations: FacetOrg[]; templates: string[]; controllers: FacetController[]
  statuses: string[]; launch_types: string[]; users: string[]
}
export const runFiltersKey = (scope: string) => ['runs', 'filters', scope] as const

export function useRunFilters(scope: 'mine' | 'shared' | 'team' = 'team') {
  return useQuery<RunFacets>({
    queryKey: runFiltersKey(scope),
    queryFn: () => apiFetch<RunFacets>(`/runs/filters?scope=${scope}`),
  })
}
