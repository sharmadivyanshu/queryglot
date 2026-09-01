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
    reason: 'nothing in this backend schema matches' }, suggestions: [] }} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.getByText(/Nothing in your schema answers this/)).toBeDefined()
  expect(screen.getByText(/refused to guess · 0 queries run/)).toBeDefined()
  expect(document.querySelector('[role="alert"]')).toBeNull()
})

test('abstained renders schema-derived suggestions from state, not the static idle list', () => {
  render(<Panel state={{ kind: 'abstained', answer: { ...answered.answer, outcome: 'abstained',
    reason: 'nothing in this backend schema matches' }, suggestions: ['go_goroutines', 'process_cpu_seconds_total'] }}
    onAsk={noop} onClose={noop} suggestions={['error rate in the last hour']} />)
  expect(screen.getByText('go_goroutines')).toBeDefined()
  expect(screen.getByText('process_cpu_seconds_total')).toBeDefined()
  expect(screen.queryByText('error rate in the last hour')).toBeNull()
  expect(screen.getByText(/CLOSEST YOUR SCHEMA CAN ANSWER/)).toBeDefined()
})

test('abstained hides the suggestions section when the schema search comes back empty', () => {
  render(<Panel state={{ kind: 'abstained', answer: { ...answered.answer, outcome: 'abstained',
    reason: 'nothing in this backend schema matches' }, suggestions: [] }} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.queryByText(/CLOSEST YOUR SCHEMA CAN ANSWER/)).toBeNull()
})

test('failed with zero attempts says the model was never reached, not "failed after 0 attempts"', () => {
  render(<Panel state={{ kind: 'failed', answer: { ...answered.answer, outcome: 'failed',
    attempts: 0, reason: 'engine error' } }} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.getByText(/Couldn.t reach the model — nothing was run/)).toBeDefined()
  expect(screen.queryByText(/failed after 0 attempts/)).toBeNull()
})

test('answered renders label/value rows for the wrapped prometheus vector shape', () => {
  const wrapped = {
    ...answered,
    answer: {
      ...answered.answer,
      result: {
        resultType: 'vector',
        result: [
          { metric: { __name__: 'go_goroutines', job: 'prometheus' }, value: [1788274792.48, '36'] },
        ],
      },
    },
  }
  render(<Panel state={wrapped} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.getByText('36')).toBeDefined()
  expect(screen.queryByText(/resultType/)).toBeNull()
})
