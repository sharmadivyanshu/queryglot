import pytest

from queryglot.catalog import Catalog, SchemaItem


@pytest.fixture
def catalog() -> Catalog:
    c = Catalog()
    c.add(
        SchemaItem(
            name="http_server_request_duration_seconds",
            backend="prometheus",
            kind="metric",
            type="histogram",
            help="HTTP request latency",
            labels=("route", "method", "status"),
        ),
        SchemaItem(
            name="http_requests_total",
            backend="prometheus",
            kind="metric",
            type="counter",
            help="Total HTTP requests served",
            labels=("route", "method", "status"),
        ),
        SchemaItem(
            name="process_resident_memory_bytes",
            backend="prometheus",
            kind="metric",
            type="gauge",
            help="Resident memory size in bytes",
        ),
        SchemaItem(
            name="orders_queue_depth",
            backend="prometheus",
            kind="metric",
            type="gauge",
            help="Pending orders awaiting processing",
        ),
        SchemaItem(
            name="level",
            backend="elasticsearch",
            kind="field",
            type="keyword",
            parent="app-logs",
        ),
        SchemaItem(
            name="message",
            backend="elasticsearch",
            kind="field",
            type="text",
            parent="app-logs",
        ),
        SchemaItem(
            name="@timestamp",
            backend="elasticsearch",
            kind="field",
            type="date",
            parent="app-logs",
        ),
    )
    return c


class ScriptedLLM:
    """Returns queued completions in order; repeats the last one."""

    def __init__(self, *completions: str):
        self.completions = list(completions)
        self.calls: list[str] = []
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append(prompt)
        self.prompts.append((system, prompt))
        if len(self.completions) > 1:
            return self.completions.pop(0)
        return self.completions[0]


class FakeBackend:
    """Configurable backend: which queries validate, what execute returns."""

    name = "prometheus"
    language = "PromQL"
    supports_range = True

    def __init__(
        self, valid: set[str] | None = None, data: object = "DATA", execute_ok: bool = True
    ):
        self.valid = valid
        self.data = data
        self.execute_ok = execute_ok
        self.executed: list[str] = []
        self.range_calls: list[tuple[str, float, float, float]] = []

    def introspect(self):
        return []

    def validate(self, query: str):
        from queryglot.backends import Validation

        if self.valid is None or query in self.valid:
            return Validation(ok=True)
        return Validation(ok=False, error=f"parse error in {query!r}")

    def execute(self, query: str):
        from queryglot.backends import Execution

        self.executed.append(query)
        if self.execute_ok:
            return Execution(ok=True, data=self.data)
        return Execution(ok=False, error="boom")

    def execute_range(self, query: str, start: float, end: float, step: float):
        if not self.supports_range:
            raise NotImplementedError("fake backend range disabled")
        self.range_calls.append((query, start, end, step))
        return self.execute(query)


class IntrospectingBackend(FakeBackend):
    """FakeBackend whose introspect() actually returns schema, so retrieval
    clears the gate and the graph reaches compile (i.e. calls the LLM)."""

    def introspect(self):
        return [
            SchemaItem(
                name="http_server_request_duration_seconds",
                backend="prometheus",
                kind="metric",
                type="histogram",
                help="HTTP request latency",
                labels=("route", "method", "status"),
            )
        ]
