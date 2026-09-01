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

## Phase 5 — the serve layer

**Goal:** an HTTP face for the engine — what a browser widget can call.

**File:** `server.py` (FastAPI + uvicorn behind a `serve` extra; core deps
stay at three)

### Decisions

**Outcomes are payloads, never HTTP errors.** An abstention is a correct
answer and arrives as a 200 with `outcome: "abstained"`. Even an engine
exception returns 200 `outcome: "failed"` — the widget renders every
outcome from one JSON shape. Error codes are reserved for transport faults
(400 empty question, 401 bad bearer).

**The app factory takes the Engine.** `create_app(engine, cors_origins,
static_dir)` — tests inject fakes for all three seams; the console script
builds real ones from the same env vars as MCP/CLI.

**Auth is a shared secret, honestly scoped.** `QUERYGLOT_SERVE_TOKEN`
bearer on `/api/*`; unset means open, and the README says so rather than
pretending. `/docs` stays open deliberately — it exposes API shape, not
data.

## Phase 6 — ask surfaces (widget + playground)

**Goal:** the product face: a one-script-tag embeddable ask-box and a
playground that makes a stranger's backend answerable in five minutes.

**Files:** `frontend/` (Vite + React + TS; two build modes), served from
`_static/` by `queryglot-serve`

### Decisions

**One component, two surfaces.** The playground renders the SAME `Panel`
the embed ships — the demo cannot drift from the product.

