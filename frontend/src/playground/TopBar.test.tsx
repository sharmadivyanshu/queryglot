import { render, screen } from '@testing-library/react'
import { ThemeProvider } from '../ui/theme'
import { TopBar } from './TopBar'

test('renders the live backend chip with the backend name from /api/status', () => {
  render(
    <ThemeProvider>
      <TopBar status={{ backends: { prometheus: 312 }, version: '0.1.0' }} unreachable={false} />
    </ThemeProvider>,
  )
  expect(screen.getByText('prometheus')).toBeDefined()
})

test('omits the backend chip while status has not loaded yet', () => {
  render(
    <ThemeProvider>
      <TopBar status={null} unreachable={false} />
    </ThemeProvider>,
  )
  expect(screen.queryByText('prometheus')).toBeNull()
})
