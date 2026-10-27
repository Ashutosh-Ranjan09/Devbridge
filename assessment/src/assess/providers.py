"""The model seam — the same two backends cvv uses, behind the same narrow protocol.

Give it a prompt and a JSON schema, get a dict back. No tools, no conversation. In
this module a model only ever CHOOSES from a list it was given or WORDS a story; code
checks every answer and has a fallback for each.

A copy of cvv's providers rather than an import: the modules meet through files in
../schemas, never through each other's code.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from assess.config import settings


class LLMProvider(Protocol):
    model_id: str

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class OllamaProvider:
    """Local, seeded, temperature 0: the same prompt gives the same answer."""

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or settings.ollama_model
        self.url = f"{settings.ollama_url.rstrip('/')}/api/chat"

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            self.url,
            timeout=settings.request_timeout,
            json={
                "model": self.model_id,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0, "seed": settings.seed, "num_ctx": settings.num_ctx},
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        parsed: dict[str, Any] = json.loads(response.json()["message"]["content"])
        return parsed


class ClaudeCodeProvider:
    """Claude through the local Claude Code wrapper. No format field and no seed: the
    schema rides in the prompt, and model_id records which backend answered."""

    def __init__(self, model_id: str | None = None) -> None:
        self.model = model_id or settings.claude_code_model
        self.model_id = f"claude-code:{self.model or 'default'}"
        self.url = f"{settings.claude_code_url.rstrip('/')}/api/chat"

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            self.url,
            timeout=settings.request_timeout,
            headers={"Authorization": f"Bearer {settings.claude_code_api_key}"},
            json={
                "message": f"{prompt}\n\nReply with JSON only, matching this schema:\n"
                f"{json.dumps(schema)}",
                **({"model": self.model} if self.model else {}),
            },
        )
        response.raise_for_status()
        text = response.json()["response"].strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```")
        parsed: dict[str, Any] = json.loads(text)
        return parsed


def default_provider() -> LLMProvider:
    if settings.llm_backend == "claude-code":
        return ClaudeCodeProvider()
    return OllamaProvider()
