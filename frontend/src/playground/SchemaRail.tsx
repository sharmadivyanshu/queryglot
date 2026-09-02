import { useMemo, useState } from 'react'
import type { SchemaField } from '../lib/api'

function SearchIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
      <circle cx="7" cy="7" r="4.5" stroke="var(--qg-text-faint)" strokeWidth="1.5" />
      <path d="M10.5 10.5 L14 14" stroke="var(--qg-text-faint)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

const BADGES: Record<string, { letter: string; fg: string; bg: string }> = {
  counter: { letter: 'C', fg: 'var(--t-counter)', bg: 'var(--t-counter-bg)' },
  gauge: { letter: 'G', fg: 'var(--t-gauge)', bg: 'var(--t-gauge-bg)' },
  histogram: { letter: 'H', fg: 'var(--t-hist)', bg: 'var(--t-hist-bg)' },
  summary: { letter: 'S', fg: 'var(--t-summ)', bg: 'var(--t-summ-bg)' },
}

function badgeFor(type: string) {
  return BADGES[type] ?? { letter: (type[0] ?? '?').toUpperCase(), fg: 'var(--t-other)', bg: 'var(--t-other-bg)' }
}

function TypeBadge({ type }: { type: string }) {
  const badge = badgeFor(type)
  return (
    <span
      aria-hidden="true"
      className="flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded-[5px] font-mono text-[9.5px] font-semibold"
      style={{ color: badge.fg, background: badge.bg }}
    >
      {badge.letter}
    </span>
  )
}

export interface SchemaRailProps {
  fields: SchemaField[]
  /** Total metric count from /api/status (may exceed fields.length when the fetch limit truncated). */
  total?: number
  /** True once /api/schema has rejected — shows a short inline message instead of an empty list. */
  unreachable: boolean
  /** schema_used names from the latest answered ask — drives IN LAST ANSWER (Task 6). */
  lastAnswerNames: string[]
  /** Focus the ask input pre-filled with this metric name. */
  onAskAbout: (name: string) => void
}

