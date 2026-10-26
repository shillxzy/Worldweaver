import { API_BASE, api } from './client'
import type {
  Comment, Invite, InvitePreview, MembersInfo, PublicChapter, PublicPage, PublicSettings, PublicSite, Role,
} from './types'

const w = (worldId: number) => `/worlds/${worldId}`

export type InviteInput = { email?: string; role: Role; expires_in_days?: number | null; max_uses?: number | null }
export type CommentTarget = { chapter: number } | { page: number }
export type PublicFlags = { enabled?: boolean; regenerate?: boolean; books?: Record<number, boolean>; chapters?: Record<number, boolean>; pages?: Record<number, boolean> }

export const collabApi = {
  members: (worldId: number, signal?: AbortSignal) => api.get<MembersInfo>(`${w(worldId)}/members/`, { signal }),
  setRole: (worldId: number, userId: number, role: Role) => api.patch<MembersInfo>(`${w(worldId)}/members/${userId}/`, { role }),
  removeMember: (worldId: number, userId: number) => api.del(`${w(worldId)}/members/${userId}/`),
  memberAvatarUrl: (worldId: number, userId: number) => `${API_BASE}${w(worldId)}/members/${userId}/avatar/`,
  transfer: (worldId: number, userId: number) => api.post<MembersInfo>(`${w(worldId)}/transfer/`, { user: userId }),

  invites: (worldId: number, signal?: AbortSignal) => api.get<Invite[]>(`${w(worldId)}/invites/`, { signal }),
  createInvite: (worldId: number, data: InviteInput) => api.post<Invite>(`${w(worldId)}/invites/`, data),
  revokeInvite: (worldId: number, id: number) => api.del(`${w(worldId)}/invites/${id}/`),
  previewInvite: (token: string, signal?: AbortSignal) => api.get<InvitePreview>(`/invites/${encodeURIComponent(token)}/`, { signal }),
  acceptInvite: (token: string) => api.post<{ world: number; book: number | null; role: Role }>(`/invites/${encodeURIComponent(token)}/accept/`),
  declineInvite: (token: string) => api.post<void>(`/invites/${encodeURIComponent(token)}/decline/`),
  myInvites: (signal?: AbortSignal) => api.get<InvitePreview[]>('/invites/mine/', { signal }),

  comments: (worldId: number, target: CommentTarget, signal?: AbortSignal) =>
    api.get<Comment[]>(`${w(worldId)}/comments/`, { query: target, signal }),
  addComment: (worldId: number, data: (CommentTarget | { parent: number }) & { body: string; quote?: string; quote_occurrence?: number }) =>
    api.post<Comment>(`${w(worldId)}/comments/`, data),
  updateComment: (worldId: number, id: number, data: { body?: string; resolved?: boolean }) =>
    api.patch<Comment>(`${w(worldId)}/comments/${id}/`, data),
  removeComment: (worldId: number, id: number) => api.del(`${w(worldId)}/comments/${id}/`),
  commentCounts: (worldId: number, bookId: number, signal?: AbortSignal) =>
    api.get<{ chapters: Record<string, number>; pages: Record<string, number> }>(`${w(worldId)}/comment-counts/`, { query: { book: bookId }, signal }),

  publicSettings: (worldId: number, signal?: AbortSignal) => api.get<PublicSettings>(`${w(worldId)}/public/`, { signal }),
  updatePublic: (worldId: number, data: PublicFlags) => api.patch<PublicSettings>(`${w(worldId)}/public/`, data),
}

/** Anonymous read-only site of a world. */
export const publicApi = {
  site: (token: string, signal?: AbortSignal) => api.get<PublicSite>(`/public/${encodeURIComponent(token)}/`, { signal }),
  chapter: (token: string, id: number, signal?: AbortSignal) => api.get<PublicChapter>(`/public/${encodeURIComponent(token)}/chapters/${id}/`, { signal }),
  page: (token: string, id: number, signal?: AbortSignal) => api.get<PublicPage>(`/public/${encodeURIComponent(token)}/pages/${id}/`, { signal }),
  imageUrl: (token: string, kind: 'book-cover' | 'page-cover' | 'portrait', id: number, version = '') =>
    `${API_BASE}/public/${encodeURIComponent(token)}/images/${kind}/${id}/${version ? `?v=${encodeURIComponent(version)}` : ''}`,
}

/** Shareable address of an app route (hash routing). */
export const appUrl = (hashPath: string) => `${location.origin}${location.pathname}#${hashPath}`
