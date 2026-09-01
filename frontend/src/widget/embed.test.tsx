import { afterEach, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { parseConfig, mount } from './embed'

const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!

function typeAndSubmit(input: HTMLInputElement, value: string) {
  nativeInputValueSetter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
}

afterEach(() => { document.getElementById('queryglot-root')?.remove() })

function scriptWith(attrs: Record<string, string>) {
  const s = document.createElement('script')
  Object.entries(attrs).forEach(([k, v]) => s.setAttribute(`data-${k}`, v))
  return s
}

test('parseConfig requires data-api and defaults theme to auto', () => {
  expect(() => parseConfig(scriptWith({}))).toThrow(/data-api/)
  const config = parseConfig(scriptWith({ api: 'http://x' }))
  expect(config).toEqual({ api: 'http://x', theme: 'auto', token: undefined, backend: undefined })
})

test('mount attaches a shadow root with themed scope and pill', () => {
  mount({ api: 'http://x', theme: 'dark' })
  const host = document.getElementById('queryglot-root')!
  expect(host.shadowRoot).not.toBeNull()
  const scope = host.shadowRoot!.querySelector('.qg-dark')
  expect(scope).not.toBeNull()
  expect(host.shadowRoot!.textContent).toContain('Ask')
})

test('mount is idempotent — a second call does not create a second host', () => {
  mount({ api: 'http://x', theme: 'light' })
  mount({ api: 'http://x', theme: 'light' })
  expect(document.querySelectorAll('#queryglot-root').length).toBe(1)
})

test('cmd+k opens the panel, esc closes it', async () => {
  mount({ api: 'http://x', theme: 'light' })
  const root = document.getElementById('queryglot-root')!.shadowRoot!
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }))
  await new Promise(requestAnimationFrame)
  expect(root.textContent).toContain('refuses to guess')
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  await new Promise(requestAnimationFrame)
  expect(root.textContent).not.toContain('refuses to guess')
})

test('cmd+k while already open resets an answered panel back to idle and refocuses the input', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        outcome: 'answered',
        backend: 'prometheus',
        query: 'up',
        result: [],
        reason: '',
        schema_used: ['up'],
        attempts: 1,
        elapsed_ms: 900,
      }),
    })),
  )

  mount({ api: 'http://x', theme: 'light' })
  const root = document.getElementById('queryglot-root')!.shadowRoot!

  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }))
  await new Promise(requestAnimationFrame)

  const input = root.querySelector('input') as HTMLInputElement
  typeAndSubmit(input, 'up')
  await waitFor(() => expect(root.textContent).toContain('grounded in'))

  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }))
  await new Promise(requestAnimationFrame)

  expect(root.textContent).toContain('refuses to guess')
  const refocused = root.querySelector('input') as HTMLInputElement
  await waitFor(() => expect(root.activeElement).toBe(refocused))

  vi.unstubAllGlobals()
})
