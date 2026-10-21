import { createContext, useContext } from 'react'
import type { Book, User } from './api/types'

export type Theme = 'dark' | 'light'
export type Lang = 'uk' | 'en'
export type { User }

export type ToastKind = 'ok' | 'error' | 'info'
export type Toast = { id: number; kind: ToastKind; text: string }

export type AppCtx = {
  theme: Theme
  setTheme: (t: Theme) => void
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: string) => string
  user: User
  setUser: (u: User) => void
  logout: () => void
  /** Called after the account was deleted on the server. */
  accountDeleted: () => void
  books: Book[]
  booksLoading: boolean
  refreshBooks: () => Promise<void>
  notify: (text: string, kind?: ToastKind) => void
  online: boolean
}

export const AppContext = createContext<AppCtx | null>(null)

export function useApp(): AppCtx {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside AppContext.Provider')
  return ctx
}
