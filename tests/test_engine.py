"""Engine-level behaviour: backend selection, caching, and range windows."""

import time

from queryglot.engine import Engine
from tests.conftest import IntrospectingBackend, ScriptedLLM


def test_engine_window_minutes_builds_epoch_window_and_reports_it():
    backend = IntrospectingBackend(valid={"GOOD"})
    engine = Engine([backend], llm=ScriptedLLM("GOOD"))
    before = time.time()
    answer = engine.search("p95 latency by route", window_minutes=30)
    after = time.time()
    assert answer.outcome == "answered"
    (query, start, end, step) = backend.range_calls[0]
    assert before - 1 <= end <= after + 1  # end ≈ now
    assert abs((end - start) - 30 * 60) < 1e-6  # 30-minute span
    assert step == max(15.0, (30 * 60) / 120)  # the spec's step formula
    assert answer.as_dict()["window"] == {"minutes": 30, "step_s": step}


def test_engine_without_window_omits_the_field_and_runs_instant():
    backend = IntrospectingBackend(valid={"GOOD"})
    engine = Engine([backend], llm=ScriptedLLM("GOOD"))
    answer = engine.search("p95 latency by route")
    assert backend.range_calls == []
    assert "window" not in answer.as_dict() or answer.as_dict().get("window") is None


def test_engine_windowed_search_on_rangeless_backend_omits_window():
    """The range path silently falls back to instant execute() — the engine
    must not claim a window ran when it didn't (F1)."""
    backend = IntrospectingBackend(valid={"GOOD"})
    backend.supports_range = False
    engine = Engine([backend], llm=ScriptedLLM("GOOD"))
    answer = engine.search("p95 latency by route", window_minutes=30)
    assert answer.outcome == "answered"
    assert backend.range_calls == []
    assert "window" not in answer.as_dict()