function FieldRow({ field, hot, onClick }: { field: SchemaField; hot: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${field.name}, ${field.type || field.kind}`}
      className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-1.5 py-[5px] text-left hover:bg-qg-surface2"
    >
      <TypeBadge type={field.type} />
      <span className={`truncate font-mono text-[12px] ${hot ? 'text-qg-text' : 'text-qg-text-mut'}`}>
        {field.name}
      </span>
    </button>
  )
}

function GroupHeader({ prefix, count, open, onToggle }: { prefix: string; count: number; open: boolean; onToggle: () => void }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open}
      className="flex w-full cursor-pointer items-center gap-1.5 px-1.5 pb-1 pt-2 text-left text-[10.5px] font-semibold tracking-[0.08em] text-qg-text-faint">
      <span aria-hidden="true" className="text-[9px]">{open ? '▾' : '▸'}</span>
      {prefix}_* <span className="font-mono font-medium tracking-normal">{count}</span>
    </button>
  )
}

function ExpandCard({ field, onAskAbout }: { field: SchemaField; onAskAbout: (name: string) => void }) {
  return (
    <div className="mx-1.5 mb-1.5 mt-0.5 flex flex-col gap-2 rounded-[11px] border border-qg-border bg-qg-surface p-3">
      <span className="break-all font-mono text-[12px] font-medium text-qg-text">{field.name}</span>
      {field.labels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {field.labels.map((label) => (
            <span key={label} className="rounded-full border border-qg-border-soft bg-qg-surface2 px-2 py-[3px] font-mono text-[10.5px] text-qg-text-mut">
              {label}
            </span>
          ))}
        </div>
      )}
      {field.help && <span className="text-[11.5px] leading-[1.5] text-qg-text-faint">{field.help}</span>}
      <button type="button" onClick={() => onAskAbout(field.name)}
        className="cursor-pointer text-left text-[11.5px] font-medium text-qg-accent">
        ↳ ask about this metric
      </button>
    </div>
  )
}

/** The 280px schema rail: typed/filterable field list from `/api/schema`, "+N more, introspected live", and the embed snippet. */
export function SchemaRail({ fields, total, unreachable, lastAnswerNames, onAskAbout }: SchemaRailProps) {
  const [filter, setFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | null>(null)
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())
  const [expandedField, setExpandedField] = useState<string | null>(null)

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const field of fields) counts.set(field.type, (counts.get(field.type) ?? 0) + 1)
    return counts
  }, [fields])

  const visible = useMemo(() => {
    const query = filter.trim().toLowerCase()
    return fields.filter(
      (field) =>
        (typeFilter === null || field.type === typeFilter) &&
        (!query || field.name.toLowerCase().includes(query) || field.help.toLowerCase().includes(query)),
    )
  }, [fields, filter, typeFilter])

  const totalCount = total ?? fields.length
  const remaining = totalCount - fields.length
  const hotNames = useMemo(() => new Set(lastAnswerNames), [lastAnswerNames])

  const filtering = filter.trim() !== '' || typeFilter !== null

  const lastAnswerFields = useMemo(
    () => lastAnswerNames
      .map((name) => fields.find((field) => field.name === name) ?? { name, type: '', kind: 'metric', labels: [], help: '', backend: '' })
      .filter((field, i, all) => all.findIndex((other) => other.name === field.name) === i),
    [fields, lastAnswerNames],
  )

  const groups = useMemo(() => {
    const map = new Map<string, SchemaField[]>()
    for (const field of visible) {
      const key = field.name.split('_')[0]
      const bucket = map.get(key)
      if (bucket) bucket.push(field)
      else map.set(key, [field])
    }
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length)
  }, [visible])

  function toggleGroup(prefix: string) {
    setOpenGroups((current) => {
      const next = new Set(current)
      if (next.has(prefix)) next.delete(prefix)
      else next.add(prefix)
      return next
    })
  }

  function toggleField(name: string) {
    setExpandedField((current) => (current === name ? null : name))
  }

  function renderRow(field: SchemaField, hot: boolean, showCard: boolean = true) {
    return (
      <div key={field.name}>
        <FieldRow field={field} hot={hot} onClick={() => toggleField(field.name)} />
        {showCard && expandedField === field.name && <ExpandCard field={field} onAskAbout={onAskAbout} />}
      </div>
    )
  }

  return (
    <div className="flex w-[280px] flex-col gap-1 border-r border-qg-border bg-qg-surface px-3 py-4">
      <div className="flex items-center justify-between px-2 pb-2">
        <span className="text-[11px] font-semibold tracking-[0.08em] text-qg-text-faint">YOUR SCHEMA</span>
        <span className="rounded-full bg-qg-surface2 px-2 py-0.5 text-[10.5px] font-medium text-qg-text-mut">
          {totalCount} fields
        </span>
      </div>
      <div className="mx-1 mb-2 flex items-center gap-2 rounded-lg border border-qg-border bg-qg-surface2 px-2.5 py-[7px]">
        <SearchIcon />
        <input
          type="text"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="filter metrics…"
            name="qg-filter" id="qg-filter"
          className="w-full border-none bg-transparent text-[12px] text-qg-text outline-none placeholder:text-qg-text-faint"
        />
      </div>
      {unreachable ? (
        <span className="p-2 text-[11px] leading-[1.5] text-qg-info-text">
          couldn&apos;t load schema — is queryglot-serve running?
        </span>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5 px-0.5 pb-1">
            <button type="button" onClick={() => setTypeFilter(null)}
              className={`cursor-pointer rounded-[7px] border px-2 py-1 font-mono text-[10.5px] ${typeFilter === null ? 'border-qg-ok-border bg-qg-ok-bg text-qg-accent' : 'border-qg-border-soft bg-qg-surface text-qg-text-mut'}`}>
              all {fields.length}
            </button>
            {[...typeCounts.entries()].map(([type, count]) => (
              <button key={type} type="button" onClick={() => setTypeFilter(typeFilter === type ? null : type)}
                className={`cursor-pointer rounded-[7px] border px-2 py-1 font-mono text-[10.5px] ${typeFilter === type ? 'border-qg-ok-border bg-qg-ok-bg text-qg-accent' : 'border-qg-border-soft bg-qg-surface text-qg-text-mut'}`}>
                {badgeFor(type).letter} {count}
              </button>
            ))}
          </div>
          <div className="flex flex-1 flex-col gap-0.5 overflow-y-auto">
            {lastAnswerFields.length > 0 && (
              <div>
                <span className="block px-1.5 pb-1 pt-2 text-[10.5px] font-semibold tracking-[0.08em] text-qg-text-faint">
                  IN LAST ANSWER <span className="font-mono font-medium tracking-normal">{lastAnswerFields.length}</span>
                </span>
                {lastAnswerFields.map((field) => renderRow(field, true))}
              </div>
            )}
            {filtering
              ? visible.map((field) => renderRow(field, hotNames.has(field.name)))
              : groups.map(([prefix, groupFields]) => (
                  <div key={prefix}>
                    <GroupHeader
                      prefix={prefix}
                      count={groupFields.length}
                      open={openGroups.has(prefix)}
                      onToggle={() => toggleGroup(prefix)}
                    />
                    {openGroups.has(prefix) && groupFields.map((field) => renderRow(field, hotNames.has(field.name), !hotNames.has(field.name)))}
                  </div>
                ))}
          </div>
        </>
      )}
      {!unreachable && remaining > 0 && (
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