**The embed is a good guest.** Shadow DOM both ways (host CSS can't leak
in, ours can't leak out), no fonts forced onto the host page, theme follows
the host (`data-theme` light|dark|auto), 13KB gzipped.

**The thinking state never lies.** Pipeline stages animate on a timer but
cap before "execute" until the response lands, then snap to truth. No
fabricated timings anywhere — the trace panel shows only what the API
measured.

**Abstention is a first-class screen.** Calm amber information, "refused to
guess · 0 queries run", and schema-derived nearest-answerable suggestions —
never an error state, never invented content.

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

### 10. CORS preflights were 401'd the moment auth was enabled

Starlette builds the middleware stack in reverse: the LAST-registered
middleware runs OUTERMOST. The bearer guard, registered after
CORSMiddleware, intercepted preflight OPTIONS requests — which by spec
carry no Authorization header — so a browser with a token configured could
never complete a preflight. The plan's own snippet mandated the ordering,
and its tests never combined CORS with auth, so everything was green.

**Fix:** OPTIONS exempt from the bearer check, plus a regression test that
enables both features at once. A later review pass added CORS headers to
the 401 itself — without them, a cross-origin widget sees an opaque CORS
failure instead of "unauthorized".

**Lesson:** features that are green separately can be broken together;
test the combinations the deployment will actually run.

### 11. The auth-and-error path was itself a leak and a crash surface

Two findings on the same few lines. `reason: f"engine error: {exc}"`
echoed raw exception text to HTTP clients — and urllib error messages
embed the internal LLM endpoint URL. And a non-ASCII Authorization header
(`Bearer café`) raised TypeError inside `hmac.compare_digest(str, str)`:
an unauthenticated caller could trip a 500 in the auth guard.

**Fix:** `logging.exception` server-side with a class-name-only reason
("engine error (URLError) — details in server logs"); byte-wise
`compare_digest` on latin-1-encoded values.

**Lesson:** error paths face the same adversaries as happy paths — audit
what they emit and what they can be fed.

### 12. The spec demanded React in the widget AND a ceiling React cannot fit

"React is bundled into the IIFE" and the 60KB gzip ceiling were mutually
unsatisfiable: react+react-dom floor near 60KB alone; the naive build hit
63KB. The resolution: alias react → preact/compat for the WIDGET build
only. Components stay React-authored, the playground ships real React, the
embed lands at 13KB — verified functionally against the built bundle, not
just measured.

**Lesson:** write budgets and stack choices in the same breath and check
their product early; and when two spec lines collide, resolve them with a
recorded ruling, not a silent pick.

### 13. CI was green because CI couldn't see the bug

Once `npm run build:all` populated `_static/`, two serve tests asserting
404-when-unbuilt failed — locally. CI stayed green because the python and
frontend jobs run in isolated checkouts: neither job ever held both the
build output and the test suite. The green badge was actively hiding a red
repo.

**Fix:** `create_app` takes `static_dir`; the 404 tests pin an empty tmp
dir, making the suite build-state-independent.

**Lesson:** job isolation isolates evidence too. When two components share
disk state, some check must exercise them together.

### 14. Tests used the shape we wrote; the wire used the shape Prometheus writes

`ResultRows` detected instant vectors as a bare `[{metric, value}]` array —
the shape every unit-test fixture used. The live API returns Prometheus's
envelope `{resultType, result: [...]}`, so real answers rendered as a JSON
blob instead of label/value rows. Only driving the real playground in a
real browser caught it.

**Fix:** unwrap the envelope, with a test using the WIRE shape.

**Lesson:** fixtures drift toward what is convenient to type. At least one
test per boundary should carry a verbatim captured response.

### 15. The honest-refusal flow — the product's signature — was the least-built flow

Two findings, same root. The trace panel extracted telemetry only from
`answered`, so an abstention (which carries real schema_used/attempts/
elapsed_ms) rendered dashes — right after the hero copy promised honest
refusals. And the abstained card's "closest your schema can answer" rows
were the static idle suggestions, making a claim about the user's schema
that nothing grounded.

**Fix:** telemetry extracted from every outcome that carries it;
suggestions fetched from /api/schema on abstention (hidden when empty).

**Lesson:** the differentiating path deserves the same engineering as the
happy path — it IS the happy path of the pitch.

### 16. The a11y floor lost silently wherever it collided with the mockups

The spec said 44px minimum targets. The approved artboards drew a 38px
pill and 36px rows, and implementers transcribed them faithfully — except
the theme toggle, where the spec spelled out the fix, and it shipped at
44px. The constraint survived exactly where it was named per-component and
vanished everywhere it wasn't.

**Fix:** minHeight 44 across pill and rows (ruling: a11y beats pixel
fidelity), slightly taller than the artboards.

**Lesson:** when two authorities conflict (spec constraint vs visual
authority), every collision needs an explicit ruling — silence always
resolves toward whichever authority the implementer is looking at.

### 17. "Which endpoint is causing the max latency?" — one question, four bugs deep

A live user question produced a fluent, valid, executed answer that was
wrong four ways at once. (a) Retrieval sent "endpoint" to a dead Consul
metric because BM25 matched its LABEL name; fixed with synonym entries
(endpoint→handler/route/path, latency→latencies) — the table doing exactly
what it was designed for: growing from observed failures. (b) The model
then grouped `by (endpoint)` on a metric whose label is `handler` — and
PromQL considers grouping by an ABSENT label valid, silently collapsing
every series into one anonymous number; the server can never catch it, so
validate() grew an unknown-grouping-label check, the metric check's natural
sibling. (c) The check didn't fire at first: histograms have no series
under their base name, so label introspection had come back empty — the
bucket-series fallback fixed the blind spot. (d) The repair then picked
`app, instance, job` over the right label, so the error message now
consults SYNONYMS to say "did you mean 'handler'?" — a deterministic hint,
not a model's guess. Final behavior: attempts 2, grouped by handler, the
max emphasized.

**Lesson:** wrong-but-plausible failures stack. Each layer's fix was small,
deterministic, and testable — and none of them would have been found
without asking a real question against a real server and refusing to accept
a fluent answer.

Coda (next session of live testing found three more layers): the shipped
suggestion chips themselves missed the vocabulary ("slowest"/"routes"/
singular "error" absent from SYNONYMS — one chip abstained, another hit a
queue metric); English stopwords in queries outscored real matches ("the"
appears twice in a help text — query-side stopword filter); metadata-only
DEAD metrics (zero live series) evaded the label check and produced empty
"successes" — introspection now drops a metric whose series probe ran and
found nothing; and _bucket on a SUMMARY is valid-but-always-empty PromQL —
validation now uses the metadata type to reject it. Residual, named
honestly: for "which endpoint has max latency", lexical retrieval prefers
the live Consul SD summary (whose label is literally `endpoint`) over the
HTTP histogram (label `handler`) — a semantic preference no lexical ranker
can adjudicate; the boundary where a reranker would begin.

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

**On the serve layer and surfaces**
17. Why is an abstention a 200? What breaks if it's a 4xx?
18. Which Starlette middleware runs first, and why did that 401 every
    preflight? (Bug 10.)
19. Why extras instead of a Poetry group for `serve`?
20. Why does the widget bundle ship preact/compat while the playground
    ships React? What would break if compat drifted? (Bug 12.)
21. How did CI stay green while the repo was red? (Bug 13.)
22. Why does the widget follow the host's theme instead of owning a
    toggle?
23. Why does the thinking state cap at "validate" until the response
    lands?

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
- **Per-stage timings in the trace panel** — the API measures only total
  elapsed_ms; the panel shows only what is measured.
- **Widget teardown API, arrow-key suggestion navigation, `data-fonts`
  opt-in** — v1 gaps, recorded not improvised.
- **Loki / Datadog backends** — sequencing discipline: finish, publish,
  then extend (`PROJECT_CORE.md`). The OpenAPI backend HAS since shipped.
