import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { Panel } from './Panel'

const noop = () => {}
const answered = { kind: 'answered' as const, answer: { outcome: 'answered' as const, backend: 'prometheus',
  query: 'histogram_quantile(0.95, rate(x[5m]))', result: [{ metric: { route: '/api/checkout' }, value: [0, '0.412'] }],
  reason: '', schema_used: ['a', 'b'], attempts: 1, elapsed_ms: 2100 } }

function answeredResponse() {
  return {
    outcome: 'answered' as const,
    backend: 'prometheus',
    query: 'histogram_quantile(0.95, rate(x[5m]))',
    result: {
      resultType: 'vector',
      result: [
        { metric: { route: '/api/checkout' }, value: [0, '0.9'] },
        { metric: { route: '/api/cart' }, value: [0, '0.4'] },
      ],
    },
    reason: '',
    schema_used: ['a', 'b'],
    attempts: 1,
    elapsed_ms: 2100,
  }
}

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

test('answered with zero rows says so instead of blank success', () => {
  const empty = {
    ...answered,
    answer: { ...answered.answer, result: { resultType: 'vector', result: [] } },
  }
  render(<Panel state={empty} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.getByText(/returned no data/i)).toBeDefined()
})

test('vector rows render sorted descending with the max first', () => {
  const multi = {
    ...answered,
    answer: {
      ...answered.answer,
      result: {
        resultType: 'vector',
        result: [
          { metric: { handler: '/small' }, value: [0, '0.05'] },
          { metric: { handler: '/big' }, value: [0, '0.9'] },
          { metric: { handler: '/mid' }, value: [0, '0.4'] },
        ],
      },
    },
  }
  render(<Panel state={multi} onAsk={noop} onClose={noop} suggestions={[]} />)
  const rows = screen.getAllByText(/\/(small|big|mid)/).map((el) => el.textContent)
  expect(rows[0]).toContain('/big')
  expect(rows[2]).toContain('/small')
})

it('renders resultView output with a chart/rows toggle, and rows when toggled', () => {
  const answer = answeredResponse()  // reuse the file's existing answered fixture builder
  render(
    <Panel state={{ kind: 'answered', answer }} onAsk={noop} onClose={noop} suggestions={[]}
      resultView={() => <div data-testid="custom-chart" />} />,
  )
  expect(screen.getByTestId('custom-chart')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'rows' }))
  expect(screen.queryByTestId('custom-chart')).not.toBeInTheDocument()
})

it('shows no toggle and plain rows when resultView is absent or returns null', () => {
  const answer = answeredResponse()
  render(
    <Panel state={{ kind: 'answered', answer }} onAsk={noop} onClose={noop} suggestions={[]}
      resultView={() => null} />,
  )
  expect(screen.queryByRole('button', { name: 'chart' })).not.toBeInTheDocument()
})

it('re-runs the question fresh from the header refresh button', () => {
  const onAsk = vi.fn()
  // Panel keeps the asked question in local state: submit a suggestion while
  // idle, then rerender the same instance in the answered state.
  const { rerender } = render(
    <Panel state={{ kind: 'idle' }} onAsk={onAsk} onClose={noop} suggestions={['slowest routes today']} />,
  )
  fireEvent.click(screen.getByRole('button', { name: /slowest routes today/ }))
  rerender(
    <Panel state={{ kind: 'answered', answer: answeredResponse() }} onAsk={onAsk} onClose={noop} suggestions={[]} />,
  )
  fireEvent.click(screen.getByRole('button', { name: 're-run this question' }))
  expect(onAsk).toHaveBeenLastCalledWith('slowest routes today', { fresh: true })
})

it('hides the refresh button when no question was asked through the panel', () => {
  render(<Panel state={{ kind: 'answered', answer: answeredResponse() }} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.queryByRole('button', { name: 're-run this question' })).not.toBeInTheDocument()
})

it('shows cache age on cached answers', () => {
  const answer = { ...answeredResponse(), cached: true, cache_age_s: 42 }
  render(<Panel state={{ kind: 'answered', answer }} onAsk={noop} onClose={noop} suggestions={[]} />)
  expect(screen.getByText(/cached 42s ago/)).toBeInTheDocument()
})
