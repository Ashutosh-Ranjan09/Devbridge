"""The model seam.

Development runs on local open-source models through Ollama — free, reproducible, and
no data leaves the machine. A hosted model can be swapped in later by implementing this
protocol; nothing else in the system changes, because nothing else in the system talks
to a model.

The protocol is deliberately narrow: give it a prompt and a JSON schema, get back a
dict. No tools, no conversation, no agent loop. The model translates and nothing more.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from cvv.config import settings

# num_ctx defaults to 4096 in Ollama and truncates SILENTLY — claims from the bottom
# of a CV vanish with no error. Set explicitly on every call.
NUM_CTX = settings.num_ctx
CHARS_PER_TOKEN = 3.2  # conservative for English prose


class ContextOverflowError(ValueError):
    """The prompt would be silently truncated. Never let this pass as a normal run."""


class LLMProvider(Protocol):
    """Give it a prompt and a schema, get a dict back."""

    model_id: str

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class OllamaProvider:
    """Local inference.

    `format` grammar-constrains generation to the schema, so the response is
    structurally valid by construction. That does not make it TRUE — which is what
    grounding is for.

    temperature=0 and a fixed seed, so the same document gives the same claims on a
    re-run. A verification that cannot be reproduced cannot be defended.
    """

    def __init__(
        self,
        model_id: str | None = None,
        *,
        url: str | None = None,
        seed: int | None = None,
        num_ctx: int | None = None,
        num_gpu: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.model_id = model_id or settings.ollama_model
        self.url = url or f"{settings.ollama_url}/api/chat"
        self.seed = settings.seed if seed is None else seed
        self.num_ctx = num_ctx or settings.num_ctx
        # None lets Ollama pick the GPU/CPU layer split from whatever VRAM is free,
        # which is the one measured source of non-determinism here. See config.py.
        self.num_gpu = settings.num_gpu if num_gpu is None else num_gpu
        self.timeout = timeout or settings.request_timeout

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        estimated = int(len(prompt) / CHARS_PER_TOKEN)
        if estimated > self.num_ctx * 0.9:
            raise ContextOverflowError(
                f"prompt is ~{estimated} tokens against num_ctx={self.num_ctx}. Ollama "
                "would truncate silently and the end of the CV would vanish. Raise "
                "num_ctx or send a narrower section."
            )

        response = httpx.post(
            self.url,
            timeout=self.timeout,
            json={
                "model": self.model_id,
                "stream": False,
                "think": False,  # qwen3 emits reasoning tokens otherwise
                "format": schema,
                "options": {
                    "temperature": 0,
                    "seed": self.seed,
                    "num_ctx": self.num_ctx,
                    **({"num_gpu": self.num_gpu} if self.num_gpu is not None else {}),
                },
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        content: str = response.json()["message"]["content"]
        parsed: dict[str, Any] = json.loads(content)
        return parsed

    def loaded_split(self) -> str | None:
        """How Ollama has actually placed the model right now, e.g. "11%/89% CPU/GPU".

        Worth recording in a report's provenance: with num_gpu unpinned this is what
        decides whether a re-run reproduces, and a stored report should say which
        configuration produced it.
        """
        try:
            base = self.url.rsplit("/api/", 1)[0]
            models = httpx.get(f"{base}/api/ps", timeout=5.0).json().get("models", [])
        except (httpx.HTTPError, KeyError, ValueError):
            return None
        for m in models:
            if m.get("name") == self.model_id or m.get("model") == self.model_id:
                total = m.get("size", 0)
                gpu = m.get("size_vram", 0)
                if total:
                    return f"{round(100 * gpu / total)}% GPU ({gpu / 1e9:.1f} of {total / 1e9:.1f} GB)"
        return None


class ClaudeCodeProvider:
    """Claude through the local Claude Code wrapper. Same contract as OllamaProvider.

    No `format` field exists here, so the schema rides in the prompt. No seed or
    temperature either, so runs are not reproducible — model_id says which backend
    produced a report. Each call is a fresh conversation (no session_id), so no pass
    sees another pass's section.
    """

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


def default_provider(model_id: str | None = None) -> LLMProvider:
    if settings.llm_backend == "claude-code":
        return ClaudeCodeProvider(model_id)
    return OllamaProvider(model_id)
