import { useEffect, useMemo, useState } from 'react'
import { ThemeProvider } from '../ui/theme'
import { createClient } from '../lib/api'
import type { SchemaField, SearchResponse, StatusResponse } from '../lib/api'
import { parseVector } from '../lib/resultData'
import { useAsk } from '../lib/useAsk'
import type { AskState } from '../lib/useAsk'
import { Panel } from '../widget/Panel'
import { BarChart } from './BarChart'
import { TopBar } from './TopBar'
import { SchemaRail } from './SchemaRail'
import { TracePanel } from './TracePanel'

/** v1's static default list — same as the widget's. */
const SUGGESTIONS = ['error rate in the last hour', 'memory usage right now', 'slowest routes today']
const SCHEMA_LIMIT = 500

function totalMetricsOf(status: StatusResponse): number {
  return Object.values(status.backends).reduce((sum, count) => sum + count, 0)
}

function SearchIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 16 16" fill="none">
      <circle cx="7" cy="7" r="4.5" stroke="var(--qg-text-faint)" strokeWidth="1.5" />
      <path d="M10.5 10.5 L14 14" stroke="var(--qg-text-faint)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function AskBar({ onAsk, seed }: { onAsk: (question: string) => void; seed: string }) {
  const [value, setValue] = useState('')
  // Adjusts state during render rather than in an effect (react.dev/learn/you-might-not-need-an-effect
  // #adjusting-some-state-when-a-prop-changes) — a seed change must land before this render paints.
  const [appliedSeed, setAppliedSeed] = useState('')
  if (seed && seed !== appliedSeed) {
    setAppliedSeed(seed)
    setValue(seed)
  }

  function submit() {
    const trimmed = value.trim()
    if (!trimmed) return
    onAsk(trimmed)
  }

  return (
    <div className="flex items-center gap-3 rounded-xl border border-qg-accent bg-qg-surface px-[18px] py-[13px] shadow-qg">
      <SearchIcon />
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') submit()
        }}
        placeholder="p95 latency by route over the last 15 minutes"
            name="qg-ask" id="qg-ask"
        className="flex-1 border-none bg-transparent text-[15px] text-qg-text outline-none placeholder:text-qg-text-faint"
      />
      <button
        type="button"
        onClick={submit}
        className="font-disp rounded-lg bg-qg-accent px-[18px] py-2 text-[13px] font-semibold text-qg-on-accent"
      >
        Ask
      </button>
    </div>
  )
}

/** Extracts the answer whenever the state actually carries one — answered, abstained, or a failed-with-answer (a validation failure still has real telemetry; only a connection failure has no answer at all). */
function answerOf(state: AskState): SearchResponse | undefined {
  if (state.kind === 'answered' || state.kind === 'abstained') {
    return state.answer
  }
  if (state.kind === 'failed' && state.answer !== undefined) {
    return state.answer
  }
  return undefined
}

function Playground() {
  const client = useMemo(() => createClient({ api: '' }), [])
  const { state, ask, reset } = useAsk(client)

  // The panel header advertises ⌘K — honor it inline too: reset to idle.
  useEffect(() => {
    const onKeydown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        reset()
      }
    }
    document.addEventListener('keydown', onKeydown)
    return () => document.removeEventListener('keydown', onKeydown)
  }, [reset])
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [statusUnreachable, setStatusUnreachable] = useState(false)
  const [schemaFields, setSchemaFields] = useState<SchemaField[]>([])
  const [schemaUnreachable, setSchemaUnreachable] = useState(false)
  const [seed, setSeed] = useState('')  // pre-fill for AskBar

  const lastAnswerNames = state.kind === 'answered' ? state.answer.schema_used : []
  const askAbout = (name: string) => {
    setSeed(name)
    document.getElementById('qg-ask')?.focus()
  }

  useEffect(() => {
    client
      .status()
      .then(setStatus)
      .catch(() => setStatusUnreachable(true))
    client
      .schema('', SCHEMA_LIMIT)
      .then((response) => setSchemaFields(response.fields))
      .catch(() => setSchemaUnreachable(true))
  }, [client])

  const answer = answerOf(state)

  const resultView = (searchResponse: SearchResponse) => {
    const rows = parseVector(searchResponse.result)
    if (!rows || rows.length < 2 || !Number.isFinite(rows[0].value)) return null
    return <BarChart rows={rows} />
  }

  return (
    <div className="flex h-screen w-screen flex-col bg-qg-bg text-qg-text">
      <TopBar status={status} unreachable={statusUnreachable} />
      <div className="flex min-h-0 flex-1">
        <SchemaRail
          fields={schemaFields}
          total={status ? totalMetricsOf(status) : undefined}
          unreachable={schemaUnreachable}
          lastAnswerNames={lastAnswerNames}
          onAskAbout={askAbout}
        />
        <main className="flex min-w-0 flex-1 flex-col gap-[18px] px-8 py-7">
          <div className="flex flex-col gap-1.5">
            <h1 className="font-disp text-[23px] font-bold tracking-[-0.015em] text-qg-text">
              Your metrics, answerable in plain language.
            </h1>
            <p className="text-[13.5px] text-qg-text-mut">
              Every answer shows the exact validated query it ran. Off-schema questions get an honest refusal.
            </p>
          </div>
          <AskBar onAsk={ask} seed={seed} />
          <div className="flex min-h-0 flex-1 gap-[18px]">
            <div className="min-w-0 flex-1">
              <Panel state={state} onAsk={ask} onClose={reset} suggestions={SUGGESTIONS} inline resultView={resultView} />
            </div>
            <TracePanel answer={answer} />
          </div>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <Playground />
    </ThemeProvider>
  )
}
