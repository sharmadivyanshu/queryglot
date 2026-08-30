"""Golden-set scoring: a must_reference element may be a string (required) or
a list of strings (any one satisfies — e.g. goroutines has two valid metrics)."""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "run_eval", pathlib.Path(__file__).parent.parent / "eval" / "run_eval.py"
)
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


def test_plain_string_reference_must_appear():
    assert run_eval.satisfied("rate(http_requests_total[5m])", ["http_requests_total"])
    assert not run_eval.satisfied("up", ["http_requests_total"])


def test_list_element_means_any_of():
    refs = [["go_goroutines", "go_sched_goroutines_goroutines"]]
    assert run_eval.satisfied("go_goroutines", refs)
    assert run_eval.satisfied("sum(go_sched_goroutines_goroutines)", refs)
    assert not run_eval.satisfied("go_threads", refs)


def test_empty_reference_list_is_vacuously_true():
    assert run_eval.satisfied("anything", [])
