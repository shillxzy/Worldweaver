import { api, listAll } from './client'
import type { LoreEntry } from './types'

export type LoreInput = Partial<Omit<LoreEntry, 'id' | 'created_at' | 'updated_at'>>

export const loreApi = {
  list: (worldId: number, query: { search?: string; category?: string; tag?: string } = {}, signal?: AbortSignal) =>
    listAll<LoreEntry>(`/worlds/${worldId}/lore/`, query, signal),
  create: (worldId: number, data: LoreInput) => api.post<LoreEntry>(`/worlds/${worldId}/lore/`, data),
  update: (worldId: number, id: number, data: LoreInput) => api.patch<LoreEntry>(`/worlds/${worldId}/lore/${id}/`, data),
  remove: (worldId: number, id: number) => api.del(`/worlds/${worldId}/lore/${id}/`),
}
