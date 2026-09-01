import type { CSSProperties } from 'react'
import { useTheme } from '../../ui/theme'

function MoonIcon({ color }: { color: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <path
        d="M13.5 9.5 A6 6 0 1 1 6.5 2.5 A5 5 0 0 0 13.5 9.5 Z"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function SunIcon({ color }: { color: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="3.2" stroke={color} strokeWidth="1.5" />
      <path
        d="M8 1.5 V3 M8 13 V14.5 M1.5 8 H3 M13 8 H14.5 M3.4 3.4 L4.5 4.5 M11.5 11.5 L12.6 12.6 M12.6 3.4 L11.5 4.5 M4.5 11.5 L3.4 12.6"
        stroke={color}
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  )
}

const buttonStyle: CSSProperties = {
  display: 'inline-flex',
  padding: '5px 0',
  background: 'transparent',
  border: 'none',
  cursor: 'pointer',
  appearance: 'none',
}

const pillStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  width: 68,
  height: 34,
  padding: 4,
  borderRadius: 999,
  background: 'var(--qg-surface)',
  border: '1px solid var(--qg-border)',
  boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
}

const cellBase: CSSProperties = {
  display: 'flex',
  justifyContent: 'center',
  alignItems: 'center',
  width: 26,
  height: 26,
  borderRadius: 999,
  transition: 'background-color 150ms ease',
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isDark}
      aria-label="Toggle dark mode"
      onClick={toggle}
      style={buttonStyle}
    >
      <span style={pillStyle}>
        <span style={{ ...cellBase, background: isDark ? 'var(--qg-host-soft)' : 'transparent' }}>
          <MoonIcon color="var(--qg-text)" />
        </span>
        <span
          style={{
            ...cellBase,
            marginLeft: 8,
            background: isDark ? 'transparent' : 'var(--qg-host-soft)',
          }}
        >
          <SunIcon color={isDark ? 'var(--qg-text-faint)' : 'var(--qg-text)'} />
        </span>
      </span>
    </button>
  )
}
