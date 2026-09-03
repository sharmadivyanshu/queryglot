import type { CSSProperties } from 'react'
import { formatValue, parseMatrix, parseVector } from '../lib/resultData'

const rowLabelStyle: CSSProperties = { fontSize: 12, color: 'var(--qg-text-mut)' }
const rowValueStyle: CSSProperties = { fontSize: '12.5px', fontWeight: 500, color: 'var(--qg-text)' }

const preStyle: CSSProperties = {
  margin: 0,
  fontSize: '11.5px',
  lineHeight: 1.6,
  color: 'var(--qg-code-text)',
  background: 'var(--qg-code-bg)',
  border: '1px solid var(--qg-border-soft)',
  borderRadius: 10,
  padding: '12px 14px',
  maxHeight: 180,
  overflow: 'auto',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
}

const emptyStyle: CSSProperties = {
  fontSize: '12.5px',
  lineHeight: 1.55,
  color: 'var(--qg-info-text)',
  background: 'var(--qg-info-bg)',
  border: '1px solid var(--qg-info-border)',
  borderRadius: 10,
  padding: '12px 14px',
}

export function ResultRows({ result: rawResult }: { result: unknown }) {
  const rows = parseVector(rawResult)
  if (rows !== null && rows.length === 0) {
    return (
      <div style={emptyStyle}>
        The query ran and was valid, but returned no data on your server.
      </div>
    )
  }
  if (rows !== null) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {rows.map((row, i) => (
          <div key={i} className="krow" style={{ background: i % 2 === 0 ? 'var(--qg-surface2)' : 'transparent' }}>
            <span className="mono" style={rowLabelStyle}>
              {row.label}
            </span>
            <span
              className="mono"
              style={
                i === 0 && rows.length > 1
                  ? { ...rowValueStyle, color: 'var(--qg-accent)', fontWeight: 600 }
                  : rowValueStyle
              }
            >
              {formatValue(row.raw)}
            </span>
          </div>
        ))}
      </div>
    )
  }
  const series = parseMatrix(rawResult)
  if (series !== null && series.length > 0) {
    const rows = series
      .map((s) => ({
        label: Object.values(s.labels).join(' ') || '(no labels)',
        raw: String(s.points[s.points.length - 1]?.[1] ?? ''),
        points: s.points.length,
      }))
      .sort((a, b) => {
        const av = Number(a.raw)
        const bv = Number(b.raw)
        return (Number.isFinite(bv) ? bv : Number.NEGATIVE_INFINITY) - (Number.isFinite(av) ? av : Number.NEGATIVE_INFINITY)
      })
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {rows.map((row, i) => (
          <div key={i} className="krow" style={{ background: i % 2 === 0 ? 'var(--qg-surface2)' : 'transparent' }}>
            <span className="mono" style={rowLabelStyle}>{row.label}</span>
            <span className="mono" style={i === 0 && rows.length > 1 ? { ...rowValueStyle, color: 'var(--qg-accent)', fontWeight: 600 } : rowValueStyle}>
              {formatValue(row.raw)}
            </span>
          </div>
        ))}
        <span style={{ fontSize: 11, color: 'var(--qg-text-faint)', padding: '4px 12px' }}>
          latest of up to {Math.max(...series.map((s) => s.points.length))} points per series
        </span>
      </div>
    )
  }
  return <pre style={preStyle}>{JSON.stringify(rawResult, null, 2)}</pre>
}
