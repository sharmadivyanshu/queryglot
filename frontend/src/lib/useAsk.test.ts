import { renderHook, act, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { createClient } from './api'
import { useAsk } from './useAsk'

const answered = {
  outcome: 'answered',
  backend: 'prometheus',
  query: 'up',
  result: [],
  reason: '',
  schema_used: ['up'],
  attempts: 1,
  elapsed_ms: 900,
}

function mockFetch(payload: unknown, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok, status: ok ? 200 : 500, json: async () => payload })),
  )
}

function mockMatchMedia(matches: boolean) {
  window.matchMedia = ((query: string) =>
    ({
      matches,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent() {
        return false
      },
    }) as MediaQueryList) as typeof window.matchMedia
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

test('search posts question and bearer', async () => {
  mockFetch(answered)
  const client = createClient({ api: 'http://x', token: 't1' })
  await client.search('q')
  const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(url).toBe('http://x/api/search')
  expect(init.headers.Authorization).toBe('Bearer t1')
})

test('search posts question and backend in body', async () => {
  mockFetch(answered)
  const client = createClient({ api: 'http://x' })
  await client.search('up rate', 'prometheus')
  const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(JSON.parse(init.body as string)).toEqual({ question: 'up rate', backend: 'prometheus' })
})

test('schema and status hit the right routes', async () => {
  mockFetch({ items: ['up'] })
  const client = createClient({ api: 'http://x' })
  await client.schema('up', 5)
  const [schemaUrl] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(schemaUrl).toBe('http://x/api/schema?query=up&limit=5')

  mockFetch({ backends: { prometheus: 3 }, version: '0.1.0' })
  await client.status()
  const [statusUrl] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(statusUrl).toBe('http://x/api/status')
})

test('non-ok HTTP response rejects with a plain message', async () => {
  mockFetch({ detail: 'bad token' }, false)
  const client = createClient({ api: 'http://x' })
  await expect(client.search('q')).rejects.toThrow()
})

test('ask walks thinking then snaps to answered', async () => {
  mockFetch(answered)
  const { result } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('q')
  })
  expect(result.current.state.kind).toBe('thinking')
  await waitFor(() => expect(result.current.state.kind).toBe('answered'))
  if (result.current.state.kind === 'answered') {
    expect(result.current.state.answer.query).toBe('up')
  }
})

test('abstained outcome maps to abstained state', async () => {
  mockFetch({ ...answered, outcome: 'abstained', reason: 'nothing matches' })
  const { result } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('q')
  })
  await waitFor(() => expect(result.current.state.kind).toBe('abstained'))
})

test('failed outcome (HTTP 200) maps to failed state carrying the answer', async () => {
  mockFetch({ ...answered, outcome: 'failed', reason: 'engine error' })
  const { result } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('q')
  })
  await waitFor(() => expect(result.current.state.kind).toBe('failed'))
  if (result.current.state.kind === 'failed') {
    expect(result.current.state.answer?.reason).toBe('engine error')
  }
})

test('network error maps to failed', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new Error('down')
    }),
  )
  const { result } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('q')
  })
  await waitFor(() => expect(result.current.state.kind).toBe('failed'))
  if (result.current.state.kind === 'failed') {
    expect(result.current.state.error).toBe('down')
  }
})

test('non-ok HTTP status maps to failed with a plain message', async () => {
  mockFetch({ detail: 'invalid or missing bearer token' }, false)
  const { result } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('q')
  })
  await waitFor(() => expect(result.current.state.kind).toBe('failed'))
  if (result.current.state.kind === 'failed') {
    expect(typeof result.current.state.error).toBe('string')
  }
})

test('thinking never advances past stage 2 (validate) before the response arrives', async () => {
  vi.useFakeTimers()
  let resolveSearch: (value: unknown) => void = () => {}
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise((resolve) => {
          resolveSearch = () => resolve({ ok: true, status: 200, json: async () => answered })
        }),
    ),
  )
  const { result } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('q')
  })
  expect(result.current.state).toEqual({ kind: 'thinking', stage: 0 })

  await act(async () => {
    await vi.advanceTimersByTimeAsync(600)
  })
  expect(result.current.state).toEqual({ kind: 'thinking', stage: 1 })

  await act(async () => {
    await vi.advanceTimersByTimeAsync(600)
  })
  expect(result.current.state).toEqual({ kind: 'thinking', stage: 2 })

  // Way past the point stage 3 (execute) would appear on a naive timer —
  // must stay capped at 2 because the response has not landed yet.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(600 * 5)
  })
  expect(result.current.state).toEqual({ kind: 'thinking', stage: 2 })

  await act(async () => {
    resolveSearch(undefined)
    await vi.advanceTimersByTimeAsync(0)
  })
  expect(result.current.state.kind).toBe('answered')
})

test('prefers-reduced-motion jumps straight to a static stage 1', async () => {
  mockMatchMedia(true)
  let resolveSearch: (value: unknown) => void = () => {}
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise((resolve) => {
          resolveSearch = () => resolve({ ok: true, status: 200, json: async () => answered })
        }),
    ),
  )
  const { result } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('q')
  })
  expect(result.current.state).toEqual({ kind: 'thinking', stage: 1 })

  await new Promise((r) => setTimeout(r, 20))
  expect(result.current.state).toEqual({ kind: 'thinking', stage: 1 })

  await act(async () => {
    resolveSearch(undefined)
  })
  await waitFor(() => expect(result.current.state.kind).toBe('answered'))
})

test('ignores a stale response after reset', async () => {
  let resolveSearch: (value: unknown) => void = () => {}
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise((resolve) => {
          resolveSearch = () => resolve({ ok: true, status: 200, json: async () => answered })
        }),
    ),
  )
  const { result } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('q')
  })
  act(() => {
    result.current.reset()
  })
  expect(result.current.state).toEqual({ kind: 'idle' })

  await act(async () => {
    resolveSearch(undefined)
    await Promise.resolve()
  })
  expect(result.current.state).toEqual({ kind: 'idle' })
})

test('ignores a stale response after a second ask supersedes the first', async () => {
  let resolveFirst: (value: unknown) => void = () => {}
  const fetchMock = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = () => resolve({ ok: true, status: 200, json: async () => answered })
        }),
    )
    .mockImplementationOnce(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ...answered, outcome: 'abstained', reason: 'nothing matches' }),
    }))
  vi.stubGlobal('fetch', fetchMock)

  const { result } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('first')
  })
  act(() => {
    result.current.ask('second')
  })
  await waitFor(() => expect(result.current.state.kind).toBe('abstained'))

  await act(async () => {
    resolveFirst(undefined)
    await Promise.resolve()
  })
  expect(result.current.state.kind).toBe('abstained')
})

test('clears timers on unmount without act() warnings', async () => {
  const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  const neverResolve: Promise<unknown> = new Promise(() => {})
  vi.stubGlobal(
    'fetch',
    vi.fn(() => neverResolve),
  )
  const { result, unmount } = renderHook(() => useAsk(createClient({ api: 'http://x' })))
  act(() => {
    result.current.ask('q')
  })
  unmount()

  await new Promise((r) => setTimeout(r, 700))
  expect(errorSpy).not.toHaveBeenCalled()
  errorSpy.mockRestore()
})
