import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  if (mode === 'widget') {
    return {
      plugins: [react()],
      define: { 'process.env.NODE_ENV': '"production"' },
      build: {
        outDir: 'dist-widget',
        lib: {
          entry: 'src/widget/entry.tsx',
          name: 'QueryglotWidget',
          formats: ['iife'],
          fileName: () => 'widget.js',
        },
        rollupOptions: { output: { inlineDynamicImports: true } },
        cssCodeSplit: false,
      },
    }
  }
  return {
    plugins: [react()],
    server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
    test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', globals: true, css: true },
  }
})
