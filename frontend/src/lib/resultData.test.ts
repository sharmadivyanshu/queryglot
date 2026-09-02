import { describe, expect, it } from 'vitest'
import { formatValue, parseVector } from './resultData'

const sample = (labels: Record<string, string>, v: string) => ({ metric: labels, value: [1, v] })

describe('parseVector', () => {
  it('unwraps the prometheus envelope and sorts descending', () => {
    const result = {
      resultType: 'vector',
      result: [sample({ handler: '/metrics' }, '0.7'), sample({ handler: '/api' }, '26.8')],
    }
    const rows = parseVector(result)
    expect(rows).not.toBeNull()
    expect(rows![0]).toEqual({ label: '/api', value: 26.8, raw: '26.8' })
    expect(rows![1].label).toBe('/metrics')
  })

  it('joins multi-label metrics with spaces and defaults empty labels', () => {
    const rows = parseVector([sample({ a: 'x', b: 'y' }, '1'), sample({}, '2')])
    expect(rows![1].label).toBe('x y')
    expect(rows![0].label).toBe('(no labels)')
  })

  it('returns null for scalars, matrices, and garbage', () => {
    expect(parseVector({ resultType: 'matrix', result: [] })).toBeNull()
    expect(parseVector(42)).toBeNull()
    expect(parseVector('nope')).toBeNull()
  })

  it('returns an empty array for an empty vector (caller shows the empty state)', () => {
    expect(parseVector({ resultType: 'vector', result: [] })).toEqual([])
  })

  it('maps non-numeric values to -Infinity so charts can reject them', () => {
    const rows = parseVector([sample({ label: 'a' }, 'NaN'), sample({ label: 'b' }, '42')])
    expect(rows).not.toBeNull()
    expect(rows![0]).toEqual({ label: 'b', value: 42, raw: '42' })  // sorted descending
    expect(rows![1].value).toBe(Number.NEGATIVE_INFINITY)
  })
})

describe('formatValue', () => {
  it('rounds to 3 significant figures', () => {
    expect(formatValue('26.8421')).toBe('26.8')
    expect(formatValue('0.010370076')).toBe('0.0104')
  })
  it('passes zero and non-numeric through', () => {
    expect(formatValue('0')).toBe('0')
    expect(formatValue('NaN-ish')).toBe('NaN-ish')
  })
})
