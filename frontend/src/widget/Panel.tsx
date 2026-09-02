import { useCallback, useState } from 'react'
import type { CSSProperties, KeyboardEvent, ReactNode } from 'react'
import type { AskState } from '../lib/useAsk'
import type { SearchResponse } from '../lib/api'
import { QueryBlock } from './QueryBlock'
import { ResultRows } from './ResultRows'
import { PipelineStages } from './PipelineStages'
import { AbstainCard } from './AbstainCard'
import { Kbd } from './Kbd'
import './panel.css'

export interface PanelProps {
  state: AskState
  onAsk: (question: string, opts?: { fresh?: boolean }) => void
  onClose: () => void
  suggestions: string[]
  /** True when embedded inline in a page (e.g. the playground), rather than floating over a host site. */
  inline?: boolean
  /** Playground-only alternative renderer for an answered result. Receives the
   *  raw answer; returning null falls back to ResultRows, so the slot never
   *  has to handle shapes it doesn't recognise. Widget builds leave it unset
   *  and the chart code is tree-shaken out of the bundle. */
  resultView?: (answer: SearchResponse) => ReactNode | null
}

const sectionLabelStyle: CSSProperties = {
  fontSize: '10.5px',
  fontWeight: 600,
  letterSpacing: '0.08em',
  color: 'var(--qg-text-faint)',
}

function SearchIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
      <circle cx="7" cy="7" r="4.5" stroke="var(--qg-text-faint)" strokeWidth="1.5" />
      <path d="M10.5 10.5 L14 14" stroke="var(--qg-text-faint)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function TrendIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <path d="M2 12 L6 7 L9 10 L14 4" stroke="var(--qg-accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function ShieldIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path d="M6 1 L10.5 3.5 V8.5 L6 11 L1.5 8.5 V3.5 Z" stroke="var(--qg-text-faint)" strokeWidth="1.2" />
    </svg>
  )
}

function RefreshIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v2.6h-2.6"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function BrandIcon({ color }: { color: string }) {
  return (
    <svg width="13" height="13" viewBox="0 0 20 20" fill="none">
      <path d="M10 2 L17 6 V14 L10 18 L3 14 V6 Z" stroke={color} strokeWidth="1.6" />
      <circle cx="10" cy="10" r="2.4" fill={color} />
    </svg>
  )
}

const headerRowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '14px 16px',
  borderBottom: '1px solid var(--qg-border-soft)',
}

const footerStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  padding: '10px 16px',
  borderTop: '1px solid var(--qg-border-soft)',
}

const hintTextStyle: CSSProperties = { fontSize: 11, color: 'var(--qg-text-faint)' }

function Footer() {
  return (
    <div style={footerStyle}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <Kbd>enter</Kbd>
        <span style={hintTextStyle}>ask</span>
      </span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <Kbd>esc</Kbd>
        <span style={hintTextStyle}>close</span>
      </span>
      <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <BrandIcon color="var(--qg-accent)" />
        <span className="disp" style={{ fontSize: 11, fontWeight: 600, color: 'var(--qg-text-faint)' }}>
          queryglot
        </span>
      </span>
    </div>
  )
}

function formatElapsed(elapsedMs: number): string {
  return `${(elapsedMs / 1000).toFixed(1)} s`
}

/**
 * The floating widget panel: idle (input + suggestions), thinking (four
 * pipeline stages), answered (exact query + result rows), and abstained /
 * failed (calm information card, never an error). Pure presentational;
 * styling is inline style objects plus the shared class helpers in
 * `panel.css` — no Tailwind inside the widget tree.
 */
