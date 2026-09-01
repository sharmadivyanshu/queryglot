import { useEffect, useMemo, useState } from 'react'
import { ThemeProvider } from '../ui/theme'
import { createClient } from '../lib/api'
import type { StatusResponse } from '../lib/api'
import { useAsk } from '../lib/useAsk'
import { Panel } from '../widget/Panel'
import { TopBar } from './TopBar'
import { SchemaRail } from './SchemaRail'
import { TracePanel } from './TracePanel'

/** v1's static default list — same as the widget's. */
const SUGGESTIONS = ['error rate in the last hour', 'memory usage right now', 'slowest routes today']
const SCHEMA_LIMIT = 50

function SearchIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 16 16" fill="none">
      <circle cx="7" cy="7" r="4.5" stroke="var(--qg-text-faint)" strokeWidth="1.5" />
      <path d="M10.5 10.5 L14 14" stroke="var(--qg-text-faint)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function AskBar({ onAsk }: { onAsk: (question: string) => void }) {
  const [value, setValue] = useState('')

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

function Playground() {
  const client = useMemo(() => createClient({ api: '' }), [])
  const { state, ask, reset } = useAsk(client)
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [schemaItems, setSchemaItems] = useState<string[]>([])

  useEffect(() => {
    client
      .status()
      .then(setStatus)
      .catch(() => {})
    client
      .schema('', SCHEMA_LIMIT)
      .then((response) => setSchemaItems(response.items))
      .catch(() => {})
  }, [client])

  const answer = state.kind === 'answered' ? state.answer : undefined

  return (
    <div className="flex h-screen w-screen flex-col bg-qg-bg text-qg-text">
      <TopBar status={status} />
      <div className="flex min-h-0 flex-1">
        <SchemaRail items={schemaItems} status={status} />
        <main className="flex min-w-0 flex-1 flex-col gap-[18px] px-8 py-7">
          <div className="flex flex-col gap-1.5">
            <h1 className="font-disp text-[23px] font-bold tracking-[-0.015em] text-qg-text">
              Your metrics, answerable in plain language.
            </h1>
            <p className="text-[13.5px] text-qg-text-mut">
              Every answer shows the exact validated query it ran. Off-schema questions get an honest refusal.
            </p>
          </div>
          <AskBar onAsk={ask} />
          <div className="flex min-h-0 flex-1 gap-[18px]">
            <div className="min-w-0 flex-1">
              <Panel state={state} onAsk={ask} onClose={reset} suggestions={SUGGESTIONS} inline />
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
