import { API_BASE, api, listAll } from './client'
import type { DocNode, PageDetail, PageProperty, PageSummary, PageTemplateInfo, PropertyKind } from './types'

const base = (worldId: number) => `/worlds/${worldId}/pages/`

export type PageInput = {
  title?: string
  icon?: string
  page_type?: string
  aliases?: string[]
  content?: DocNode
  base_revision?: number
}

export const pagesApi = {
  list: (worldId: number, query: { search?: string; page_type?: string } = {}, signal?: AbortSignal) =>
    listAll<PageSummary>(base(worldId), query, signal),
  get: (worldId: number, id: number, signal?: AbortSignal) => api.get<PageDetail>(`${base(worldId)}${id}/`, { signal }),
  create: (worldId: number, data: { title?: string; parent?: number | null; template?: string; user_template?: number; page_type?: string }) =>
    api.post<PageDetail>(base(worldId), data),
  update: (worldId: number, id: number, data: PageInput, signal?: AbortSignal) =>
    api.patch<PageDetail>(`${base(worldId)}${id}/`, data, { signal }),
  remove: (worldId: number, id: number, children?: 'lift' | 'delete') =>
    api.del<{ deleted: number }>(`${base(worldId)}${id}/`, undefined, { query: { children } }),
  move: (worldId: number, id: number, parent: number | null, position?: number) =>
    api.post<PageSummary>(`${base(worldId)}${id}/move/`, { parent, position }),
  lookup: (worldId: number, q: string, signal?: AbortSignal) => api.get<PageSummary[]>(`${base(worldId)}lookup/`, { query: { q }, signal }),
  byEntity: (worldId: number, type: string, id: number) => api.get<PageSummary>(`${base(worldId)}by-entity/`, { query: { type, id } }),
  saveAsTemplate: (worldId: number, id: number, name: string) => api.post<PageTemplateInfo>(`${base(worldId)}${id}/save-as-template/`, { name }),
  uploadCover: (worldId: number, id: number, file: File) => {
    const form = new FormData()
    form.append('cover', file)
    return api.upload<PageDetail>(`${base(worldId)}${id}/cover/`, form)
  },
  removeCover: (worldId: number, id: number) => api.del(`${base(worldId)}${id}/cover/`),
  coverUrl: (worldId: number, page: Pick<PageSummary, 'id' | 'updated_at'>) =>
    `${API_BASE}${base(worldId)}${page.id}/cover/?v=${encodeURIComponent(page.updated_at)}`,
  addProperty: (worldId: number, pageId: number, data: { label: string; kind: PropertyKind; value?: unknown }) =>
    api.post<PageProperty>(`${base(worldId)}${pageId}/properties/`, data),
  updateProperty: (worldId: number, pageId: number, id: number, data: Partial<Pick<PageProperty, 'label' | 'kind' | 'value'>>) =>
    api.patch<PageProperty>(`${base(worldId)}${pageId}/properties/${id}/`, data),
  removeProperty: (worldId: number, pageId: number, id: number) => api.del(`${base(worldId)}${pageId}/properties/${id}/`),
  reorderProperties: (worldId: number, pageId: number, order: number[]) =>
    api.post<PageProperty[]>(`${base(worldId)}${pageId}/properties/reorder/`, { order }),
  templates: (worldId: number) => api.get<PageTemplateInfo[]>('/page-templates/', { query: { world: worldId } }),
  removeTemplate: (id: number) => api.del(`/page-templates/${id}/`),
  relevantForChapter: (bookId: number, chapterId: number) =>
    api.get<{ chapter: number; pages: { id: number; title: string; icon: string; page_type: string; mentions: number }[] }>(
      `/books/${bookId}/chapters/${chapterId}/relevant-pages/`),
}
