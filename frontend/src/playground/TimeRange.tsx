import { useEffect, useRef, useState } from 'react'

const WINDOW_PRESETS = [
  { minutes: undefined, label: 'Instant' },
  { minutes: 5, label: 'Last 5 minutes' },
  { minutes: 15, label: 'Last 15 minutes' },
  { minutes: 30, label: 'Last 30 minutes' },
  { minutes: 60, label: 'Last 1 hour' },
  { minutes: 180, label: 'Last 3 hours' },
  { minutes: 360, label: 'Last 6 hours' },
  { minutes: 1440, label: 'Last 24 hours' },
] as const

function ClockIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 4.5V8l2.5 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function RefreshIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v2.6h-2.6"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export interface TimeRangeProps {
  windowMinutes: number | undefined
  onChange: (minutes: number | undefined) => void
  onRefresh: () => void
}

export function TimeRange({ windowMinutes, onChange, onRefresh }: TimeRangeProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])
  const active = WINDOW_PRESETS.find((preset) => preset.minutes === windowMinutes) ?? WINDOW_PRESETS[0]

  useEffect(() => {
    if (!open) return
    const activeIndex = WINDOW_PRESETS.findIndex((preset) => preset.minutes === windowMinutes)
    itemRefs.current[activeIndex >= 0 ? activeIndex : 0]?.focus()
  }, [open, windowMinutes])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        return
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault()
        const count = WINDOW_PRESETS.length
        const current = itemRefs.current.findIndex((el) => el === document.activeElement)
        const delta = event.key === 'ArrowDown' ? 1 : -1
        const next = (current + delta + count) % count
        itemRefs.current[next]?.focus()
      }
    }
    const onClick = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  return (
    <div ref={rootRef} className="relative">
      <div className="flex items-stretch overflow-hidden rounded-[10px] border border-qg-border bg-qg-surface2">
        <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-haspopup="menu"
          className="flex cursor-pointer items-center gap-2 px-3 py-[7px] text-[12.5px] font-medium text-qg-text">
          <span className="text-qg-text-mut"><ClockIcon /></span>
          {active.label}
          <span aria-hidden="true" className="text-[10px] text-qg-text-faint">▾</span>
        </button>
        <button type="button" onClick={onRefresh} aria-label="Refresh"
          className="flex cursor-pointer items-center gap-1.5 border-l border-qg-border px-3 py-[7px] text-[12.5px] font-medium text-qg-accent">
          <RefreshIcon /> Refresh
        </button>
      </div>
      {open && (
        <div role="menu"
          className="absolute right-0 top-[calc(100%+6px)] z-20 flex min-w-[180px] flex-col rounded-[10px] border border-qg-border bg-qg-surface p-1 shadow-qg">
          {WINDOW_PRESETS.map((preset, index) => (
            <button key={preset.label} role="menuitem" type="button"
              ref={(el) => { itemRefs.current[index] = el }}
              onClick={() => { onChange(preset.minutes); setOpen(false) }}
              className={`cursor-pointer rounded-lg px-3 py-2 text-left text-[12.5px] ${preset.minutes === windowMinutes ? 'bg-qg-surface2 text-qg-text' : 'text-qg-text-mut hover:bg-qg-surface2'}`}>
              {preset.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
