import { api, listAll } from './client'
import type { Chronology, Dependency, TimelineEvent } from './types'

export type EventInput = Partial<Omit<TimelineEvent, 'id' | 'created_at' | 'updated_at'>>

export const timelineApi = {
  list: (worldId: number, signal?: AbortSignal) => listAll<TimelineEvent>(`/worlds/${worldId}/timeline/`, {}, signal),
  create: (worldId: number, data: EventInput) => api.post<TimelineEvent>(`/worlds/${worldId}/timeline/`, data),
  update: (worldId: number, id: number, data: EventInput) => api.patch<TimelineEvent>(`/worlds/${worldId}/timeline/${id}/`, data),
  remove: (worldId: number, id: number) => api.del(`/worlds/${worldId}/timeline/${id}/`),
  dependencies: (worldId: number, signal?: AbortSignal) => listAll<Dependency>(`/worlds/${worldId}/dependencies/`, {}, signal),
  addDependency: (worldId: number, data: { before: number; after: number; kind?: string; min_gap?: string | null; description?: string }) =>
    api.post<Dependency>(`/worlds/${worldId}/dependencies/`, data),
  removeDependency: (worldId: number, id: number) => api.del(`/worlds/${worldId}/dependencies/${id}/`),
  chronology: (worldId: number, signal?: AbortSignal) => api.get<Chronology>(`/worlds/${worldId}/chronology/`, { signal }),
}
