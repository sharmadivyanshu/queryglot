import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BarChart } from './BarChart'

const ROWS = [
  { label: '/api/v1/series', value: 26.8, raw: '26.842' },
  { label: '/metrics', value: 0.667, raw: '0.667' },
]

describe('BarChart', () => {
  it('renders one labelled bar per row with a summary aria-label', () => {
    render(<BarChart rows={ROWS} />)
    expect(screen.getByText('/api/v1/series')).toBeInTheDocument()
    expect(screen.getByText('26.8')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /2 rows.*\/api\/v1\/series.*26.8/ })).toBeInTheDocument()
  })

  it('scales bar widths against the max', () => {
    render(<BarChart rows={ROWS} />)
    const fills = document.querySelectorAll('[data-testid="qg-bar-fill"]')
    expect((fills[0] as HTMLElement).style.width).toBe('100%')
    expect(parseFloat((fills[1] as HTMLElement).style.width)).toBeLessThan(5)
  })

  it('handles -Infinity values in bars (sorted to the end)', () => {
    const rowsWithInfinity = [
      { label: '/api/v1/series', value: 26.8, raw: '26.842' },
      { label: '/invalid', value: Number.NEGATIVE_INFINITY, raw: 'NaN' },
    ]
    render(<BarChart rows={rowsWithInfinity} />)
    expect(screen.getByText('/api/v1/series')).toBeInTheDocument()
    expect(screen.getByText('/invalid')).toBeInTheDocument()
    // The -Infinity bar renders with 1.5% width (fallback for zero/negative max)
    const fills = document.querySelectorAll('[data-testid="qg-bar-fill"]')
    expect(parseFloat((fills[1] as HTMLElement).style.width)).toBe(1.5)
  })
})
