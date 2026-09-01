import { render, screen } from '@testing-library/react'

test('scaffold renders', () => {
  render(<div className="qg-light">queryglot</div>)
  expect(screen.getByText('queryglot')).toBeDefined()
})
