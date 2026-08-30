"""LLM interface — injectable, with an OpenAI-compatible adapter.

The adapter speaks /v1/chat/completions, which means the SAME code path serves
OpenAI, Ollama, and `mlx_lm.server` running your own fine-tuned adapter on a
Mac. The fine-tune track of this project plugs in here with zero code change:

    llm = OpenAICompatibleLLM(base_url="http://127.0.0.1:8080/v1", model="local")
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Protocol


class LLM(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


def parse_completion(body: dict) -> str:
    """Message content from a chat-completions response, defensively.

    Hybrid "thinking" models (Qwen3.5 and friends) can spend the entire token
    budget on a hidden `reasoning` field and return a message with NO content
    key at all. That is an empty completion, not a crash: the graph's
    validate/repair path handles an empty query like any other bad attempt.
    """
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    return message.get("content") or ""


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        adapters: str | None = None,
    ):
        resolved = base_url or os.getenv("QUERYGLOT_LLM_URL") or "http://127.0.0.1:8080/v1"
        self.base_url = resolved.rstrip("/")
        self.model = model or os.getenv("QUERYGLOT_LLM_MODEL", "default")
        self.api_key = api_key or os.getenv("QUERYGLOT_LLM_KEY", "")
        self.temperature = temperature
        # Thinking models need headroom: reasoning tokens count against the
        # completion budget, and the default server cap (512) can be consumed
        # before any content is emitted.
        self.max_tokens = max_tokens or int(os.getenv("QUERYGLOT_LLM_MAX_TOKENS", "2048"))
        # Escape hatch for hybrid-thinking models: e.g. " /no_think" for Qwen.
        self.system_suffix = os.getenv("QUERYGLOT_LLM_SYSTEM_SUFFIX", "")
        # mlx_lm.server 0.31.3 drops the CLI --adapter-path for EVERY request
        # (ModelProvider.load keys _adapter_map by the already-resolved model
        # path, so the lookup can never hit). The per-request "adapters" field
        # is the supported path that works; only sent when configured, so
        # OpenAI/Ollama payloads are untouched.
        self.adapters = adapters or os.getenv("QUERYGLOT_LLM_ADAPTERS", "")

    def complete(self, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system + self.system_suffix},
                {"role": "user", "content": prompt},
            ],
        }
        if self.adapters:
            payload["adapters"] = self.adapters
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode())
        return parse_completion(body)


_FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)


def extract_query(completion: str) -> str:
    """Models wrap queries in fences and prose; the query is what we keep."""
    match = _FENCE.search(completion)
    text = match.group(1) if match else completion
    return text.strip().strip("`").strip()
