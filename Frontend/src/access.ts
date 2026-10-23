import { createContext, useContext } from 'react'
import type { Role } from './api/types'

const RANK: Record<Role, number> = { viewer: 10, commenter: 20, editor: 30, admin: 40, owner: 50 }

/** What the current user may do in the open project (mirrors the server's checks; the server decides). */
export type Access = {
  role: Role
  /** Change content: chapters, pages, characters, timeline, diary, imports, checks. */
  edit: boolean
  /** Read and write comments. */
  comment: boolean
  /** Manage members and invitations; delete books. */
  manage: boolean
  /** Public site, ownership transfer, deleting the world. */
  own: boolean
}

export function accessFor(role: Role | undefined): Access {
  const rank = RANK[role ?? 'owner']
  return { role: role ?? 'owner', edit: rank >= RANK.editor, comment: rank >= RANK.commenter, manage: rank >= RANK.admin, own: rank >= RANK.owner }
}

export const roleAtLeast = (role: Role, min: Role) => RANK[role] >= RANK[min]

export const AccessContext = createContext<Access>(accessFor('owner'))

export const useAccess = () => useContext(AccessContext)
