import type { ReactNode } from 'react'
import type { StatusResponse } from '../lib/api'
import { ThemeToggle } from '../components/ui/theme-toggle'

function LogoMark() {
  return (
    <svg width="22" height="22" viewBox="0 0 20 20" fill="none">
      <path d="M10 2 L17 6 V14 L10 18 L3 14 V6 Z" stroke="var(--qg-accent)" strokeWidth="1.6" />
      <circle cx="10" cy="10" r="2.4" fill="var(--qg-accent)" />
    </svg>
  )
}

function totalMetricsOf(status: StatusResponse): number {
  return Object.values(status.backends).reduce((sum, count) => sum + count, 0)
}

function backendNamesOf(status: StatusResponse): string {
  return Object.keys(status.backends).join(', ')
}

const chipBase =
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium'

export interface TopBarProps {
  status: StatusResponse | null
  /** True once /api/status has rejected — distinct from still-loading, so a down backend never reads as "connecting…" forever. */
  unreachable: boolean
  /** Playground-only extras (e.g. TimeRange) rendered in the right cluster, before the backend chips. Keeps TopBar itself dumb. */
  children?: ReactNode
}

/** Top bar: logo + wordmark, "playground" chip, live status chip from /api/status, ThemeToggle. 60px per the mockup. */
export function TopBar({ status, unreachable, children }: TopBarProps) {
  return (
    <div className="flex h-[60px] items-center gap-3.5 border-b border-qg-border bg-qg-surface px-6">
      <LogoMark />
      <span className="font-disp text-[16px] font-bold tracking-[-0.01em] text-qg-text">queryglot</span>
      <span className={`${chipBase} border-qg-border bg-qg-surface2 text-qg-text-mut`}>playground</span>
      <div className="ml-auto flex items-center gap-2.5">
        {children}
        {status && backendNamesOf(status) && (
          <div className="flex items-center gap-2 rounded-lg border border-qg-border bg-qg-surface2 px-3 py-[7px]">
            <span className="h-[7px] w-[7px] rounded-full bg-qg-accent" />
            <span className="font-mono text-[12px] text-qg-text-mut">{backendNamesOf(status)}</span>
          </div>
        )}
        {unreachable ? (
          <span className={`${chipBase} border-qg-info-border bg-qg-info-bg text-qg-info-text`}>
            backend unreachable
          </span>
        ) : status ? (
          <span className={`${chipBase} border-qg-ok-border bg-qg-ok-bg text-qg-accent`}>
            connected · {totalMetricsOf(status)} metrics
          </span>
        ) : (
          <span className={`${chipBase} border-qg-border bg-qg-surface2 text-qg-text-faint`}>connecting…</span>
        )}
        <ThemeToggle />
      </div>
    </div>
  )
}
