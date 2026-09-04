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

# num_ctx defaults to 4096 in Ollama and truncates SILENTLY — claims from the bottom
# of a CV vanish with no error. Set explicitly on every call.
NUM_CTX = 8192
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
        model_id: str = "qwen3:1.7b",
        *,
        url: str = "http://localhost:11434/api/chat",
        seed: int = 7,
        num_ctx: int = NUM_CTX,
        timeout: float = 600.0,
    ) -> None:
        self.model_id = model_id
        self.url = url
        self.seed = seed
        self.num_ctx = num_ctx
        self.timeout = timeout

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
                },
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        content: str = response.json()["message"]["content"]
        parsed: dict[str, Any] = json.loads(content)
        return parsed
