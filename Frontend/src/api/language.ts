import { api } from './client'
import type { SpellResult } from './types'

export const languageApi = {
  status: () => api.get<{ available: boolean; dictionary: string | null; error: string | null }>('/language/status/'),
  check: (text: string, world?: number, signal?: AbortSignal) =>
    api.post<SpellResult>('/language/spellcheck/', { text, world }, { signal }),
  suggest: (word: string) => api.get<{ word: string; suggestions: string[] }>('/language/suggest/', { query: { word } }),
  words: () => api.get<{ id: number; word: string }[]>('/language/dictionary/'),
  addWord: (word: string) => api.post<{ id: number; word: string }>('/language/dictionary/', { word }),
  removeWord: (id: number) => api.del(`/language/dictionary/${id}/`),
}
