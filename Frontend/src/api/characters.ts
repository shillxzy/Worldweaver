import { API_BASE, api, listAll } from './client'
import type { Character } from './types'

export type CharacterInput = Partial<Omit<Character, 'id' | 'has_portrait' | 'memberships' | 'created_at' | 'updated_at'>>

const base = (worldId: number) => `/worlds/${worldId}/characters/`

export const charactersApi = {
  list: (worldId: number, query: { search?: string; status?: string; faction?: number } = {}, signal?: AbortSignal) =>
    listAll<Character>(base(worldId), query, signal),
  get: (worldId: number, id: number) => api.get<Character>(`${base(worldId)}${id}/`),
  create: (worldId: number, data: CharacterInput) => api.post<Character>(base(worldId), data),
  update: (worldId: number, id: number, data: CharacterInput) => api.patch<Character>(`${base(worldId)}${id}/`, data),
  remove: (worldId: number, id: number) => api.del(`${base(worldId)}${id}/`),
  uploadPortrait: (worldId: number, id: number, file: File) => {
    const form = new FormData()
    form.append('portrait', file)
    return api.upload<Character>(`${base(worldId)}${id}/portrait/`, form)
  },
  removePortrait: (worldId: number, id: number) => api.del(`${base(worldId)}${id}/portrait/`),
  portraitUrl: (worldId: number, c: Pick<Character, 'id' | 'updated_at'>) =>
    `${API_BASE}${base(worldId)}${c.id}/portrait/?v=${encodeURIComponent(c.updated_at)}`,
}
