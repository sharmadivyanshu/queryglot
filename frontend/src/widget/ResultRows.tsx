import type { CSSProperties } from 'react'

interface InstantVectorSample {
  metric: Record<string, string>
  value: [number | string, string]
}

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

/** Prometheus wraps vectors as {resultType: "vector", result: [...]} — unwrap it. */
function unwrap(result: unknown): unknown {
  if (
    typeof result === 'object' &&
    result !== null &&
    'resultType' in result &&
    (result as { resultType: unknown }).resultType === 'vector' &&
    'result' in result
  ) {
    return (result as { result: unknown }).result
  }
  return result
}

function isInstantVector(result: unknown): result is InstantVectorSample[] {
  return (
    Array.isArray(result) &&
    result.every(
      (item) =>
        typeof item === 'object' &&
        item !== null &&
        'metric' in item &&
        typeof (item as { metric: unknown }).metric === 'object' &&
        'value' in item &&
        Array.isArray((item as { value: unknown }).value),
    )
  )
}

/**
 * 3 significant figures, no invented unit — just the number as a string.
 * Falls back to the raw source text if it isn't numeric.
 */
function formatValue(raw: string): string {
  const n = Number(raw)
  if (!Number.isFinite(n)) {
    return raw
  }
  if (n === 0) {
    return '0'
  }
  return Number(n.toPrecision(3)).toString()
}

/**
 * Prometheus instant-vector rows (label = metric label values joined by a
 * space, value = the raw result string formatted to 3 sig figs). Anything
 * else falls back to pretty-printed JSON in a scrollable <pre>.
 */
const emptyStyle: CSSProperties = {
  fontSize: '12.5px',
  lineHeight: 1.55,
  color: 'var(--qg-info-text)',
  background: 'var(--qg-info-bg)',
  border: '1px solid var(--qg-info-border)',
  borderRadius: 10,
  padding: '12px 14px',
}

function numeric(sample: InstantVectorSample): number {
  const parsed = Number(sample.value[1])
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY
}

export function ResultRows({ result: rawResult }: { result: unknown }) {
  const result = unwrap(rawResult)
  if (Array.isArray(result) && result.length === 0) {
    return (
      <div style={emptyStyle}>
        The query ran and was valid, but returned no data on your server.
      </div>
    )
  }
  if (isInstantVector(result)) {
    const sorted = [...result].sort((a, b) => numeric(b) - numeric(a))
    if (result.length === 0) {
      return <span style={{ fontSize: 12, color: 'var(--qg-text-faint)' }}>No series returned.</span>
    }
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {sorted.map((sample, i) => {
          const label = Object.values(sample.metric).join(' ') || '(no labels)'
          return (
            <div key={i} className="krow" style={{ background: i % 2 === 0 ? 'var(--qg-surface2)' : 'transparent' }}>
              <span className="mono" style={rowLabelStyle}>
                {label}
              </span>
              <span
                className="mono"
                style={
                  i === 0 && sorted.length > 1
                    ? { ...rowValueStyle, color: 'var(--qg-accent)', fontWeight: 600 }
                    : rowValueStyle
                }
              >
                {formatValue(String(sample.value[1]))}
              </span>
            </div>
          )
        })}
      </div>
    )
  }

  return <pre style={preStyle}>{JSON.stringify(result, null, 2)}</pre>
}
