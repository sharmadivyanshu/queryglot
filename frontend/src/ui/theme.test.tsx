import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider } from './theme'
import { ThemeToggle } from '../components/ui/theme-toggle'

function setup() {
  localStorage.clear()
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  )
}

test('defaults to system preference and applies scope class', () => {
  setup()
  expect(document.documentElement.className).toMatch(/qg-(light|dark)/)
})

test('click toggles class and persists', async () => {
  setup()
  const before = document.documentElement.className
  await userEvent.click(screen.getByRole('switch'))
  expect(document.documentElement.className).not.toBe(before)
  expect(localStorage.getItem('qg-theme')).toMatch(/light|dark/)
})

test('keyboard toggles', async () => {
  setup()
  screen.getByRole('switch').focus()
  const before = screen.getByRole('switch').getAttribute('aria-checked')
  await userEvent.keyboard('{Enter}')
  expect(screen.getByRole('switch').getAttribute('aria-checked')).not.toBe(before)
})
