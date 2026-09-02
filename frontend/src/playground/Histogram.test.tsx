import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Histogram } from './Histogram'

const SERIES = {
  labels: { handler: '/api' },
  points: [[100, 10], [130, 84.2], [160, 31.5]] as [number, number][],
}

describe('Histogram', () => {
  it('renders one bar per point with a summary aria-label naming the peak', () => {
    render(<Histogram series={SERIES} stepSeconds={30} />)
    expect(document.querySelectorAll('[data-testid="qg-hist-bar"]')).toHaveLength(3)
    expect(screen.getByRole('img', { name: /3 points.*peak 84.2/ })).toBeInTheDocument()
  })

  it('notes the interval and point count', () => {
    render(<Histogram series={SERIES} stepSeconds={30} />)
    expect(screen.getByText(/interval: 30 s · 3 points · peak highlighted/)).toBeInTheDocument()
  })
})
