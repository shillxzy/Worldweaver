import { API_BASE, api, listAll } from './client'
import type { Character } from './types'

export type CharacterInput = Partial<Omit<Character, 'id' | 'has_portrait' | 'has_banner' | 'memberships' | 'created_at' | 'updated_at'>>

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
  uploadBanner: (worldId: number, id: number, file: File) => {
    const form = new FormData()
    form.append('banner', file)
    return api.upload<Character>(`${base(worldId)}${id}/banner/`, form)
  },
  removeBanner: (worldId: number, id: number) => api.del(`${base(worldId)}${id}/banner/`),
  bannerUrl: (worldId: number, c: Pick<Character, 'id' | 'updated_at'>) =>
    `${API_BASE}${base(worldId)}${c.id}/banner/?v=${encodeURIComponent(c.updated_at)}`,
}

export const nameHue = (s: string) => [...s].reduce((a, c) => a + c.charCodeAt(0) * 7, 0) % 360

/** CSS background of a character's banner: uploaded image, else chosen colour, else a hue derived from the name. */
export function bannerBackground(worldId: number, c: Pick<Character, 'id' | 'name' | 'updated_at' | 'has_banner' | 'banner_color'>) {
  if (c.has_banner) return `center / cover no-repeat url("${charactersApi.bannerUrl(worldId, c)}")`
  if (c.banner_color) return `linear-gradient(135deg, ${c.banner_color}, color-mix(in srgb, ${c.banner_color} 35%, #000))`
  const h = nameHue(c.name)
  return `linear-gradient(135deg, hsl(${h} 45% 32%), hsl(${h + 50} 45% 14%))`
}
