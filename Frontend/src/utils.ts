import type { CSSProperties } from 'react'

export const cssVars = (v: Record<string, string>) => v as CSSProperties
export const accentVars = (c: string) => cssVars({ '--accent': c, '--c': c })
