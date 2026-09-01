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
          : { items: ['go_goroutines (gauge)'] },
    })),
  )
  render(<App />)
  await waitFor(() => expect(screen.getByText(/connected · 312 metrics/)).toBeDefined())
  expect(screen.getByText(/go_goroutines/)).toBeDefined()
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
        return { ok: true, status: 200, json: async () => ({ items: ['go_goroutines (gauge)'] }) }
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
      if (String(url).includes('/api/schema')) return { items: ['go_goroutines (gauge)'] }
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
