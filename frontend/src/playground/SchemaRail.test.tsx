import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SchemaRail } from './SchemaRail'
import type { SchemaField } from '../lib/api'

const f = (name: string, type: string, labels: string[] = [], help = ''): SchemaField => ({
  name, type, kind: 'metric', labels, help, backend: 'prometheus',
})

const FIELDS = [
  f('go_goroutines', 'gauge'),
  f('go_gc_duration_seconds', 'summary'),
  f('prometheus_http_requests_total', 'counter'),
  f('prometheus_http_request_duration_seconds', 'histogram', ['handler', 'le'], 'Latencies.'),
]

const noop = () => {}

describe('SchemaRail', () => {
  it('shows the field count and one type badge per row', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    expect(screen.getByText('4 fields')).toBeInTheDocument()
    expect(screen.getByText('H')).toBeInTheDocument()
    expect(screen.getByText('S')).toBeInTheDocument()
  })

  it('type chips filter the list', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    fireEvent.click(screen.getByRole('button', { name: /C 1/ }))
    expect(screen.getByText('prometheus_http_requests_total')).toBeInTheDocument()
    expect(screen.queryByText('go_goroutines')).not.toBeInTheDocument()
  })

  it('text filter flattens and narrows', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    fireEvent.change(screen.getByPlaceholderText('filter metrics…'), { target: { value: 'goroutines' } })
    expect(screen.getByText('go_goroutines')).toBeInTheDocument()
    expect(screen.queryByText('prometheus_http_requests_total')).not.toBeInTheDocument()
  })

  it('row accessible name includes the type word (badge is decoration)', () => {
    render(<SchemaRail fields={FIELDS} total={4} status={null} unreachable={false} lastAnswerNames={[]} onAskAbout={noop} />)
    expect(screen.getByRole('button', { name: /go_goroutines.*gauge/ })).toBeInTheDocument()
  })
})
