import { api, listAll } from './client'
import type { Board, BoardConnection, BoardItem } from './types'

export type BoardItemInput = Partial<Omit<BoardItem, 'id' | 'board' | 'created_at' | 'updated_at'>>
export type LayoutUpdate = { id: number; x?: number; y?: number; order?: number; parent?: number | null }

export const boardsApi = {
  forBook: (bookId: number, signal?: AbortSignal) => listAll<Board>('/boards/', { book: bookId }, signal),
  create: (data: { title: string; book?: number; world?: number; with_default_columns?: boolean }) => api.post<Board>('/boards/', data),
  get: (id: number) => api.get<Board>(`/boards/${id}/`),
  layout: (id: number, items: LayoutUpdate[]) => api.post<Board>(`/boards/${id}/layout/`, { items }),
  addItem: (boardId: number, data: BoardItemInput) => api.post<BoardItem>(`/boards/${boardId}/items/`, data),
  updateItem: (boardId: number, id: number, data: BoardItemInput) => api.patch<BoardItem>(`/boards/${boardId}/items/${id}/`, data),
  removeItem: (boardId: number, id: number) => api.del(`/boards/${boardId}/items/${id}/`),
  connect: (boardId: number, source: number, target: number, label = '') =>
    api.post<BoardConnection>(`/boards/${boardId}/connections/`, { source, target, label }),
  disconnect: (boardId: number, id: number) => api.del(`/boards/${boardId}/connections/${id}/`),
}
