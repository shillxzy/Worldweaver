import { api, listAll } from './client'
import type { Faction, Membership } from './types'

export type FactionInput = Partial<Omit<Faction, 'id' | 'members_count' | 'created_at' | 'updated_at'>>
export type MembershipInput = Partial<Omit<Membership, 'id' | 'character_name' | 'faction_name'>>

export const factionsApi = {
  list: (worldId: number, signal?: AbortSignal) => listAll<Faction>(`/worlds/${worldId}/factions/`, {}, signal),
  create: (worldId: number, data: FactionInput) => api.post<Faction>(`/worlds/${worldId}/factions/`, data),
  update: (worldId: number, id: number, data: FactionInput) => api.patch<Faction>(`/worlds/${worldId}/factions/${id}/`, data),
  remove: (worldId: number, id: number) => api.del(`/worlds/${worldId}/factions/${id}/`),
  memberships: (worldId: number, query: { character?: number; faction?: number } = {}) =>
    listAll<Membership>(`/worlds/${worldId}/memberships/`, query),
  addMembership: (worldId: number, data: MembershipInput) => api.post<Membership>(`/worlds/${worldId}/memberships/`, data),
  updateMembership: (worldId: number, id: number, data: MembershipInput) => api.patch<Membership>(`/worlds/${worldId}/memberships/${id}/`, data),
  removeMembership: (worldId: number, id: number) => api.del(`/worlds/${worldId}/memberships/${id}/`),
}
