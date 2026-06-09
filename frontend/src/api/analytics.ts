import { useQuery } from '@tanstack/react-query'
import { apiFetch } from './client'

// Response shapes — mirror backend app/api/analytics.py (Canonical Contract).
export interface TemplateStat {
  template_name: string
  runs: number
  failed: number
  succeeded: number
  success_rate: number
  current_streak: number
  streak_kind: 'pass' | 'fail'
  flips: number
  flaky_score: number // flips / (runs-1); 0 when runs < 2
  avg_duration_s: number | null
  time_to_recovery_s: number | null // mean seconds from a failure streak's first fail to the next pass
  last_status: string
  last_when: string | null
  last_run_id: string
  recent: string[] // last ≤20 statuses, oldest→newest
  recent_ids: string[]
}
export interface TemplateStatsOut { items: TemplateStat[]; window_days: number }

export const analyticsKey = (days: number) => ['analytics', 'templates', days] as const

export function useTemplateStats(days: number) {
  return useQuery({
    queryKey: analyticsKey(days),
    queryFn: () => apiFetch<TemplateStatsOut>(`/analytics/templates?days=${days}`),
  })
}
