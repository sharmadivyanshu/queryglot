import { afterEach } from 'vitest'
import { parseConfig, mount } from './embed'

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
