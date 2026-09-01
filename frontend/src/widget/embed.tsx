import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createClient } from '../lib/api'
import { useAsk } from '../lib/useAsk'
import { Panel } from './Panel'
import tokensCss from '../ui/tokens.css?inline'
import panelCss from './panel.css?inline'

export type WidgetTheme = 'light' | 'dark' | 'auto'

export interface WidgetConfig {
  api: string
  theme: WidgetTheme
  token?: string
  backend?: string
}

/** v1's static default list — the mockup's three suggestions. */
const DEFAULT_SUGGESTIONS = ['error rate in the last hour', 'memory usage right now', 'slowest routes today']

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]'

/** Reads the embed script's `data-*` attributes into a widget config. Throws when `data-api` is missing. */
export function parseConfig(script: HTMLScriptElement): WidgetConfig {
  const api = script.dataset.api
  if (!api) {
    throw new Error('queryglot embed script is missing a required data-api attribute')
  }
  const theme = script.dataset.theme
  const resolvedTheme: WidgetTheme = theme === 'light' || theme === 'dark' ? theme : 'auto'
  return {
    api,
    theme: resolvedTheme,
    token: script.dataset.token,
    backend: script.dataset.backend,
  }
}

function usePrefersDark(): boolean {
  const [prefersDark, setPrefersDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)

  useEffect(() => {
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = (event: MediaQueryListEvent) => setPrefersDark(event.matches)
    mql.addEventListener('change', handleChange)
    return () => mql.removeEventListener('change', handleChange)
  }, [])

  return prefersDark
}

function resolveScopeClass(theme: WidgetTheme, prefersDark: boolean): 'qg-light' | 'qg-dark' {
  if (theme === 'auto') {
    return prefersDark ? 'qg-dark' : 'qg-light'
  }
  return theme === 'dark' ? 'qg-dark' : 'qg-light'
}

/** Cycles focus among a root's focusable elements, wrapping at the ends — a minimal, dependency-free focus trap. */
function trapFocus(event: KeyboardEvent, root: HTMLElement | null): void {
  if (!root) return
  const focusable = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => el.tabIndex !== -1,
  )
  if (focusable.length === 0) return

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const rootNode = root.getRootNode() as Document | ShadowRoot
  const active = rootNode.activeElement as HTMLElement | null

  if (event.shiftKey) {
    if (active === null || active === first || !focusable.includes(active)) {
      event.preventDefault()
      last.focus()
    }
  } else if (active === null || active === last || !focusable.includes(active)) {
    event.preventDefault()
    first.focus()
  }
}

function BrandIcon() {
  return (
    <svg width={15} height={15} viewBox="0 0 20 20" fill="none">
      <path d="M10 2 L17 6 V14 L10 18 L3 14 V6 Z" stroke="var(--qg-on-accent)" strokeWidth={1.7} />
      <circle cx={10} cy={10} r={2.4} fill="var(--qg-on-accent)" />
    </svg>
  )
}

const pillStyle: CSSProperties = {
  position: 'fixed',
  right: 28,
  bottom: 28,
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  background: 'var(--qg-accent)',
  borderRadius: 999,
  padding: '11px 18px',
  boxShadow: 'var(--qg-shadow)',
  border: 'none',
  cursor: 'pointer',
  zIndex: 2147483000,
}

const pillLabelStyle: CSSProperties = { fontSize: 13, fontWeight: 600, color: 'var(--qg-on-accent)' }

const panelContainerStyle: CSSProperties = {
  position: 'fixed',
  right: 28,
  bottom: 96,
  zIndex: 2147483000,
}

function Widget({ config }: { config: WidgetConfig }) {
  const client = useMemo(() => createClient({ api: config.api, token: config.token }), [config.api, config.token])
  const { state, ask, reset } = useAsk(client, config.backend)
  const [open, setOpen] = useState(false)
  const prefersDark = usePrefersDark()
  const scopeClass = resolveScopeClass(config.theme, prefersDark)

  const wrapperRef = useRef<HTMLDivElement>(null)
  const pillRef = useRef<HTMLButtonElement>(null)

  const close = useCallback(() => {
    setOpen(false)
    reset()
    pillRef.current?.focus()
  }, [reset])

  useEffect(() => {
    function handleKeydown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen(true)
        return
      }
      if (!open) return
      if (event.key === 'Escape') {
        close()
        return
      }
      if (event.key === 'Tab') {
        trapFocus(event, wrapperRef.current)
      }
    }
    document.addEventListener('keydown', handleKeydown)
    return () => document.removeEventListener('keydown', handleKeydown)
  }, [open, close])

  return (
    <div ref={wrapperRef} className={scopeClass}>
      {open && (
        <div style={panelContainerStyle}>
          <Panel state={state} onAsk={ask} onClose={close} suggestions={DEFAULT_SUGGESTIONS} />
        </div>
      )}
      <button ref={pillRef} type="button" onClick={() => setOpen(true)} aria-label="Ask queryglot" style={pillStyle}>
        <BrandIcon />
        <span className="disp" style={pillLabelStyle}>
          Ask
        </span>
      </button>
    </div>
  )
}

/** Mounts the widget: an open shadow root under `#queryglot-root`, tokens + panel styles injected first, themed scope, floating pill, and the four-state panel wired to `useAsk`. */
export function mount(config: WidgetConfig): void {
  if (document.getElementById('queryglot-root')) {
    console.warn('queryglot: already mounted, ignoring duplicate mount() call')
    return
  }

  const host = document.createElement('div')
  host.id = 'queryglot-root'
  document.body.appendChild(host)

  const shadow = host.attachShadow({ mode: 'open' })

  const tokensStyle = document.createElement('style')
  tokensStyle.textContent = tokensCss
  shadow.appendChild(tokensStyle)

  const panelStyle = document.createElement('style')
  panelStyle.textContent = panelCss
  shadow.appendChild(panelStyle)

  const container = document.createElement('div')
  shadow.appendChild(container)

  // The initial commit is forced synchronous so `mount()` leaves the shadow
  // root fully populated before returning — callers (and tests) never need
  // to await a scheduler flush just to see the pill.
  flushSync(() => {
    createRoot(container).render(<Widget config={config} />)
  })
}
