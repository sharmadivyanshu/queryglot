import type { CSSProperties } from 'react'

// PromQL keywords the mockup renders in the "keyword" ink (codeKw). Matched
// as whole words so identifiers like `my_rate_total` are left alone.
const KEYWORDS = [
  'histogram_quantile',
  'quantile',
  'rate',
  'irate',
  'increase',
  'sum',
  'avg',
  'count',
  'min',
  'max',
  'by',
  'without',
  'on',
  'ignoring',
  'group_left',
  'group_right',
  'offset',
]
const KEYWORD_RE = new RegExp(`\\b(${KEYWORDS.join('|')})\\b`, 'g')

const labelStyle: CSSProperties = {
  fontSize: '10.5px',
  fontWeight: 600,
  letterSpacing: '0.08em',
  color: 'var(--qg-text-faint)',
}

const chipStyle: CSSProperties = {
  background: 'var(--qg-ok-bg)',
  color: 'var(--qg-accent)',
  border: '1px solid var(--qg-ok-border)',
}

const codeStyle: CSSProperties = {
  fontSize: '11.5px',
  lineHeight: 1.6,
  color: 'var(--qg-code-text)',
  background: 'var(--qg-code-bg)',
  border: '1px solid var(--qg-border-soft)',
  borderRadius: 10,
  padding: '12px 14px',
  wordBreak: 'break-all',
}

/** Splits a PromQL string into keyword / plain segments for the two-tone mono highlight. */
function highlight(query: string) {
  const parts: { text: string; keyword: boolean }[] = []
  let lastIndex = 0
  for (const match of query.matchAll(KEYWORD_RE)) {
    const index = match.index ?? 0
    if (index > lastIndex) {
      parts.push({ text: query.slice(lastIndex, index), keyword: false })
    }
    parts.push({ text: match[0], keyword: true })
    lastIndex = index + match[0].length
  }
  if (lastIndex < query.length) {
    parts.push({ text: query.slice(lastIndex), keyword: false })
  }
  return parts
}

/** "RAN THIS EXACT QUERY" label + validated chip + syntax-tinted mono block, from Main.dc.html. */
export function QueryBlock({ query, suffix }: { query: string; suffix?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={labelStyle}>RAN THIS EXACT QUERY</span>
        {suffix && <span style={{ fontSize: '10.5px', color: 'var(--qg-text-faint)' }}>{suffix}</span>}
        <span className="chip" style={chipStyle}>
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <path
              d="M1.5 5.5 L4 8 L8.5 2.5"
              stroke="var(--qg-accent)"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          validated by your server
        </span>
      </div>
      <div className="mono" style={codeStyle}>
        {highlight(query).map((part, i) =>
          part.keyword ? (
            <span key={i} style={{ color: 'var(--qg-code-kw)' }}>
              {part.text}
            </span>
          ) : (
            <span key={i}>{part.text}</span>
          ),
        )}
      </div>
    </div>
  )
}
