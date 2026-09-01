import type { CSSProperties } from 'react'
import type { ThinkingStage } from '../lib/useAsk'

type StageStatus = 'done' | 'current' | 'pending'

interface StageMeta {
  name: string
  currentLabel: string
  doneLabel: string
  pendingLabel: string
}

// Stage 0 (retrieve) never reports a fabricated schema-item count here — v1
// has no streaming, so the real number only exists once the answer lands
// (schema_used.length, shown on the answered card). Everything else is
// transcribed from WidgetThinking.dc.html verbatim (the "validate"/"execute"
// pending copy and the "Writing the query…" current copy are exact).
const STAGES: StageMeta[] = [
  { name: 'retrieve', currentLabel: 'Searching your schema…', doneLabel: 'Found matching schema items', pendingLabel: 'Search your schema' },
  { name: 'compile', currentLabel: 'Writing the query…', doneLabel: 'Query written', pendingLabel: 'Write the query' },
  { name: 'validate', currentLabel: 'Validating against your server…', doneLabel: 'Validated against your server', pendingLabel: 'Validate against your server' },
  { name: 'execute', currentLabel: 'Running it…', doneLabel: 'Ran it', pendingLabel: 'Run it' },
]

const trackStyle: CSSProperties = {
  height: 3,
  borderRadius: 999,
  background: 'var(--qg-surface2)',
  overflow: 'hidden',
}

function statusOf(index: number, stage: ThinkingStage): StageStatus {
  if (index < stage) return 'done'
  if (index === stage) return 'current'
  return 'pending'
}

function StageIcon({ status }: { status: StageStatus }) {
  if (status === 'done') {
    return (
      <span
        style={{
          display: 'inline-flex',
          width: 18,
          height: 18,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: 999,
          background: 'var(--qg-ok-bg)',
          border: '1px solid var(--qg-ok-border)',
          flexShrink: 0,
        }}
      >
        <svg width="9" height="9" viewBox="0 0 10 10" fill="none">
          <path d="M1.5 5.5 L4 8 L8.5 2.5" stroke="var(--qg-accent)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    )
  }
  if (status === 'current') {
    return (
      <span
        style={{
          display: 'inline-flex',
          width: 18,
          height: 18,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: 999,
          border: '1.5px solid var(--qg-accent)',
          flexShrink: 0,
        }}
      >
        <span style={{ width: 6, height: 6, borderRadius: 999, background: 'var(--qg-accent)' }} />
      </span>
    )
  }
  return (
    <span
      style={{
        display: 'inline-flex',
        width: 18,
        height: 18,
        borderRadius: 999,
        border: '1px solid var(--qg-border)',
        flexShrink: 0,
      }}
    />
  )
}

/** The four retrieve/compile/validate/execute rows + progress bar from WidgetThinking.dc.html. */
export function PipelineStages({ stage }: { stage: ThinkingStage }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
      {STAGES.map((meta, i) => {
        const status = statusOf(i, stage)
        const label = status === 'done' ? meta.doneLabel : status === 'current' ? meta.currentLabel : meta.pendingLabel
        return (
          <div key={meta.name} style={{ display: 'flex', alignItems: 'center', gap: 12, opacity: status === 'pending' ? 0.45 : 1, transition: 'opacity 200ms ease' }}>
            <StageIcon status={status} />
            <span
              style={{
                fontSize: 13,
                flexGrow: 1,
                fontWeight: status === 'current' ? 500 : 400,
                color: status === 'current' ? 'var(--qg-text)' : 'var(--qg-text-mut)',
              }}
            >
              {label}
            </span>
            <span className="mono" style={{ fontSize: '10.5px', color: 'var(--qg-text-faint)' }}>
              {meta.name}
            </span>
          </div>
        )
      })}
      <div style={trackStyle}>
        <div className="qg-progress-fill" style={{ width: `${stage * 33 + 11}%`, height: '100%', borderRadius: 999, background: 'var(--qg-accent)' }} />
      </div>
    </div>
  )
}
