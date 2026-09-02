import type { SearchResponse } from '../lib/api'

interface StageRow {
  name: string
  metric: string
}

/**
 * v1 has no per-stage timing breakdown from the server — only the answer's
 * totals (schema_used.length, attempts, elapsed_ms) are real. "validate"
 * has no numeric metric of its own, so it always reads "server parser"
 * (true regardless of outcome — the server's parser is what validated it).
 */
function buildStages(answer?: SearchResponse): StageRow[] {
  if (!answer) {
    return [
      { name: 'retrieve', metric: '–' },
      { name: 'compile', metric: '–' },
      { name: 'validate', metric: '–' },
      { name: 'execute', metric: '–' },
    ]
  }
  const items = answer.schema_used.length
  const attempts = answer.attempts
  return [
    { name: 'retrieve', metric: `${items} item${items === 1 ? '' : 's'}` },
    { name: 'compile', metric: `${attempts} attempt${attempts === 1 ? '' : 's'}` },
    { name: 'validate', metric: 'server parser' },
    { name: 'execute', metric: answer.window ? `query_range · ${answer.window.minutes} min` : `${Math.round(answer.elapsed_ms)} ms` },
  ]
}

function StageDot({ done }: { done: boolean }) {
  return (
    <span
      className={
        done
          ? 'h-4 w-4 flex-shrink-0 rounded-full border border-qg-ok-border bg-qg-ok-bg'
          : 'h-4 w-4 flex-shrink-0 rounded-full border border-qg-border'
      }
    />
  )
}

/** "HOW IT GOT THERE" trace: the four pipeline stages, populated from the answered state's answer once it lands. */
export function TracePanel({ answer }: { answer?: SearchResponse }) {
  const stages = buildStages(answer)

  return (
    <div className="flex w-[300px] flex-shrink-0 flex-col gap-2.5 rounded-[14px] border border-qg-border bg-qg-surface p-4">
      <span className="text-[11px] font-semibold tracking-[0.08em] text-qg-text-faint">HOW IT GOT THERE</span>
      {stages.map((stage) => (
        <div key={stage.name} className="flex items-center gap-2.5">
          <StageDot done={answer !== undefined} />
          <span className="flex-1 text-[12.5px] text-qg-text-mut">{stage.name}</span>
          <span className="font-mono text-[11px] text-qg-text-faint">{stage.metric}</span>
        </div>
      ))}
      <span className="border-t border-qg-border-soft pt-1 text-[11.5px] leading-[1.5] text-qg-text-faint">
        {answer?.window
          ? 'The window came from the picker, not the model — the model wrote the expression, the range was applied by the engine.'
          : "The model only wrote syntax. Your schema came from live introspection; your server's parser had the final word."}
      </span>
    </div>
  )
}
