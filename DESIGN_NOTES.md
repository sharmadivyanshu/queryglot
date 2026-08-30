# Design notes

The build in the order it happened, with the reasoning and the things that
went wrong. Companion documents: `PROJECT_CORE.md` (why this exists),
`finetune/README.md` (the bake-off results in full).

If you only read one section, read **Bugs found and what they taught** — those
are the parts worth talking about out loud.

---

## Phase 1 — the compiler

**Goal:** a text-to-query pipeline that cannot reference a metric that doesn't
exist on YOUR server, and refuses instead of guessing.

**Files:** `catalog.py`, `backends/`, `retrieve.py`, `prompts.py`, `graph.py`,
`engine.py`

### Decisions

**Validation is the backend's own parser, never a reimplementation.**
Prometheus `format_query`, Elasticsearch `_validate/query?explain`. A
reimplemented grammar drifts from the real one version by version; the
server's parser is definitionally correct for that server. Parse errors come
back verbatim and become the next attempt's constraint.

**Retrieval is deliberately lexical.** BM25 over tokenised names/help/labels,
a small synonym table, a +10 exact-name boost. Schema retrieval is a
vocabulary-matching problem ("latency" → `*_duration_seconds`), not a
deep-semantics one — and a deterministic ranker means retrieval failures are
debuggable and the eval reproduces with zero model calls. An embedding
reranker is allowed in only when the eval shows lexical recall actually
failing. (The eval eventually showed the opposite failure: lexical matching
too *eager* — see question 14.)

**Abstention is an outcome, not an error.** `answered | abstained | failed`.
When nothing in the schema scores above `MIN_RETRIEVAL_SCORE`, the graph
refuses before any model call — zero tokens spent, zero invented names.
Wrong-but-plausible is the failure mode that matters; "I can't answer from
this schema" is a correct answer, and the eval scores it as one.

**The repair loop is bounded and audited.** `MAX_REPAIRS = 2`; every failed
attempt is kept in an accumulating `attempts` list. The abstain node reads
that trail to say *why* it gave up — the trail's presence (not the retrieval
score) is what distinguishes "nothing matched" from "couldn't produce valid
syntax".

**Every seam is a Protocol.** `Backend` (introspect/validate/execute), `LLM`
(complete), `Transport` (HTTP). Unit tests run the real graph against a
`FakeBackend` and `ScriptedLLM`; the live-Prometheus suite proves the same
code against a real parser and skips loudly, never silently, when no server
is configured. Runtime deps stay at three (langgraph, pydantic, mcp); HTTP is
stdlib urllib.

## Phase 2 — distribution

**Goal:** meet callers where they are. MCP server (`search`, `list_schema`,
`refresh_schema`) for agents; CLI for humans; both are thin wrappers over the
same `Engine`. Backend auto-routing is retrieval-strength-based —
deterministic and explainable, no extra model call.

## Phase 3 — the verified dataset

**Goal:** NL→PromQL training pairs that cannot teach hallucination.

**File:** `dataset.py`

### Decisions

Four rules, each load-bearing:

1. **Every pair is machine-verified** — must parse (`format_query`) AND
   execute against the live backend, or it is discarded, never hand-fixed.
2. **Training prompts are the engine's prompts** — the exact
   `SYSTEM` + `compile_prompt()` text the model sees at inference.
   Train/serve skew is the quiet killer of fine-tunes.
3. **Pairs whose target metric doesn't surface in top-8 retrieval are
   dropped and counted** — keeping them would teach the model to answer
   around the provided schema, i.e. train hallucination.
4. **Split by metric, never by row** — md5-hash buckets, so paraphrases
   never straddle train/test and held-out metrics measure generalisation.
   (Rule 4 was later defeated in a way none of the four rules anticipated —
   bug 7.)

## Phase 4 — the bake-off

**Goal:** answer "fine-tune or RAG?" with evidence at a scale a normal team
can afford: Qwen3-4B 4-bit, QLoRA via MLX, 18GB consumer Mac, deterministic
10-question golden eval. Result: RAG 8/10, FT-only 3/10, FT+RAG 9/10 — the
full analysis lives in `finetune/README.md`.

---

## Bugs found and what they taught

Real, in build order. Each one is a better interview answer than any feature.

### 1. Thinking mode + temperature 0.0 = an infinite loop

