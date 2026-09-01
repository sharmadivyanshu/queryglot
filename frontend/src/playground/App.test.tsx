import { render, screen, waitFor } from '@testing-library/react'
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
