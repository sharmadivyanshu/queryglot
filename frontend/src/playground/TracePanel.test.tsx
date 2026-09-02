import { render, screen } from '@testing-library/react'
import { TracePanel } from './TracePanel'

function answeredResponse() {
  return {
    outcome: 'answered' as const,
    backend: 'prometheus',
    query: 'histogram_quantile(0.95, rate(x[5m]))',
    result: {
      resultType: 'vector',
      result: [{ metric: { route: '/api/checkout' }, value: [0, '0.9'] }],
    },
    reason: '',
    schema_used: ['a', 'b'],
    attempts: 1,
    elapsed_ms: 2100,
  }
}

test('shows dashes for every stage before an answer lands', () => {
  render(<TracePanel />)
  expect(screen.getAllByText('–')).toHaveLength(4)
})

test('shows real telemetry once an answer lands', () => {
  render(<TracePanel answer={answeredResponse()} />)
  expect(screen.getByText('2 items')).toBeInTheDocument()
  expect(screen.getByText('1 attempt')).toBeInTheDocument()
  expect(screen.getByText('2100 ms')).toBeInTheDocument()
})

test('labels execution as query_range with the window', () => {
  const answer = { ...answeredResponse(), window: { minutes: 30, step_s: 15 } }
  render(<TracePanel answer={answer} />)
  expect(screen.getByText('query_range · 30 min')).toBeInTheDocument()
  expect(screen.getByText(/window came from the picker/)).toBeInTheDocument()
})