Qwen3 in thinking mode at temperature 0 recurses into its own reasoning and
never emits content. The fix cannot be per-request: `mlx_lm.server` only
honours `enable_thinking` in `--chat-template-args` at startup (mlx-lm #914).

**Fix:** server started with `--chat-template-args '{"enable_thinking":
false}'`; `QUERYGLOT_LLM_SYSTEM_SUFFIX=" /no_think"` kept as a per-request
escape hatch.

**Lesson:** know which knobs bind at process start vs per request — the
OpenAI-compatible surface hides that distinction.

### 2. A completion with no `content` key at all

Hybrid-thinking models can spend the entire token budget on a hidden
`reasoning` field and return a message with NO content key. Naive parsing
crashes; the information is "empty completion", not "malformed response".

**Fix:** `parse_completion()` returns `""` defensively; an empty query flows
into validate → repair like any other bad attempt.

**Lesson:** the failure belongs in the domain (a bad attempt) rather than in
the transport (an exception). The graph already knew what to do with a bad
attempt.

### 3. Test perplexity 7.704 — or 1.009, depending on a flag

`mlx_lm.lora --test` without `--mask-prompt` averages loss over prompt tokens
the model was never trained to predict. Same adapter, same data: 7.704
without the flag, 1.009 with it.

**Fix:** always `--mask-prompt`, for training AND testing.

**Lesson:** a loss is meaningless without knowing which tokens it averages
over.

### 4. Qwen3.5-4B cannot LoRA-train on Metal

OOM at the first backward pass regardless of batch size, layers, or
grad-checkpointing (mlx-lm #1206). Generation works fine, which makes the
first crash look like user error.

**Fix:** base model is Qwen3-4B. Documented so nobody rediscovers it.

**Lesson:** "inference works" says nothing about "training works" — the
memory profiles are different regimes.

### 5. `--adapter-path` silently ignored — every "arm 3" run was arm 1

Arm-3 eval output was byte-identical to arm 1 across two runs, one against a
freshly started server with `--adapter-path`. The tell: the model emitted
`A: process_resident_memory_bytes{...}` — an `A:` prefix. Training prompts
end with `A:` and all 1,281 completions are bare queries; an adapter at loss
0.009 essentially cannot produce that tic. So the base model was answering.

Root cause, in mlx-lm 0.31.3 `ModelProvider.load()`:

```python
model_path = self._model_map.get(model_path, model_path)        # rebinds to repo id
adapter_path = self._adapter_map.get(model_path, adapter_path)  # keyed by REBOUND value
```

`_adapter_map`'s only key is the sentinel `"default_model"`, but the lookup
uses the already-resolved repo id — it can never hit. The adjacent draft-model
line does the same lookup keyed by the original argument, correctly. Verified
by driving the real `load()` with weight-loading stubbed: **no request
`model` value activates the CLI adapter — the flag is dead on every path,
startup preload included.**

Epilogue: when we went to file it, it was already reported (mlx-lm #1745,
#1248) and fixed on `main` (PR #1249) — closed five days before we hit it,
with no release carrying the fix (0.31.3 was still latest). Independent
root-causing confirmed against the upstream patch: same two lines, same
reordering.

**Fix:** the per-request `"adapters"` body field survives (it enters `load()`
as the `.get()` default), so `llm.py` sends it when `QUERYGLOT_LLM_ADAPTERS`
is set. Chosen over `mlx_lm.fuse` because fusing de/re-quantises — the eval
would run a numerically different artifact than the one that trained.

**Lesson:** verify which model answered *behaviourally*. `/v1/models` reports
the same id either way; only a discriminating probe (the `A:` tic on a
non-templated question) separates adapter from base. The eval now prints a
fingerprint header into every results file so an arm label can never again
silently disagree with reality. And before filing upstream, check `main` —
"fixed but unreleased" is a state pip cannot show you.

### 6. The golden set had bugs of its own

Two found during failure analysis: the goroutines case rejected
`go_sched_goroutines_goroutines`, a valid synonym metric (fix: a
`must_reference` entry may now list alternatives); and "current number of
active alerts" was unanswerable on a bare Prometheus — `ALERTS` is synthetic
and absent from `/api/v1/metadata`, so the system's own unknown-metric check
would reject the only honest answer — yet it PASSed on a semantically wrong
metric (fix: replaced with an answerable question).

**Lesson:** the eval is code and has bugs like code. Failure analysis must
interrogate the test as hard as the system.

### 7. Val loss 0.009 on held-out metrics — then 3/10 deployed

The no-schema arm's metric-disjoint validation loss converged to 0.009 with
no schema in the prompt. That should be impossible for unseen metric names —
unless the names aren't actually unseen. They weren't: `subject_phrase()`
puts the metric's own words into the generated question (`go_goroutines` →
"go goroutines"), so the model learned the inverse string transform, not the
schema. The metric-disjoint split guarded against memorisation and was
silently defeated by the question generator.

**Fix:** none needed in code — the golden set (human phrasing, no shared
tokens) is the deployment-predictive number, and the writeup says so.

**Lesson:** splits control one leakage channel; the data generator can open
another. Ask "could a model score well here WITHOUT the capability I'm
measuring?"

### 8. A passing answer that computes the constant 100

Arm 3's CPU answer: `rate(x[5m]) / rate(x[5m]) * 100` — identically 100,
fluent, valid, executes, references the required metric. PASS.

**Fix:** none — deliberately. Deterministic semantic scoring of arbitrary
PromQL is equivalence-checking; an LLM judge would reintroduce the
self-preference bias the eval exists to avoid. The limit is documented and
carried in every results claim instead.

**Lesson:** know what your eval measures (outcome + references +
executability) and say what it doesn't (meaning). An eval's blind spot
becomes dishonest only when it goes unstated.

### 9. The repair prompt asked the question twice

`compile_prompt` appends `["Q: ...", "A:"]`, then the repair branch replaced
`lines[-1:]` — only the `"A:"` — and re-added its own `Q:` line. Every repair
attempt in every arm carried the duplicated question. Found while writing
these notes; fixed with a one-character slice change (`lines[-2:]`) and a
test that counts occurrences.

**Lesson:** prompts are code paths with no compiler. Rendered-output tests
(count the `Q:` lines) are the only thing that catches them — and writing
documentation is a code review.

---

## Questions to be able to answer

If you can answer these without notes, you own this code.

**On the compiler**
1. Why does `validate()` call the backend's parser instead of a PromQL
   grammar library? What drifts, and when?
2. Why is retrieval BM25 and not embeddings? What evidence would justify
   adding a reranker?
3. Why does the abstention gate fire *before* the first model call? What
   does that cost, what does it save?
4. The abstain node distinguishes its two reasons by the attempts trail, not
   the retrieval score. Why is the score the wrong signal? (Hint: the
   no-retrieval arm.)
5. `metric_candidates()` is regex-based and best-effort. Why is that
   acceptable there and unacceptable in `validate()`'s parser role?
6. Histogram metadata lists `x`; queries address `x_bucket`. Where is that
   resolved and why not in retrieval?

**On the dataset**
7. Why must every pair parse AND execute? What does execute catch that parse
   doesn't?
8. Why drop pairs whose metric doesn't surface in top-8 retrieval? What
   behaviour would keeping them train?
9. Why split by metric hash instead of random rows?
10. Rule 4 was defeated anyway. By what, and what would you change in
    `subject_phrase()` to close it — and what would that cost in dataset
    naturalness?

**On the bake-off**
11. What did the fine-tune actually improve, mechanically? Point at the two
    artifacts in the transcripts.
12. Arm 2 "abstained" seven times. Who abstained, exactly? Why is that
    distinction the whole thesis?
13. Why serve the adapter per request instead of fusing it into the weights?
14. Both RAG arms answered the kubernetes question they should have refused.
    Why can't more training fix that? What could?
15. Test perplexity was 1.009 and deployment was 3/10. Reconcile those
    numbers in two sentences.
16. Prove which model answered an eval run, given that `/v1/models` lies.

---

## What's deliberately not built

- **Embedding reranker** — until the eval shows lexical recall failing.
  So far the observed failure is the opposite: matching too eager (Q14).
- **Semantic answer scoring** — an LLM judge trades a stated blind spot for
  an unstated bias (bug 8).
- **LLM paraphrase augmentation of the dataset** — would attack bug 7's
  leakage and the phrasing gap, but every added generator is a new leakage
  channel to audit. The golden set covers phrasing until then.
- **Per-token likelihood analysis of the MMLU deltas** — the regression
  check ran (no forgetting; both adapters gained, arm 2 most, likely a
  terse-completion format effect on loglikelihood scoring — see
  `finetune/README.md`); confirming the mechanism needs likelihoods the
  harness doesn't retain.
- **Loki / Datadog backends, OpenAPI backend** — sequencing discipline:
  finish, publish, then extend (`PROJECT_CORE.md`).
