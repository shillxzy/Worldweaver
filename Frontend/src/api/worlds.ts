import { api, listAll, request } from './client'
import type { SearchResult, World } from './types'

export type WorldInput = Partial<Pick<World,
  'name' | 'description' | 'genre' | 'rules' | 'tech_level' | 'magic_system' | 'time_unit_label' | 'calendar_notes'>>

export const worldsApi = {
  list: (signal?: AbortSignal) => listAll<World>('/worlds/', {}, signal),
  get: (id: number, signal?: AbortSignal) => api.get<World>(`/worlds/${id}/`, { signal }),
  create: (data: WorldInput) => api.post<World>('/worlds/', data),
  update: (id: number, data: WorldInput) => api.patch<World>(`/worlds/${id}/`, data),
  remove: (id: number) => api.del(`/worlds/${id}/`),
  graphLayout: (id: number, view: 'factions' | 'relations', signal?: AbortSignal) =>
    api.get<{ view: string; positions: Record<string, [number, number]> }>(`/worlds/${id}/graph-layout/${view}/`, { signal }),
  saveGraphLayout: (id: number, view: 'factions' | 'relations', positions: Record<string, [number, number]>) =>
    request<{ view: string; positions: Record<string, [number, number]> }>('PUT', `/worlds/${id}/graph-layout/${view}/`, { body: { positions } }),
  search: (id: number, q: string, signal?: AbortSignal) =>
    api.get<{ query: string; results: SearchResult[] }>(`/worlds/${id}/search/`, { query: { q }, signal }),
  globalSearch: (q: string, signal?: AbortSignal) =>
    api.get<{ query: string; results: SearchResult[] }>('/search/', { query: { q }, signal }),
}
