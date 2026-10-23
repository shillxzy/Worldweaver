import type { LoreCategory } from '../api/types'
import type { IconName } from '../icons'
import type { EntryKind, Section } from '../types'

/** Static design metadata (not user data): icons and colours of encyclopedia kinds. */
export const TYPE_META: Record<EntryKind, { icon: IconName; color: string }> = {
  Персонаж: { icon: 'user', color: '#7aa2ff' },
  Фракція: { icon: 'shield', color: '#e879a8' },
  Локація: { icon: 'pin', color: '#6fd1a0' },
  Предмет: { icon: 'gem', color: '#e0b36a' },
  Істота: { icon: 'eye', color: '#c58bff' },
  Лор: { icon: 'encyclopedia', color: '#9aa7b8' },
}
export const TYPES: ('Усе' | EntryKind)[] = ['Усе', 'Персонаж', 'Фракція', 'Локація', 'Предмет', 'Істота', 'Лор']

/** Lore categories that have their own encyclopedia tab; the rest are grouped under «Лор». */
export const KIND_BY_CATEGORY: Partial<Record<LoreCategory, EntryKind>> = { location: 'Локація', item: 'Предмет', creature: 'Істота' }
export const CATEGORY_BY_KIND: Partial<Record<EntryKind, LoreCategory>> = { Локація: 'location', Предмет: 'item', Істота: 'creature' }

export const LORE_CATEGORIES: LoreCategory[] = [
  'history', 'geography', 'location', 'magic', 'culture', 'technology', 'religion', 'rules', 'item', 'creature', 'custom',
]

export const SECTIONS: { id: Section; icon: IconName }[] = [
  { id: 'overview', icon: 'overview' },
  { id: 'encyclopedia', icon: 'encyclopedia' },
  { id: 'characters', icon: 'users' },
  { id: 'graph', icon: 'graph' },
  { id: 'diary', icon: 'pen' },
  { id: 'book', icon: 'read' },
  { id: 'timeline', icon: 'clock' },
  { id: 'analysis', icon: 'shield' },
]

export const ACCENTS = ['#3fb8c9', '#c58bff', '#e0b36a', '#e879a8', '#6fd1a0', '#7aa2ff']

/** Suggested encyclopedia page types; authors can also type their own. */
export const PAGE_TYPES = ['note', 'character', 'faction', 'location', 'item', 'creature', 'event', 'lore', 'magic', 'culture', 'religion', 'rules']
