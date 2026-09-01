import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        qg: {
          accent: 'var(--qg-accent)',
          'on-accent': 'var(--qg-on-accent)',
          bg: 'var(--qg-bg)',
          host: 'var(--qg-host)',
          'host-soft': 'var(--qg-host-soft)',
          surface: 'var(--qg-surface)',
          surface2: 'var(--qg-surface2)',
          border: 'var(--qg-border)',
          'border-soft': 'var(--qg-border-soft)',
          text: 'var(--qg-text)',
          'text-mut': 'var(--qg-text-mut)',
          'text-faint': 'var(--qg-text-faint)',
          'code-bg': 'var(--qg-code-bg)',
          'code-text': 'var(--qg-code-text)',
          'code-kw': 'var(--qg-code-kw)',
          'kbd-bg': 'var(--qg-kbd-bg)',
          'kbd-border': 'var(--qg-kbd-border)',
          'kbd-text': 'var(--qg-kbd-text)',
          info: 'var(--qg-info)',
          'info-bg': 'var(--qg-info-bg)',
          'info-border': 'var(--qg-info-border)',
          'info-text': 'var(--qg-info-text)',
          'ok-bg': 'var(--qg-ok-bg)',
          'ok-border': 'var(--qg-ok-border)',
        },
      },
      fontFamily: {
        disp: ['Bricolage Grotesque', 'Instrument Sans', 'system-ui', 'sans-serif'],
        sans: ['Instrument Sans', 'system-ui', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        qg: 'var(--qg-shadow)',
      },
    },
  },
  plugins: [],
} satisfies Config
