import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TimeRange } from './TimeRange'

describe('TimeRange', () => {
  it('shows the active preset and opens the menu', () => {
    render(<TimeRange windowMinutes={30} onChange={vi.fn()} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Last 30 minutes/ }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Instant' })).toBeInTheDocument()
  })

  it('selecting a preset fires onChange and closes', () => {
    const onChange = vi.fn()
    render(<TimeRange windowMinutes={undefined} onChange={onChange} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Instant/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Last 1 hour' }))
    expect(onChange).toHaveBeenCalledWith(60)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('escape closes the menu; refresh fires onRefresh', () => {
    const onRefresh = vi.fn()
    render(<TimeRange windowMinutes={15} onChange={vi.fn()} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByRole('button', { name: /Last 15 minutes/ }))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(onRefresh).toHaveBeenCalled()
  })
})
