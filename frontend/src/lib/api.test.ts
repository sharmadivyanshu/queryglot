import { afterEach, describe, expect, it, vi } from 'vitest'
import { createClient } from './api'

function mockFetch(body: unknown) {
  const fn = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(body) })
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('client.search', () => {
  it('sends fresh only when requested', async () => {
    const fetchFn = mockFetch({ outcome: 'answered' })
    const client = createClient({ api: '' })
    await client.search('q')
    expect(JSON.parse(fetchFn.mock.calls[0][1].body as string)).toEqual({
      question: 'q',
      backend: undefined,
    })
    await client.search('q', undefined, true)
    expect(JSON.parse(fetchFn.mock.calls[1][1].body as string).fresh).toBe(true)
  })
})

describe('client.schema', () => {
  it('exposes structured fields', async () => {
    mockFetch({ items: ['up (gauge)'], fields: [{ name: 'up', type: 'gauge', kind: 'metric', labels: [], help: '', backend: 'prometheus' }] })
    const client = createClient({ api: '' })
    const response = await client.schema()
    expect(response.fields[0].name).toBe('up')
  })
})
