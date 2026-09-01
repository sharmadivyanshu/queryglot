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

const chipBase =
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium'

/** Top bar: logo + wordmark, "playground" chip, live status chip from /api/status, ThemeToggle. 60px per the mockup. */
export function TopBar({ status }: { status: StatusResponse | null }) {
  return (
    <div className="flex h-[60px] items-center gap-3.5 border-b border-qg-border bg-qg-surface px-6">
      <LogoMark />
      <span className="font-disp text-[16px] font-bold tracking-[-0.01em] text-qg-text">queryglot</span>
      <span className={`${chipBase} border-qg-border bg-qg-surface2 text-qg-text-mut`}>playground</span>
      <div className="ml-auto flex items-center gap-2.5">
        {status ? (
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
