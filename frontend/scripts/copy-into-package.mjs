import { cpSync, mkdirSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import { readFileSync } from 'node:fs'

const out = '../src/queryglot/_static'
mkdirSync(out, { recursive: true })
cpSync('dist', out, { recursive: true })
cpSync('dist-widget/widget.js', `${out}/widget.js`)
const gzipped = gzipSync(readFileSync(`${out}/widget.js`)).length
console.log(`widget.js gzipped: ${(gzipped / 1024).toFixed(1)} KB`)
if (gzipped > 60 * 1024) {
  console.error('widget.js exceeds the 60KB gzip ceiling')
  process.exit(1)
}
