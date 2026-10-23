import { SECTIONS } from './data/projects'
import type { Section } from './types'

export type Route =
  | { page: 'library' }
  | { page: 'profile' }
  | { page: 'settings' }
  | { page: 'project'; bookId: number; section: Section; focus?: string; pageId?: number }
  /** Invitation link: join a shared project. */
  | { page: 'join'; token: string }
  /** Public read-only site of a world (no account needed). */
  | { page: 'public'; token: string; chapterId?: number; pageId?: number }

export function parseHash(): Route {
  const [path, query = ''] = location.hash.slice(1).split('?')
  const [, a, id, sec] = path.split('/')
  if (a === 'profile') return { page: 'profile' }
  if (a === 'settings') return { page: 'settings' }
  if (a === 'join' && id) return { page: 'join', token: id }
  if (a === 's' && id) {
    const target = Number(path.split('/')[4])
    const valid = Number.isInteger(target) && target > 0
    return { page: 'public', token: id, chapterId: sec === 'chapter' && valid ? target : undefined, pageId: sec === 'page' && valid ? target : undefined }
  }
  const bookId = a === 'p' ? Number(id) : NaN
  if (Number.isInteger(bookId) && bookId > 0) {
    const focus = new URLSearchParams(query).get('focus') ?? undefined
    const pageId = sec === 'page' ? Number(path.split('/')[4]) : NaN
    if (Number.isInteger(pageId) && pageId > 0) return { page: 'project', bookId, section: 'encyclopedia', pageId }
    return { page: 'project', bookId, section: SECTIONS.find((s) => s.id === sec)?.id ?? 'overview', focus }
  }
  return { page: 'library' }
}

export const navigate = (path: string) => { location.hash = path }
export const projectPath = (id: number, section: Section = 'overview', focus?: string) =>
  `/p/${id}/${section}${focus ? `?focus=${encodeURIComponent(focus)}` : ''}`
export const pagePath = (bookId: number, pageId: number) => `/p/${bookId}/page/${pageId}`
export const joinPath = (token: string) => `/join/${token}`
export const publicPath = (token: string, kind?: 'chapter' | 'page', id?: number) => `/s/${token}${kind && id ? `/${kind}/${id}` : ''}`
