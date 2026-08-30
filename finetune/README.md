# Fine-tune track — RAG vs LoRA at 4B, measured

The bake-off this repo exists to run, now complete:

| Arm | What it knows | Golden set |
|---|---|---|
| 1 — RAG only | your schema, at query time (retrieval in prompt) | **8/10** |
| 2 — fine-tune only | PromQL syntax + whatever names it absorbed | **3/10** |
| 3 — RAG + fine-tune | both | **9/10** |

Base model for every arm: `mlx-community/Qwen3-4B-4bit` served by
`mlx_lm.server` on an 18GB Apple Silicon Mac. (Qwen3.5-4B was the original
target; its LoRA training crashes Metal OOM at the first backward pass
regardless of config — mlx-lm #1206 — so Qwen3 it is.)

The division of labour the results confirm: **schema is per-environment and
changes on every deploy — it can only be retrieval. Syntax and output format
are stable — they are exactly what a small fine-tune learns well.** Published
context this replicates at hobby scale: FT+RAG measurably wins at <=4B
(SIGIR-AP 2024); supervised pairs beat unsupervised doc-training by an order
of magnitude (EMNLP 2024).

## Results in detail

Full transcripts: `results-arm1-rag-base.txt`, `results-arm2-ft-only.txt`,
`results-arm3-rag-ft.txt` — each opens with a fingerprint header (LLM URL,
model, adapter, `/v1/models`) so the arm label is recorded in the artifact,
not in shell history. See "Bugs" in `../DESIGN_NOTES.md` for why that header
exists.

**What the fine-tune bought (+1, arm 1 → arm 3): format compliance, not
knowledge.** The base model prefixes answers with a literal `A: ` — a tic
that fails validation and costs it the memory question after repair
exhaustion. The adapter never does. Arm 3's queries also shed arm 1's
reflexive `sum by (app, instance, job)` wrapping in favour of the training
templates' bare shapes. Nothing in the +1 required knowing more facts.

**What removing retrieval cost (−5 vs arm 1, −6 vs arm 3): everything the
thesis predicts.** Arm 2's model answered all ten questions confidently and
got the metric name right once — `go_goroutines`, the only question whose
words spell the metric. Everything else was fluent PromQL over invented
names, and the inventions are diagnostic:

- `http_requests_total`, `http_request_duration_seconds_bucket` — real names
  on most servers in the world, absent on this one (here they are
  `prometheus_http_*`). The pretraining prior, ungrounded.
- `prometheus_tsdb_total_samples_appended` — a word-order permutation of the
  real `prometheus_tsdb_head_samples_appended_total`. Near-memory, not
  memory.
- `sum by (le) (rate(file_descriptors_open_total[5m]))` for a gauge
  question — `le` bleeding in from histogram templates. Template-trained
  models interpolate between templates when uncertain.
- `balance_bitcoin_wallet_bytes` — the off-schema refusal case, answered
  anyway, with a dutifully learned `_bytes` suffix.

**Arm 2 never refused.** Every "abstained" in its transcript was produced by
the validation layer (unknown-metric check + bounded repair exhaustion), not
by the model. Its two abstention-case passes are right-for-the-wrong-reason.
Without that layer, `http_requests_total` would have *executed* — valid
PromQL, empty result, green status: a silent failure. The system's outer
guardrail is what kept hallucination from reaching the caller.

**One arm-3 pass is semantically vacuous and the eval cannot see it.**
`rate(process_cpu_seconds_total[5m]) / rate(process_cpu_seconds_total[5m]) * 100`
is identically 100. It parses, executes, and references the required metric,
so it scores PASS. The eval verifies outcome + references + executability —
not meaning. Honest headline: 9/10, one of them hollow.

**Both RAG arms share one failure the fine-tune cannot fix:** "kubernetes pod
restarts in the payments namespace" should be refused, but "kubernetes"
BM25-matches `prometheus_sd_kubernetes_events_total` above the abstention
gate, so both arms answer an unanswerable question. Abstention lives in the
retrieval gate, not the model — no amount of training touches it.

## The two measurement traps

Worth more than the scores:

1. **A loss is meaningless without knowing which tokens it averages over.**
   `mlx_lm.lora --test` reports 7.704 without `--mask-prompt` and 1.009 with
   it. The first number averages over unmasked prompt tokens and says
   nothing about the completion the model actually learns.
2. **A good loss is meaningless if the eval distribution leaks the answer.**
   The no-schema arm hit val loss 0.009 on *metric-disjoint* held-out data —
   and then scored 3/10 deployed. The templated questions contain the
   metric's own words (`go_goroutines` → "go goroutines"), so held-out
   perplexity measured a string transform (spaces→underscores, restore the
   type suffix), not schema knowledge. The metric-disjoint split guarded
   against memorisation and was silently defeated by the question generator.
   The golden set, whose phrasing shares no tokens with the metric names, is
   the only number that predicted deployment behaviour.

## Dataset (methodology unchanged, it held up)

Generator: `queryglot.dataset` — 1,651 machine-verified pairs from a bare
self-scraping Prometheus. Every pair must PARSE (`format_query`) and EXECUTE
against the live backend; pairs whose target metric doesn't surface in top-8
retrieval are dropped and counted (`report.json`) — keeping them would teach
the model to answer around the provided schema. Splits are metric-disjoint by
md5 hash (1281/155/215). Training prompts are the engine's own
`SYSTEM` + `compile_prompt()` — train/serve parity, for both variants:

```bash
# RAG+FT arm: prompts carry the engine's retrieval slice (train = serve)
python -m queryglot.dataset --prometheus http://localhost:9090 --out finetune/data

# FT-only arm: same verified pairs, bare Q/A prompts (same code path the
# --no-retrieval eval serves)
python -m queryglot.dataset --prometheus http://localhost:9090 \
  --out finetune/data-noschema --no-schema
```

## Training (MLX, reproduced twice)

```bash
mlx_lm.lora --model mlx-community/Qwen3-4B-4bit --train \
  --data finetune/data --iters 800 --batch-size 4 \
  --num-layers 16 --mask-prompt --grad-checkpoint \
  --adapter-path finetune/adapters            # data-noschema -> adapters-noschema
```

With-schema run: val 2.623 → 0.001, peak 7.86GB. No-schema run: val
3.295 → 0.009, peak 3.78GB (prompts ~10× shorter). Both converge by ~iter
400; both under an hour.

Serving: `mlx_lm.server` 0.31.3 silently drops `--adapter-path` (upstream
mlx-lm #1745, fixed by PR #1249 on main but unreleased as of 0.31.3;
independently root-caused in `../DESIGN_NOTES.md`); the adapter must travel
per request via `QUERYGLOT_LLM_ADAPTERS`, and `eval/run_eval.py`'s
fingerprint header records what actually answered.

## Measurement rules

- `eval/run_eval.py` + 10 golden questions: outcome match + required metric
  referenced (an entry may list alternatives) + the query actually executed.
  Deterministic — no LLM judge, no self-preference bias.
- Abstention questions count. A model that answers everything confidently
  scores WORSE than one that refuses off-schema questions — arm 2
  demonstrates why this rule exists.
- Honest caveats: n=10; the golden set is the only phrasing-generalisation
  test (val/test are templated and leak names, trap 2 above).

## MMLU regression check — no forgetting (and one more format effect)

`mlx_lm.evaluate` has no adapter flag, so `mmlu_check.py` injects
`adapter_path` into its module-level `load()` and defers everything else to
the stock harness (`run_mmlu_check.sh` reproduces all three runs). Identical
slice for all arms: 57 subtasks x 4 questions = 228, 0-shot, seed 123 — a
paired comparison. Raw lm-eval output in `mmlu/`.

| | base | schema-FT (arm 3) | noschema-FT (arm 2) |
|---|---|---|---|
| MMLU overall | 0.500 | 0.535 (+3.5) | 0.597 (+9.7) |

No regression anywhere — a 7.3M-parameter LoRA at 800 iters left general
capability intact. Both adapters *gained*, which should not be read as
knowledge gain: nothing in PromQL teaches the social-science questions that
moved most. The likely mechanism is the experiment's recurring theme —
format. MMLU is loglikelihood-scored, and a model trained to emit terse,
immediate completions concentrates probability mass on short continuations;
the adapter trained on the tersest prompts (bare Q/A, arm 2) gained the
most. Hypothesis, not established: 0-shot, n=228, single seed, and the
per-token likelihoods needed to confirm it aren't retained by the harness.
