import { api, listAll } from './client'
import type { EntityType, Relationship, RelationshipKind } from './types'

export type RelationshipInput = {
  kind: RelationshipKind
  source: { type: EntityType; id: number }
  target: { type: EntityType; id: number }
  description?: string
  directed?: boolean
  start_key?: string | null
  start_label?: string
  end_key?: string | null
  end_label?: string
}

export const relationshipsApi = {
  list: (worldId: number, query: { entity_type?: EntityType; entity_id?: number; kind?: string } = {}) =>
    listAll<Relationship>(`/worlds/${worldId}/relationships/`, query),
  create: (worldId: number, data: RelationshipInput) => api.post<Relationship>(`/worlds/${worldId}/relationships/`, data),
  update: (worldId: number, id: number, data: Partial<Pick<RelationshipInput, 'kind' | 'description' | 'directed'>>) =>
    api.patch<Relationship>(`/worlds/${worldId}/relationships/${id}/`, data),
  remove: (worldId: number, id: number) => api.del(`/worlds/${worldId}/relationships/${id}/`),
}
