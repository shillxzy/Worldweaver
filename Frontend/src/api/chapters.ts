import { api, download, listAll } from './client'
import type { Chapter, ChapterStatus, ChapterSummary, ChapterVersion, ChapterVersionDetail, DocNode } from './types'

export type ChapterInput = {
  title?: string
  status?: ChapterStatus
  content?: DocNode
  base_revision?: number
  snapshot?: boolean
  story_time_key?: string | null
  story_time_label?: string
  is_flashback?: boolean
  narrator_unreliable?: boolean
}

export type ImportMode = 'new_chapter' | 'split_headings' | 'replace_chapter'

export type ImportPreview = {
  levels: { level: number; count: number; samples: string[] }[]
  split_level: number | null
  suggested_level: number | null
  chapters: { title: string; word_count: number; merged: string[]; lead_in: boolean }[]
}

const base = (bookId: number) => `/books/${bookId}/chapters/`

export const chaptersApi = {
  list: (bookId: number, signal?: AbortSignal) => listAll<ChapterSummary>(base(bookId), {}, signal),
  get: (bookId: number, id: number, signal?: AbortSignal) => api.get<Chapter>(`${base(bookId)}${id}/`, { signal }),
  create: (bookId: number, data: ChapterInput) => api.post<Chapter>(base(bookId), data),
  update: (bookId: number, id: number, data: ChapterInput, signal?: AbortSignal) =>
    api.patch<Chapter>(`${base(bookId)}${id}/`, data, { signal }),
  remove: (bookId: number, id: number) => api.del(`${base(bookId)}${id}/`),
  reorder: (bookId: number, order: number[]) => api.post<ChapterSummary[]>(`${base(bookId)}reorder/`, { order }),
  versions: (bookId: number, id: number) => api.get<ChapterVersion[]>(`${base(bookId)}${id}/versions/`),
  version: (bookId: number, id: number, versionId: number) =>
    api.get<ChapterVersionDetail>(`${base(bookId)}${id}/versions/${versionId}/`),
  restore: (bookId: number, id: number, versionId: number) =>
    api.post<Chapter>(`${base(bookId)}${id}/versions/${versionId}/restore/`),
  exportDocx: (bookId: number, chapter: Pick<ChapterSummary, 'id' | 'title'>) =>
    download(`${base(bookId)}${chapter.id}/export/`, `${chapter.title}.docx`),
  importDocx: (bookId: number, file: File, mode: ImportMode, chapterId?: number, splitLevel?: number) => {
    const form = new FormData()
    form.append('file', file)
    form.append('book', String(bookId))
    form.append('mode', mode)
    if (chapterId) form.append('chapter', String(chapterId))
    if (splitLevel) form.append('split_level', String(splitLevel))
    return api.upload<ChapterSummary[]>('/import/docx/', form)
  },
  /** Dry run of the heading split: the chapters an import would create. Nothing is saved. */
  previewDocx: (file: File, splitLevel?: number, signal?: AbortSignal) => {
    const form = new FormData()
    form.append('file', file)
    if (splitLevel) form.append('split_level', String(splitLevel))
    return api.upload<ImportPreview>('/import/docx/preview/', form, { signal })
  },
}
