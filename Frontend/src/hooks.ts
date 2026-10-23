import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { ApiError } from './api/client'

export type AsyncState<T> = {
  data: T | undefined
  loading: boolean
  error: ApiError | null
  reload: () => void
  setData: (updater: T | ((prev: T | undefined) => T)) => void
}

/**
 * Load data with cancellation: a new load (or unmount) aborts the previous request,
 * so stale responses never overwrite fresh state. `deps` must be primitives.
 * Loading/error are derived from which request key has completed, so the effect itself
 * only sets state asynchronously.
 */
export function useAsync<T>(loader: (signal: AbortSignal) => Promise<T>, deps: (string | number | boolean | null | undefined)[]): AsyncState<T> {
  const [tick, setTick] = useState(0)
  const key = JSON.stringify(deps) + ':' + tick
  const [data, setDataState] = useState<T>()
  const [done, setDone] = useState<{ key: string; error: ApiError | null }>({ key: '', error: null })
  const loaderRef = useRef(loader)
  useEffect(() => { loaderRef.current = loader })

  useEffect(() => {
    const controller = new AbortController()
    loaderRef.current(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setDataState(() => result)
        setDone({ key, error: null })
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setDone({ key, error: err instanceof ApiError ? err : new ApiError(0, 'client_error', String(err)) })
      })
    return () => controller.abort()
  }, [key])

  const reload = useCallback(() => setTick((n) => n + 1), [])
  const setData = useCallback((updater: T | ((prev: T | undefined) => T)) => {
    setDataState((prev) => (typeof updater === 'function' ? (updater as (p: T | undefined) => T)(prev) : updater))
  }, [])
  return { data, loading: done.key !== key, error: done.key === key ? done.error : null, reload, setData }
}

/** Run a mutation with a busy flag that prevents double submission. */
export function useBusy() {
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const run = useCallback(async <R,>(action: () => Promise<R>): Promise<R | undefined> => {
    if (busyRef.current) return undefined
    busyRef.current = true
    setBusy(true)
    try {
      return await action()
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }, [])
  return { busy, run }
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return err instanceof Error ? err.message : String(err)
}

/**
 * The last non-empty text selection made inside the element (editor or reader), kept while the
 * user moves on to type a comment elsewhere. `clear` forgets it once it has been used.
 */
export function useSelectionQuote(container: RefObject<HTMLElement | null>, enabled: boolean) {
  const [quote, setQuote] = useState('')
  useEffect(() => {
    if (!enabled) return
    const onChange = () => {
      const selection = document.getSelection()
      const text = selection?.toString().trim() ?? ''
      if (text && selection?.anchorNode && container.current?.contains(selection.anchorNode)) setQuote(text.slice(0, 500))
    }
    document.addEventListener('selectionchange', onChange)
    return () => document.removeEventListener('selectionchange', onChange)
  }, [container, enabled])
  return { quote, clear: useCallback(() => setQuote(''), []) }
}
