import { api, listAll } from './client'
import type { Paginated } from './client'
import type { AIStatus, AnalysisJob, Decision, Finding, JobKind, QuickCheckResult } from './types'

export const analysisApi = {
  runConsistency: (worldId: number, bookId?: number) =>
    api.post<AnalysisJob>(`/worlds/${worldId}/consistency/`, bookId ? { book: bookId } : {}),
  createJob: (data: { kind: Exclude<JobKind, 'consistency'>; book?: number; chapter?: number; text?: string; use_ai?: boolean }) =>
    api.post<AnalysisJob>('/analysis/', data),
  jobs: (query: { book?: number; world?: number } = {}, signal?: AbortSignal) =>
    api.get<Paginated<AnalysisJob>>('/analysis/', { query: { ...query, page_size: 20 }, signal }),
  job: (id: number, signal?: AbortSignal) => api.get<AnalysisJob>(`/analysis/${id}/`, { signal }),
  cancel: (id: number) => api.post<AnalysisJob>(`/analysis/${id}/cancel/`),
  results: (id: number, signal?: AbortSignal) => listAll<Finding>(`/analysis/${id}/results/`, {}, signal),
  decide: (findingId: number, decision: Decision, decision_note = '') =>
    api.patch<Finding>(`/analysis/findings/${findingId}/`, { decision, decision_note }),
  explain: (findingId: number) => api.post<{ explanation: string; model: string }>(`/analysis/findings/${findingId}/explain/`),
  quickCheck: (chapter: number, text: string, offset: number, signal?: AbortSignal) =>
    api.post<QuickCheckResult>('/analysis/quick-check/', { chapter, text, offset }, { signal }),
  aiStatus: (signal?: AbortSignal) => api.get<AIStatus>('/ai/status/', { signal }),
}
