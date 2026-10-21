/**
 * Centralised HTTP client for the Worldweaver API.
 *
 * - Base URL comes from VITE_API_BASE_URL (default: same-origin `/api/v1`, proxied by Vite in dev).
 * - Session cookies are always sent; unsafe methods carry the Django CSRF token (X-CSRFToken).
 * - Errors are normalised into ApiError with the server's {error: {code, message, details}} shape.
 * - Mutating requests are never retried automatically.
 */

export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') || '/api/v1'

export type ErrorDetails = Record<string, unknown> | unknown[] | null

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: ErrorDetails

  constructor(status: number, code: string, message: string, details: ErrorDetails = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  get isNetwork() { return this.code === 'network' }
  get isAborted() { return this.code === 'aborted' }

  /** First validation message for a field, if the server reported one. */
  field(name: string): string | undefined {
    if (!this.details || Array.isArray(this.details)) return undefined
    const value = (this.details as Record<string, unknown>)[name]
    if (Array.isArray(value)) return value.map(String).join(' ')
    return typeof value === 'string' ? value : undefined
  }
}

export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] }

type Query = Record<string, string | number | boolean | undefined | null>

export type RequestOptions = {
  query?: Query
  body?: unknown
  form?: FormData
  signal?: AbortSignal
  /** Return the raw Response (downloads). */
  raw?: boolean
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

function readCookie(name: string): string | null {
  const match = document.cookie.split('; ').find((c) => c.startsWith(name + '='))
  return match ? decodeURIComponent(match.split('=')[1]) : null
}

let csrfPromise: Promise<void> | null = null

/** Make sure the csrftoken cookie exists (GET /auth/csrf/ sets it). */
export async function ensureCsrf(force = false): Promise<void> {
  if (!force && readCookie('csrftoken')) return
  if (!csrfPromise || force) {
    csrfPromise = fetch(`${API_BASE}/auth/csrf/`, { credentials: 'include' })
      .then(() => undefined)
      .finally(() => { csrfPromise = null })
  }
  return csrfPromise
}

function buildUrl(path: string, query?: Query): string {
  const url = path.startsWith('http') || path.startsWith('/api') ? path : `${API_BASE}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}${url.includes('?') ? '&' : '?'}${qs}` : url
}

async function parseError(response: Response): Promise<ApiError> {
  let code = 'http_' + response.status
  let message = `Помилка сервера (${response.status}).`
  let details: ErrorDetails = null
  try {
    const data = (await response.json()) as { error?: { code?: string; message?: string; details?: ErrorDetails } }
    if (data?.error) {
      code = data.error.code ?? code
      message = data.error.message ?? message
      details = data.error.details ?? null
    }
  } catch {
    // Non-JSON error body (e.g. proxy error page): keep the generic message.
  }
  if (response.status === 502 || response.status === 504) {
    code = 'network'
    message = 'Сервер Worldweaver недоступний. Перевірте, чи запущено backend.'
  }
  return new ApiError(response.status, code, message, details)
}

export async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  let body: BodyInit | undefined
  if (options.form) {
    body = options.form
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (UNSAFE.has(method)) {
    await ensureCsrf()
    const token = readCookie('csrftoken')
    if (token) headers['X-CSRFToken'] = token
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, options.query), {
      method, headers, body, credentials: 'include', signal: options.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw new ApiError(0, 'aborted', 'Запит скасовано.')
    throw new ApiError(0, 'network', 'Немає зʼєднання з сервером Worldweaver.')
  }

  if (!response.ok) throw await parseError(response)
  if (options.raw) return response as unknown as T
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>('GET', path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('POST', path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PATCH', path, { ...options, body }),
  del: <T = void>(path: string, body?: unknown, options?: RequestOptions) => request<T>('DELETE', path, { ...options, body }),
  upload: <T>(path: string, form: FormData, options?: RequestOptions) => request<T>('POST', path, { ...options, form }),
}

/** Fetch every page of a paginated list (lists are capped server-side at 200 per page). */
export async function listAll<T>(path: string, query: Query = {}, signal?: AbortSignal): Promise<T[]> {
  const items: T[] = []
  let next: string | null = buildUrl(path, { ...query, page_size: 200 })
  while (next) {
    const page: Paginated<T> = await request<Paginated<T>>('GET', next, { signal })
    items.push(...page.results)
    next = page.next ? toRelative(page.next) : null
  }
  return items
}

function toRelative(url: string): string {
  try {
    const parsed = new URL(url)
    return parsed.origin === location.origin ? parsed.pathname + parsed.search : url
  } catch {
    return url
  }
}

/** Trigger a browser download for an API response (DOCX export). */
export async function download(path: string, fallbackName: string): Promise<void> {
  const response = await request<Response>('GET', path, { raw: true })
  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const utf = /filename\*=UTF-8''([^;]+)/.exec(disposition)
  const plain = /filename="([^"]+)"/.exec(disposition)
  const name = utf ? decodeURIComponent(utf[1]) : plain ? plain[1] : fallbackName
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}
