import { createContext, useContext, useLayoutEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

export type Theme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  toggle: () => void
}

const STORAGE_KEY = 'qg-theme'

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getInitialTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') {
      return stored
    }
  } catch {
    // localStorage may be blocked (private browsing, disabled storage) —
    // fall through to the media-query default.
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useLayoutEffect(() => {
    document.documentElement.className = theme === 'dark' ? 'qg-dark' : 'qg-light'
    try {
      window.localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // Blocked storage is non-fatal — theme still applies for this session.
    }
  }, [theme])

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      toggle: () => setTheme((current) => (current === 'dark' ? 'light' : 'dark')),
    }),
    [theme],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}
