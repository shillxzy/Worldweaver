import { api, download, listAll } from './client'
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
}
