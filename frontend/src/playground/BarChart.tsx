import type { VectorRow } from '../lib/resultData'
import { formatValue } from '../lib/resultData'

/**
 * Hand-rolled horizontal bar chart for instant vectors. Playground-only —
 * reaches the shared Panel through its resultView slot so the widget bundle
 * never imports it. Rows arrive pre-sorted descending from parseVector.
 */
export function BarChart({ rows }: { rows: VectorRow[] }) {
  const max = rows[0]?.value ?? 0
  const summary = `bar chart, ${rows.length} rows, max ${rows[0]?.label ?? ''} at ${formatValue(rows[0]?.raw ?? '')}`
  return (
    <div role="img" aria-label={summary} className="flex flex-col gap-[7px]">
      {rows.map((row, i) => {
        const width = max > 0 ? `${Math.max((row.value / max) * 100, 1.5)}%` : '1.5%'
        return (
          <div key={i} className="grid grid-cols-[168px_1fr_64px] items-center gap-2.5">
            <span className="truncate text-right font-mono text-[11.5px] text-qg-text-mut">{row.label}</span>
            <span className="h-4 overflow-hidden rounded-[5px] bg-qg-surface2">
              <span
                data-testid="qg-bar-fill"
                className="block h-full rounded-[5px]"
                style={{ width, background: i === 0 ? 'var(--qg-bar)' : 'var(--qg-bar-soft)' }}
              />
            </span>
            <span className={`font-mono text-[11.5px] ${i === 0 ? 'font-semibold text-qg-accent' : 'font-medium text-qg-text-mut'}`}>
              {formatValue(row.raw)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
