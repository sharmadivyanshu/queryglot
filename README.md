# queryglot

**One question, many query languages.** Schema-aware natural-language search
over your observability stack — Prometheus, Elasticsearch — and any
OpenAPI-described API, shipped as an MCP server any agent can plug into.

> "p95 latency by route" is easy. Knowing YOUR latency metric is called
> `http_server_request_duration_seconds` and carries a `route` label — that's
> the actual problem. Frontier models write fluent PromQL over metric names
> that don't exist.

## How it works

```
question ──> retrieve            ──> compile        ──> validate           ──> execute
             (BM25 + synonyms       (LLM, schema        (the backend's OWN     (real data,
              over YOUR schema,      slice in the        parser + unknown-      query shown)
              introspected live)     prompt)             metric check)
                    │                      ▲                   │ parse error
                    │ nothing matches      └─── bounded repair ┘
                    ▼
                 ABSTAIN — refuses to guess a metric name
```

- **Retrieval owns facts** (your metric names, labels, index fields —
  introspected from the live backend, never hallucinated).
- **The model owns syntax** (PromQL / Query DSL — swap in your own fine-tune
  via any OpenAI-compatible endpoint, including `mlx_lm.server` on a Mac).
- **The backend owns truth**: every query is validated by the server's own
  parser (`format_query`, `_validate/query`) before execution, and parse
  errors drive a bounded repair loop.
- **Abstention is a feature**: off-schema questions get a refusal, not an
  invented metric. The eval scores this.

## Use it from any MCP client

```json
{
  "mcpServers": {
    "queryglot": {
      "command": "queryglot-mcp",
      "env": {
        "QUERYGLOT_PROMETHEUS": "http://localhost:9090",
        "QUERYGLOT_ELASTIC": "http://localhost:9200",
        "QUERYGLOT_OPENAPI": "http://localhost:8081/api/v3",
        "QUERYGLOT_LLM_URL": "http://localhost:11434/v1",
        "QUERYGLOT_LLM_MODEL": "qwen3.5:4b",
        "QUERYGLOT_SERVE_TOKEN": "your-token-here",
        "QUERYGLOT_CORS_ORIGINS": "https://example.com"
      }
    }
  }
}
```

Environment variables:
- `QUERYGLOT_SERVE_TOKEN` — bearer token for `/api/*` endpoints. Empty = open (intended for localhost/demo).
- `QUERYGLOT_CORS_ORIGINS` — comma-separated allowed origins for embedding (queryglot-serve only).

Tools exposed: `search(question, backend?)`, `list_schema(query?)`,
`refresh_schema()`.

Or the CLI:

```bash
queryglot "p95 http request duration" --prometheus http://localhost:9090
```

Or run an HTTP server with the ask-widget and query playground:

```bash
queryglot-serve --prometheus http://localhost:9090
```

Any OpenAI-compatible endpoint works as the model: OpenAI, Ollama, or your own
LoRA behind `mlx_lm.server` — that last one is the point of `finetune/`.

## Evaluation — deterministic, no LLM judge

`eval/run_eval.py` scores golden questions against a live backend: the
outcome must match, required metrics must appear in the query, and the query
must actually execute. Abstention cases score correct only on refusal.
`eval/docker-compose.yml` brings up real backends; CI runs the full
integration suite against a real Prometheus and petstore on every push.

## Status

**v0.1.0** — the RAG arm, working end to end.

- [x] Prometheus + Elasticsearch backends (introspect / validate / execute)
- [x] BM25 + synonym schema retrieval, exact-name boosting
- [x] compile -> validate -> repair -> execute LangGraph with abstention
- [x] MCP server + CLI; 89 tests incl. live-Prometheus and live-petstore
      integration; CI
- [x] Verified NL->PromQL dataset generator (parse+execute gated, metric-disjoint splits)
- [x] Bake-off complete — RAG 8/10, FT-only 3/10, FT+RAG 9/10 on the same
      golden set; full analysis in `finetune/README.md`, build history and
      bugs in `DESIGN_NOTES.md`
- [x] OpenAPI backend — read-only, GET-only by construction; validated
      against the spec's own contract; petstore-verified in CI
- [ ] Loki (LogQL) backend; Datadog connector

## Where this is going: apps that agents can actually use

The `Backend` protocol (introspect / validate / execute) is not
observability-specific. The same loop pointed at a product's own OpenAPI spec
or database turns any app into something an AI can query *safely*:

- **OpenAPI backend — shipped.** Introspects a product's own spec into the
  catalog; questions compile into validated, GET-only API calls. Existing
  OpenAPI->MCP generators dump every endpoint as a tool, which measurably
  degrades agents (arXiv 2411.15399) and executes whatever the model asks.
  queryglot's contribution is the missing layer: schema-grounded retrieval,
  server-side validation, and abstention.
- **Customer-facing ask widget** — an embeddable search box backed by the
  same engine: visitors' questions become validated queries against the
  app's data, never hallucinated ones.
- **`llms.txt` + MCP endpoint generation** — one schema catalog, two
  audiences: humans get the widget, agents get a typed, validated interface
  instead of scraping. Discoverability for the agentic web, with execution
  semantics — not just markup.

## Known limits

- `metric_candidates` (unknown-metric detection) is regex-based and
  best-effort; the backend parser owns syntax, this only improves error
  messages. Complex PromQL may slip past it — never through the parser.
- Backend auto-routing is retrieval-strength-based; ambiguous questions
  ("errors in checkout") can route to the wrong store. Pass `backend=` to pin.
- Synonym table is small and English-only, grown from eval failures.
- When a backend's catalog is smaller than the retrieval k (8), retrieval
  sends the whole catalog and the abstention gate rarely fires — abstention
  then rests on the validation layer.

## License

MIT
