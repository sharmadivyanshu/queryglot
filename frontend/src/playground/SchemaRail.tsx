import { useMemo, useState } from 'react'
import type { StatusResponse } from '../lib/api'

function totalMetricsOf(status: StatusResponse): number {
  return Object.values(status.backends).reduce((sum, count) => sum + count, 0)
}

function SearchIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
      <circle cx="7" cy="7" r="4.5" stroke="var(--qg-text-faint)" strokeWidth="1.5" />
      <path d="M10.5 10.5 L14 14" stroke="var(--qg-text-faint)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

export interface SchemaRailProps {
  /** Raw items from `/api/schema` (limit 50) — filtering below is client-side. */
  items: string[]
  status: StatusResponse | null
  /** True once /api/schema has rejected — shows a short inline message instead of an empty list. */
  unreachable: boolean
}

/** The 280px schema rail: filterable metric list from `/api/schema`, "+N more, introspected live", and the embed snippet. */
export function SchemaRail({ items, status, unreachable }: SchemaRailProps) {
  const [filter, setFilter] = useState('')

  const filtered = useMemo(() => {
    const query = filter.trim().toLowerCase()
    if (!query) return items
    return items.filter((item) => item.toLowerCase().includes(query))
  }, [items, filter])

  const total = status ? totalMetricsOf(status) : undefined
  const remaining = total !== undefined ? total - items.length : undefined

  return (
    <div className="flex w-[280px] flex-col gap-1 border-r border-qg-border bg-qg-surface px-3 py-4">
      <span className="px-2 pb-2 text-[11px] font-semibold tracking-[0.08em] text-qg-text-faint">YOUR SCHEMA</span>
      <div className="mx-1 mb-2 flex items-center gap-2 rounded-lg border border-qg-border bg-qg-surface2 px-2.5 py-[7px]">
        <SearchIcon />
        <input
          type="text"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="filter metrics…"
          className="w-full border-none bg-transparent text-[12px] text-qg-text outline-none placeholder:text-qg-text-faint"
        />
      </div>
      {unreachable ? (
        <span className="p-2 text-[11px] leading-[1.5] text-qg-info-text">
          couldn&apos;t load schema — is queryglot-serve running?
        </span>
      ) : (
        <div className="flex flex-1 flex-col gap-0.5 overflow-y-auto">
          {filtered.map((item) => (
            <div key={item} className="flex items-center justify-between rounded-lg px-3 py-2">
              <span className="font-mono text-[11.5px] text-qg-text-mut">{item}</span>
            </div>
          ))}
        </div>
      )}
      {!unreachable && remaining !== undefined && remaining > 0 && (
        <span className="p-2 text-[11px] text-qg-text-faint">+{remaining} more, introspected live</span>
      )}
      <div className="mt-auto flex flex-col gap-1.5 rounded-[10px] border border-qg-border bg-qg-surface2 p-3">
        <span className="text-[11px] font-semibold text-qg-text-mut">EMBED THIS ON YOUR SITE</span>
        <span className="break-all font-mono text-[10.5px] text-qg-code-text">
          {'<script src="queryglot.js" data-api="…">'}
        </span>
      </div>
    </div>
  )
}
