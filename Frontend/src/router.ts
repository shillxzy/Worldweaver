import { SECTIONS } from './data/projects'
import type { Section } from './types'

export type Route =
  | { page: 'library' }
  | { page: 'profile' }
  | { page: 'settings' }
  | { page: 'project'; bookId: number; section: Section; focus?: string }

export function parseHash(): Route {
  const [path, query = ''] = location.hash.slice(1).split('?')
  const [, a, id, sec] = path.split('/')
  if (a === 'profile') return { page: 'profile' }
  if (a === 'settings') return { page: 'settings' }
  const bookId = a === 'p' ? Number(id) : NaN
  if (Number.isInteger(bookId) && bookId > 0) {
    const focus = new URLSearchParams(query).get('focus') ?? undefined
    return { page: 'project', bookId, section: SECTIONS.find((s) => s.id === sec)?.id ?? 'overview', focus }
  }
  return { page: 'library' }
}

export const navigate = (path: string) => { location.hash = path }
export const projectPath = (id: number, section: Section = 'overview', focus?: string) =>
  `/p/${id}/${section}${focus ? `?focus=${encodeURIComponent(focus)}` : ''}`
