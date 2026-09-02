/**
 * Shared parsing for Prometheus result payloads. Lives in lib/ (not widget/)
 * because both the widget's ResultRows and the playground's chart renderers
 * consume it — the chart code itself must never enter the widget bundle,
 * but this parsing is shared and tiny.
 */

export interface WindowInfo {
  minutes: number
  step_s: number
}

interface InstantVectorSample {
  metric: Record<string, string>
  value: [number | string, string]
}

export interface MatrixSeries {
  labels: Record<string, string>
  points: [number, number][]
}

interface MatrixSample {
  metric: Record<string, string>
  values: [number | string, string][]
}

export interface VectorRow {
  label: string
  value: number
  raw: string
}

function unwrap(result: unknown, resultType: string): unknown | null {
  if (
    typeof result === 'object' &&
    result !== null &&
    'resultType' in result &&
    (result as { resultType: unknown }).resultType === resultType &&
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

function isMatrix(result: unknown): result is MatrixSample[] {
  return (
    Array.isArray(result) &&
    result.every(
      (item) =>
        typeof item === 'object' &&
        item !== null &&
        'metric' in item &&
        'values' in item &&
        Array.isArray((item as { values: unknown }).values),
    )
  )
}

export function formatValue(raw: string): string {
  const n = Number(raw)
  if (!Number.isFinite(n)) return raw
  if (n === 0) return '0'
  return Number(n.toPrecision(3)).toString()
}

export function parseVector(result: unknown): VectorRow[] | null {
  const inner = unwrap(result, 'vector')
  if (!isInstantVector(inner)) return null
  return inner
    .map((sample) => {
      const parsed = Number(sample.value[1])
      return {
        label: Object.values(sample.metric).join(' ') || '(no labels)',
        value: Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY,
        raw: String(sample.value[1]),
      }
    })
    .sort((a, b) => b.value - a.value)
}

export function parseMatrix(result: unknown): MatrixSeries[] | null {
  if (
    typeof result !== 'object' ||
    result === null ||
    (result as { resultType?: unknown }).resultType !== 'matrix'
  ) {
    return null
  }
  const inner = unwrap(result, 'matrix')
  if (!isMatrix(inner)) return null
  return inner.map((series) => ({
    labels: series.metric,
    points: series.values.map(([t, v]) => [Number(t), Number(v)] as [number, number]),
  }))
}
