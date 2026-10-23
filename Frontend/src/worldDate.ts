import type { Precision } from './api/types'

/**
 * Understands dates the way authors type them and turns them into a comparable number
 * for consistency checks (year + fraction of the year). The text itself is kept as typed.
 *
 *   "19 жовтня 1999", "19.10.1999", "1999-10-19", "жовтень 1999", "1999", "212 рік",
 *   "близько 1999" / "~1999" (approximate). Anything else (e.g. "весна Епохи Глибин")
 *   is kept as text only and is not used in date checks.
 */
export type ParsedDate = { key: number | null; precision: Precision; day?: number; month?: number; year?: number }

const MONTH_STEMS = [
  ['січ', 'jan'], ['лют', 'feb'], ['берез', 'mar'], ['квіт', 'apr'], ['трав', 'may'], ['черв', 'jun'],
  ['лип', 'jul'], ['серп', 'aug'], ['верес', 'sep'], ['жовт', 'oct'], ['листоп', 'nov'], ['груд', 'dec'],
]
const DAYS_BEFORE = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
const APPROX = /^(?:≈|~|бл\.?\s|близько\s|приблизно\s|около\s|circa\s|c\.\s|ca\.\s|approx\.?\s)/i

function monthIndex(word: string): number | null {
  const w = word.toLowerCase()
  const i = MONTH_STEMS.findIndex((stems) => stems.some((s) => w.startsWith(s)))
  return i >= 0 ? i + 1 : null
}

function toKey(year: number, month?: number, day?: number): number {
  if (!month) return year
  const dayOfYear = DAYS_BEFORE[month - 1] + (day ?? 1) - 1
  return Math.round((year + dayOfYear / 366) * 10000) / 10000
}

export function parseWorldDate(input: string): ParsedDate {
  let text = input.trim()
  if (!text) return { key: null, precision: 'unknown' }
  const approximate = APPROX.test(text)
  if (approximate) text = text.replace(APPROX, '').trim()
  const precision: Precision = approximate ? 'approximate' : 'exact'

  let m = /^(\d{1,2})[./](\d{1,2})[./](-?\d{1,6})/.exec(text)
  if (m) {
    const day = +m[1], month = +m[2], year = +m[3]
    if (month >= 1 && month <= 12 && day >= 1 && day <= 31) return { key: toKey(year, month, day), precision, day, month, year }
  }
  m = /^(-?\d{1,6})-(\d{1,2})-(\d{1,2})$/.exec(text)
  if (m) {
    const year = +m[1], month = +m[2], day = +m[3]
    if (month >= 1 && month <= 12 && day >= 1 && day <= 31) return { key: toKey(year, month, day), precision, day, month, year }
  }
  m = /^(\d{1,2})\s+([\p{L}]+)\.?,?\s+(-?\d{1,6})/u.exec(text)
  if (m && monthIndex(m[2])) {
    const day = +m[1], month = monthIndex(m[2])!, year = +m[3]
    if (day >= 1 && day <= 31) return { key: toKey(year, month, day), precision, day, month, year }
  }
  m = /^([\p{L}]+)\.?,?\s+(-?\d{1,6})/u.exec(text)
  if (m && monthIndex(m[1])) {
    const month = monthIndex(m[1])!, year = +m[2]
    return { key: toKey(year, month), precision, month, year }
  }
  m = /^(-?\d{1,6})(?:\s*(?:р\.?|рік|року|рр\.?|year|ad))?(?:\s|$|[,.])/iu.exec(text)
  if (m) {
    const year = +m[1]
    return { key: year, precision, year }
  }
  return { key: null, precision: 'unknown' }
}

/** Short human confirmation of what was understood, e.g. "19.10.1999" or "1999 рік". */
export function describeParsed(p: ParsedDate): string {
  if (p.key === null || p.year === undefined) return ''
  const approx = p.precision === 'approximate' ? '≈ ' : ''
  if (p.day && p.month) return `${approx}${String(p.day).padStart(2, '0')}.${String(p.month).padStart(2, '0')}.${p.year}`
  if (p.month) return `${approx}${String(p.month).padStart(2, '0')}.${p.year}`
  return `${approx}${p.year}`
}
