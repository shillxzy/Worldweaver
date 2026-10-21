import { API_BASE, api, download, listAll } from './client'
import type { Book } from './types'

export type BookInput = Partial<Pick<Book, 'world' | 'title' | 'description' | 'genre' | 'status' | 'manuscript_format' | 'accent'>> & {
  new_world_name?: string
}

export const booksApi = {
  list: (signal?: AbortSignal) => listAll<Book>('/books/', {}, signal),
  get: (id: number, signal?: AbortSignal) => api.get<Book>(`/books/${id}/`, { signal }),
  create: (data: BookInput) => api.post<Book>('/books/', data),
  update: (id: number, data: BookInput) => api.patch<Book>(`/books/${id}/`, data),
  remove: (id: number) => api.del(`/books/${id}/`),
  exportDocx: (book: Pick<Book, 'id' | 'title'>) => download(`/books/${book.id}/export/`, `${book.title}.docx`),
  uploadCover: (id: number, file: File) => {
    const form = new FormData()
    form.append('cover', file)
    return api.upload<Book>(`/books/${id}/cover/`, form)
  },
  removeCover: (id: number) => api.del(`/books/${id}/cover/`),
  coverUrl: (book: Pick<Book, 'id' | 'updated_at'>) => `${API_BASE}/books/${book.id}/cover/?v=${encodeURIComponent(book.updated_at)}`,
}
