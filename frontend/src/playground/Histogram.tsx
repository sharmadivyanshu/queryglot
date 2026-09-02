import { useState } from 'react'
import type { MatrixSeries } from '../lib/resultData'
import { formatValue } from '../lib/resultData'

function timeLabel(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

/**
 * Bar-per-point renderer for a single range-vector series. Playground-only —
 * reaches the shared Panel through its resultView slot so the widget bundle
 * never imports it. Caps at 120 bars by slicing evenly so a long window
 * doesn't render thousands of sub-pixel bars.
 */
export function Histogram({ series, stepSeconds }: { series: MatrixSeries; stepSeconds: number }) {
  const points = series.points.length > 120
    ? series.points.filter((_, i) => i % Math.ceil(series.points.length / 120) === 0)
    : series.points
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(...points.map(([, value]) => value), 0)
  const peakIndex = points.findIndex(([, value]) => value === max)
  const first = points[0]?.[0] ?? 0
  const last = points[points.length - 1]?.[0] ?? 0
  const mid = points[Math.floor(points.length / 2)]?.[0] ?? 0
  const summary = `histogram, ${points.length} points, peak ${formatValue(String(max))} at ${timeLabel(points[peakIndex]?.[0] ?? 0)}`
  const shown = hover ?? peakIndex

  return (
    <div role="img" aria-label={summary} className="relative flex flex-col gap-1.5">
      {points[shown] && (
        <span className="self-start rounded-lg border border-qg-border bg-qg-surface px-2.5 py-1.5 font-mono text-[10.5px] text-qg-text-mut">
          <b className="font-semibold text-qg-text">{formatValue(String(points[shown][1]))}</b> · {timeLabel(points[shown][0])}
        </span>
      )}
      <div className="flex h-[120px] items-end gap-[3px] border-b border-qg-border-soft px-0.5 pt-1">
        {points.map(([, value], i) => (
          <span key={i} data-testid="qg-hist-bar"
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
            className="min-w-[3px] flex-1 rounded-t-[3px]"
            style={{ height: `${max > 0 ? Math.max((value / max) * 100, 2) : 2}%`,
              background: i === peakIndex ? 'var(--qg-bar)' : 'var(--qg-bar-soft)' }} />
        ))}
      </div>
      <div className="flex justify-between px-0.5 font-mono text-[10px] text-qg-text-faint">
        <span>{timeLabel(first)}</span><span>{timeLabel(mid)}</span><span>{timeLabel(last)}</span>
      </div>
      <span className="text-[10.5px] text-qg-text-faint">
        interval: {stepSeconds} s · {points.length} points · peak highlighted
      </span>
    </div>
  )
}
