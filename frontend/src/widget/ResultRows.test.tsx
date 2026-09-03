import { render, screen } from '@testing-library/react'
import { ResultRows } from './ResultRows'

test('renders a matrix as latest-value rows with a points note', () => {
  const matrix = {
    resultType: 'matrix',
    result: [
      { metric: { handler: '/a' }, values: [[1, '2'], [2, '5']] },
      { metric: { handler: '/b' }, values: [[1, '9'], [2, '3']] },
    ],
  }
  render(<ResultRows result={matrix} />)
  expect(screen.getByText('/a')).toBeInTheDocument()
  expect(screen.getByText('5')).toBeInTheDocument() // latest, not max
  expect(screen.getByText(/latest of up to 2 points/)).toBeInTheDocument()
})
