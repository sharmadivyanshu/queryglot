import { useCallback, useEffect, useRef, useState } from 'react'
import type { Client, SearchResponse } from './api'

/**
 * The four pipeline stages the "thinking" state walks through:
 * 0 retrieve, 1 compile, 2 validate, 3 execute. v1 has no streaming, so the
 * UI can only ever confirm stages 0-2 have started — "execute" is the
 * response itself, so it is never shown as done/current speculatively
 * (the honest-thinking rule). The state snaps straight to answered/
 * abstained/failed the moment the real response lands.
 */
export type ThinkingStage = 0 | 1 | 2 | 3

export type AskState =
  | { kind: 'idle' }
  | { kind: 'thinking'; stage: ThinkingStage }
  | { kind: 'answered'; answer: SearchResponse }
  | { kind: 'abstained'; answer: SearchResponse }
  | { kind: 'failed'; answer: SearchResponse; error?: undefined }
  | { kind: 'failed'; answer?: undefined; error: string }

export interface UseAskResult {
  state: AskState
  ask: (question: string) => void
  reset: () => void
}

const STAGE_INTERVAL_MS = 600
const THINKING_CAP: ThinkingStage = 2

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useAsk(client: Client, backend?: string): UseAskResult {
  const [state, setState] = useState<AskState>({ kind: 'idle' })
  const requestIdRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  // Belt-and-braces: also clear on unmount so a pending interval never
  // fires (and never calls setState) after the component is gone.
  useEffect(() => clearTimer, [clearTimer])

  const reset = useCallback(() => {
    requestIdRef.current += 1
    clearTimer()
    setState({ kind: 'idle' })
  }, [clearTimer])

  const ask = useCallback(
    (question: string) => {
      const requestId = ++requestIdRef.current
      clearTimer()

      const reduced = prefersReducedMotion()
      setState({ kind: 'thinking', stage: reduced ? 1 : 0 })

      if (!reduced) {
        timerRef.current = setInterval(() => {
          setState((current) => {
            if (current.kind !== 'thinking' || current.stage >= THINKING_CAP) {
              clearTimer()
              return current
            }
            return { kind: 'thinking', stage: (current.stage + 1) as ThinkingStage }
          })
        }, STAGE_INTERVAL_MS)
      }

      client
        .search(question, backend)
        .then((answer) => {
          if (requestIdRef.current !== requestId) {
            return
          }
          clearTimer()
          if (answer.outcome === 'answered') {
            setState({ kind: 'answered', answer })
          } else if (answer.outcome === 'abstained') {
            setState({ kind: 'abstained', answer })
          } else {
            setState({ kind: 'failed', answer })
          }
        })
        .catch((err: unknown) => {
          if (requestIdRef.current !== requestId) {
            return
          }
          clearTimer()
          const message = err instanceof Error ? err.message : 'request failed'
          setState({ kind: 'failed', error: message })
        })
    },
    [client, backend, clearTimer],
  )

  return { state, ask, reset }
}
