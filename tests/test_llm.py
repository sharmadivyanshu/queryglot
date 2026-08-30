"""OpenAICompatibleLLM request shape — the adapters passthrough that works
around mlx-lm 0.31.3 dropping --adapter-path (ModelProvider.load keys
_adapter_map by the resolved model path, so the CLI flag never applies)."""

import io
import json
import urllib.request

import pytest

from queryglot.llm import OpenAICompatibleLLM


@pytest.fixture
def sent(monkeypatch):
    """Capture the JSON body complete() sends; serve a canned response."""
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured.update(json.loads(request.data.decode()))
        body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
        response = io.BytesIO(body)
        response.status = 200
        return response

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


def test_adapters_field_sent_when_configured(sent):
    llm = OpenAICompatibleLLM(base_url="http://x/v1", model="m", adapters="finetune/adapters")
    llm.complete("sys", "prompt")
    assert sent["adapters"] == "finetune/adapters"


def test_adapters_env_var_is_picked_up(sent, monkeypatch):
    monkeypatch.setenv("QUERYGLOT_LLM_ADAPTERS", "finetune/adapters")
    OpenAICompatibleLLM(base_url="http://x/v1", model="m").complete("sys", "p")
    assert sent["adapters"] == "finetune/adapters"


def test_adapters_absent_by_default(sent, monkeypatch):
    monkeypatch.delenv("QUERYGLOT_LLM_ADAPTERS", raising=False)
    OpenAICompatibleLLM(base_url="http://x/v1", model="m").complete("sys", "p")
    assert "adapters" not in sent
