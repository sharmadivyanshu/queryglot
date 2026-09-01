import { render, screen } from '@testing-library/react'
import { Panel } from './Panel'

const noop = () => {}
const answered = { kind: 'answered' as const, answer: { outcome: 'answered' as const, backend: 'prometheus',
  query: 'histogram_quantile(0.95, rate(x[5m]))', result: [{ metric: { route: '/api/checkout' }, value: [0, '0.412'] }],
  reason: '', schema_used: ['a', 'b'], attempts: 1, elapsed_ms: 2100 } }

test('idle shows suggestions and grounding note', () => {
  render(<Panel state={{ kind: 'idle' }} onAsk={noop} onClose={noop} suggestions={['error rate in the last hour']} />)
  expect(screen.getByText('error rate in the last hour')).toBeDefined()
  expect(screen.getByText(/refuses to guess/)).toBeDefined()
})

test('answered shows the exact query and validation chip', () => {
  render(<Panel state={answered} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.getByText(/RAN THIS EXACT QUERY/)).toBeDefined()
  expect(screen.getByText(/validated by your server/)).toBeDefined()
  expect(screen.getByText(/histogram_quantile/)).toBeDefined()
  expect(screen.getByText(/grounded in 2 schema items · 1 attempt/)).toBeDefined()
})

test('thinking renders four stages with aria-live', () => {
  render(<Panel state={{ kind: 'thinking', stage: 1 }} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.getByText(/Writing the query/)).toBeDefined()
  expect(document.querySelector('[aria-live="polite"]')).not.toBeNull()
})

test('abstained is information, not error', () => {
  render(<Panel state={{ kind: 'abstained', answer: { ...answered.answer, outcome: 'abstained',
    reason: 'nothing in this backend schema matches' } }} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.getByText(/Nothing in your schema answers this/)).toBeDefined()
  expect(screen.getByText(/refused to guess · 0 queries run/)).toBeDefined()
  expect(document.querySelector('[role="alert"]')).toBeNull()
})
