import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import App from './App'

test('renders status chip and schema rail from api', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () =>
        url.includes('/api/status')
          ? { backends: { prometheus: 312 }, version: '0.1.0' }
          : { items: ['go_goroutines'], fields: [{ name: 'go_goroutines', type: 'gauge', kind: 'metric', labels: [], help: '', backend: 'prometheus' }] },
    })),
  )
  render(<App />)
  await waitFor(() => expect(screen.getByText(/connected · 312 metrics/)).toBeDefined())
  expect(screen.getByText(/go_\*/)).toBeDefined()
  expect(screen.getByText('Your metrics, answerable in plain language.')).toBeDefined()
})

test('TracePanel shows real telemetry after an abstained answer, not dashes', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/api/status')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ backends: { prometheus: 312 }, version: '0.1.0' }),
        }
      }
      if (url.includes('/api/schema')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            items: ['go_goroutines'],
            fields: [{ name: 'go_goroutines', type: 'gauge', kind: 'metric', labels: [], help: '', backend: 'prometheus' }],
          }),
        }
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          outcome: 'abstained',
          backend: 'prometheus',
          query: '',
          result: null,
          reason: 'nothing in this backend schema matches',
          schema_used: ['a', 'b', 'c'],
          attempts: 2,
          elapsed_ms: 450,
        }),
      }
    }),
  )
  render(<App />)
  await waitFor(() => expect(screen.getByText(/connected · 312 metrics/)).toBeDefined())

  const input = screen.getByPlaceholderText('p95 latency by route over the last 15 minutes')
  await userEvent.type(input, 'kubernetes pod cpu usage{enter}')

  await waitFor(() => expect(screen.getByText(/3 items/)).toBeDefined())
  expect(screen.getByText(/2 attempts/)).toBeDefined()
  expect(screen.getByText(/450 ms/)).toBeDefined()
})

test('shows an unreachable status chip and schema error when the backend is down', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new Error('network error')
    }),
  )
  render(<App />)
  await waitFor(() => expect(screen.getByText(/backend unreachable/)).toBeDefined())
  expect(screen.getByText(/couldn.t load schema/)).toBeDefined()
})

test('cmd+k resets the inline panel to idle after an answer', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true, status: 200,
    json: async () => {
      if (String(url).includes('/api/status')) return { backends: { prometheus: 3 }, version: '0.1.0' }
      if (String(url).includes('/api/schema'))
        return {
          items: ['go_goroutines'],
          fields: [{ name: 'go_goroutines', type: 'gauge', kind: 'metric', labels: [], help: '', backend: 'prometheus' }],
        }
      return { outcome: 'answered', backend: 'prometheus', query: 'up', result: { resultType: 'vector', result: [] }, reason: '', schema_used: ['up'], attempts: 1, elapsed_ms: 5 }
    },
  })))
  render(<App />)
  const input = await screen.findByPlaceholderText(/Ask anything/)
  await userEvent.type(input, 'anything{Enter}')
  await waitFor(() => expect(screen.getByText(/RAN THIS EXACT QUERY/)).toBeDefined())
  await userEvent.keyboard('{Meta>}k{/Meta}')
  await waitFor(() => expect(screen.queryByText(/RAN THIS EXACT QUERY/)).toBeNull())
  expect(screen.getByText('SUGGESTED')).toBeDefined()
})

test('changing the time-range preset re-runs the last question under the new window', async () => {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.includes('/api/status')) {
      return { ok: true, status: 200, json: async () => ({ backends: { prometheus: 3 }, version: '0.1.0' }) }
    }
    if (url.includes('/api/schema')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          items: ['up'],
          fields: [{ name: 'up', type: 'gauge', kind: 'metric', labels: [], help: '', backend: 'prometheus' }],
        }),
      }
    }
    if (url.includes('/api/summary')) {
      return { ok: true, status: 200, json: async () => ({ summary: '' }) }
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({
        outcome: 'answered',
        backend: 'prometheus',
        query: 'up',
        result: { resultType: 'vector', result: [] },
        reason: '',
        schema_used: ['up'],
        attempts: 1,
        elapsed_ms: 5,
      }),
    }
  })
  vi.stubGlobal('fetch', fetchMock)

  function searchBodies() {
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit | undefined][]
    return calls
      .filter(([url]) => url.includes('/api/search'))
      .map(([, init]) => JSON.parse(init?.body as string) as Record<string, unknown>)
  }

  render(<App />)
  const input = await screen.findByPlaceholderText('p95 latency by route over the last 15 minutes')
  await userEvent.type(input, 'p95 latency{enter}')
  await waitFor(() => expect(searchBodies()).toHaveLength(1))
  expect(searchBodies()[0]).toMatchObject({ question: 'p95 latency' })
  expect(searchBodies()[0].window_minutes).toBeUndefined()

  // Instant -> Last 1 hour: re-runs the SAME question, this time pinned to
  // window_minutes 60 — proves the new window reaches the request rather
  // than the stale one `ask`'s useCallback closed over.
  await userEvent.click(screen.getByRole('button', { name: /Instant/ }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Last 1 hour' }))
  await waitFor(() => expect(searchBodies()).toHaveLength(2))
  expect(searchBodies()[1]).toMatchObject({ question: 'p95 latency', window_minutes: 60 })

  // Last 1 hour -> Instant: re-runs again with no window at all (the `null`
  // override sentinel maps back to "omit window_minutes", not "reuse 60").
  await userEvent.click(screen.getByRole('button', { name: /Last 1 hour/ }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Instant' }))
  await waitFor(() => expect(searchBodies()).toHaveLength(3))
  expect(searchBodies()[2]).toMatchObject({ question: 'p95 latency' })
  expect(searchBodies()[2].window_minutes).toBeUndefined()
})
