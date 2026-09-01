import type { CSSProperties, ReactNode } from 'react'

const kbdStyle: CSSProperties = {
  background: 'var(--qg-kbd-bg)',
  borderColor: 'var(--qg-kbd-border)',
  color: 'var(--qg-kbd-text)',
}

/** The small pill key-hint chip (⌘K, ⏎, enter, esc) from every artboard's footer/header. */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <span className="kbd" style={kbdStyle}>
      {children}
    </span>
  )
}
