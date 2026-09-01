import type { CSSProperties } from 'react'
import { Kbd } from './Kbd'

const cardStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 9,
  background: 'var(--qg-info-bg)',
  border: '1px solid var(--qg-info-border)',
  borderRadius: 12,
  padding: 15,
}

const titleStyle: CSSProperties = { fontSize: '13.5px', fontWeight: 600, color: 'var(--qg-info-text)' }
const messageStyle: CSSProperties = { fontSize: '12.5px', lineHeight: 1.55, color: 'var(--qg-text-mut)' }
const chipStyle: CSSProperties = {
  alignSelf: 'flex-start',
  background: 'var(--qg-surface)',
  color: 'var(--qg-info)',
  border: '1px solid var(--qg-info-border)',
}

const sectionLabelStyle: CSSProperties = {
  fontSize: '10.5px',
  fontWeight: 600,
  letterSpacing: '0.08em',
  color: 'var(--qg-text-faint)',
  padding: '2px 10px 6px',
}

/**
 * The calm "information, not error" card from WidgetAbstained.dc.html.
 * Reused for both the abstained state and the two failed variants (the
 * frame — icon, title, chip shape — is verbatim from the mockup; the
 * message text is the actual reason/error from the response, never the
 * mockup's illustrative "kubernetes pod metrics" copy).
 */
export function AbstainCard({
  title,
  message,
  chipText,
  suggestions = [],
  onAsk,
}: {
  title: string
  message: string
  chipText: string
  suggestions?: string[]
  onAsk: (question: string) => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
            <circle cx="9" cy="9" r="7" stroke="var(--qg-info)" strokeWidth="1.5" />
            <path d="M9 5.5 V9.5" stroke="var(--qg-info)" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="9" cy="12.4" r="0.9" fill="var(--qg-info)" />
          </svg>
          <span className="disp" style={titleStyle}>
            {title}
          </span>
        </div>
        <span style={messageStyle}>{message}</span>
        <span className="chip" style={chipStyle}>
          {chipText}
        </span>
      </div>
      {suggestions.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={sectionLabelStyle}>CLOSEST YOUR SCHEMA CAN ANSWER</span>
          {suggestions.map((suggestion, i) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => onAsk(suggestion)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '9px 10px',
                borderRadius: 9,
                background: i === 0 ? 'var(--qg-surface2)' : 'transparent',
                border: 'none',
                cursor: 'pointer',
                textAlign: 'left',
                width: '100%',
              }}
            >
              <span style={{ fontSize: 13, color: i === 0 ? 'var(--qg-text)' : 'var(--qg-text-mut)', flexGrow: 1 }}>{suggestion}</span>
              {i === 0 && <Kbd>⏎</Kbd>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