export function Panel({ state, onAsk, onClose, suggestions, inline = false, resultView }: PanelProps) {
  const [question, setQuestion] = useState('')

  // The chart/rows toggle resets to 'chart' whenever a new answer lands.
  // Adjusts state during render rather than in an effect (react.dev/learn/
  // you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes) —
  // the reset must land before this render paints, and the repo's React
  // Compiler lint rule flags a bare set-state-in-effect for this case.
  const [view, setView] = useState<'chart' | 'rows'>('chart')
  const [viewedState, setViewedState] = useState(state)
  if (state !== viewedState) {
    setViewedState(state)
    setView('chart')
  }

  const submit = useCallback(
    (q: string) => {
      const trimmed = q.trim()
      if (!trimmed) return
      setQuestion(trimmed)
      onAsk(trimmed)
    },
    [onAsk],
  )

  const handleInputKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'Enter') {
        submit(question)
      } else if (event.key === 'Escape') {
        onClose()
      }
    },
    [submit, question, onClose],
  )

  const outerStyle: CSSProperties = inline
    ? {
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        maxWidth: 480,
        background: 'var(--qg-surface)',
        border: '1px solid var(--qg-border)',
        borderRadius: 14,
      }
    : {
        display: 'flex',
        flexDirection: 'column',
        width: 416,
        background: 'var(--qg-surface)',
        border: '1px solid var(--qg-border)',
        borderRadius: 14,
        boxShadow: 'var(--qg-shadow)',
      }

  return (
    <div className="qg-panel" style={outerStyle}>
      {state.kind === 'idle' ? (
        <div style={headerRowStyle}>
          <SearchIcon />
          <input
            type="text"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="Ask anything about your live metrics…"
            name="qg-panel-ask"
            autoFocus
            style={{
              flexGrow: 1,
              fontSize: 14,
              color: 'var(--qg-text)',
              background: 'transparent',
              border: 'none',
              outline: 'none',
            }}
          />
          <Kbd>⌘K</Kbd>
        </div>
      ) : (
        <div style={headerRowStyle}>
          <SearchIcon />
          <span style={{ fontSize: 14, color: 'var(--qg-text)', flexGrow: 1 }}>{question}</span>
          {state.kind === 'answered' && question && (
            <button type="button" aria-label="re-run this question"
              onClick={() => onAsk(question, { fresh: true })}
              style={{ width: 26, height: 26, borderRadius: 7, border: '1px solid var(--qg-border)',
                background: 'var(--qg-surface2)', color: 'var(--qg-text-mut)', cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
              <RefreshIcon />
            </button>
          )}
          {state.kind === 'answered' && <Kbd>⌘K</Kbd>}
        </div>
      )}

      <div aria-live="polite" aria-atomic="false" className="qg-anim" key={state.kind}>
        {state.kind === 'idle' && (
          <div style={{ padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ ...sectionLabelStyle, padding: '4px 10px' }}>SUGGESTED</span>
            {suggestions.map((suggestion, i) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => submit(suggestion)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '7px 10px',
                  minHeight: 44,
                  boxSizing: 'border-box',
                  borderRadius: 9,
                  background: i === 0 ? 'var(--qg-surface2)' : 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  textAlign: 'left',
                  width: '100%',
                }}
              >
                {i === 0 ? (
                  <TrendIcon />
                ) : (
                  <span style={{ width: 14, height: 14, flexShrink: 0 }} aria-hidden="true" />
                )}
                <span style={{ fontSize: 13, color: i === 0 ? 'var(--qg-text)' : 'var(--qg-text-mut)', flexGrow: 1 }}>
                  {suggestion}
                </span>
                {i === 0 && <Kbd>⏎</Kbd>}
              </button>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 10px 4px' }}>
              <ShieldIcon />
              <span style={{ fontSize: 11, color: 'var(--qg-text-faint)' }}>
                Answers only from your schema — it refuses to guess.
              </span>
            </div>
          </div>
        )}

        {state.kind === 'thinking' && (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 13 }}>
            <PipelineStages stage={state.stage} />
          </div>
        )}

        {state.kind === 'answered' && (() => {
          const chart = resultView ? resultView(state.answer) : null
          return (
            <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 13 }}>
              {state.summary && (
                <p
                  className="qg-anim"
                  style={{ margin: 0, fontSize: 13, lineHeight: 1.55, color: 'var(--qg-text)' }}
                >
                  {state.summary}
                </p>
              )}
              <QueryBlock query={state.answer.query} />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={sectionLabelStyle}>RESULT</span>
                  {chart !== null && (
                    <span
                      style={{
                        marginLeft: 'auto',
                        display: 'inline-flex',
                        border: '1px solid var(--qg-border-soft)',
                        borderRadius: 8,
                        overflow: 'hidden',
                      }}
                    >
                      {(['chart', 'rows'] as const).map((mode) => (
                        <button
                          key={mode}
                          type="button"
                          onClick={() => setView(mode)}
                          style={{
                            fontSize: '10.5px',
                            fontWeight: 500,
                            padding: '4px 10px',
                            border: 'none',
                            cursor: 'pointer',
                            background: view === mode ? 'var(--qg-surface2)' : 'transparent',
                            color: view === mode ? 'var(--qg-text)' : 'var(--qg-text-faint)',
                          }}
                        >
                          {mode}
                        </button>
                      ))}
                    </span>
                  )}
                </div>
                {chart !== null && view === 'chart' ? chart : <ResultRows result={state.answer.result} />}
              </div>
              <span style={{ fontSize: 11, color: 'var(--qg-text-faint)' }}>
                grounded in {state.answer.schema_used.length} schema item{state.answer.schema_used.length === 1 ? '' : 's'} ·{' '}
                {state.answer.attempts} attempt{state.answer.attempts === 1 ? '' : 's'} · {formatElapsed(state.answer.elapsed_ms)}
                {state.answer.cached && state.answer.cache_age_s !== undefined && (
                  <> · <span style={{ color: 'var(--qg-accent)' }}>cached {state.answer.cache_age_s}s ago</span></>
                )}
              </span>
            </div>
          )
        })()}

        {state.kind === 'abstained' && (
          <div style={{ padding: '14px 16px' }}>
            <AbstainCard
              title="Nothing in your schema answers this"
              message={state.answer.reason}
              chipText="refused to guess · 0 queries run"
              suggestions={state.suggestions}
              onAsk={submit}
            />
          </div>
        )}

        {state.kind === 'failed' && state.answer !== undefined && (
          <div style={{ padding: '14px 16px' }}>
            <AbstainCard
              title="Couldn't produce a validated query"
              message={state.answer.reason}
              chipText={
                state.answer.attempts === 0
                  ? "Couldn't reach the model — nothing was run"
                  : `failed after ${state.answer.attempts} attempt${state.answer.attempts === 1 ? '' : 's'}`
              }
              onAsk={submit}
            />
          </div>
        )}

        {state.kind === 'failed' && state.error !== undefined && (
          <div style={{ padding: '14px 16px' }}>
            <AbstainCard
              title="Couldn't reach your server"
              message={state.error}
              chipText="connection failed · 0 queries run"
              onAsk={submit}
            />
          </div>
        )}
      </div>

      <Footer />
    </div>
  )
}
