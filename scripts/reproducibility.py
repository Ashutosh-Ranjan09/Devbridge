"""Is extraction reproducible?

CLAUDE.md requires `temperature: 0` and a fixed seed so the same document gives the
same claims on a re-run. A verification that cannot be reproduced cannot be defended,
and phase 5's metrics are meaningless if a claim count moves on its own — you could
not attribute a change to a code change.

Observed during the spike: the achievements pass proposed 14, then 6, then 8, then 6
items across otherwise identical runs. This measures whether that is real, and where
it comes from.

    uv run python scripts/reproducibility.py [n] [model]
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

from cvv.extract import PASSES, extract
from cvv.ingest import read, section_text
from cvv.providers import OllamaProvider

CV = Path("docs/CV-SDE-AR.pdf")


def digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]


def one_pass(n: int, model: str) -> None:
    """The narrowest possible test: one pass, one section, same seed, N times."""
    doc = read(CV)
    achievements = next(p for p in PASSES if p.name == "achievements")
    text, _ = section_text(doc, achievements.sections)
    provider = OllamaProvider(model)

    print(f"\n=== one pass, {n} runs · {model} · {len(text)} chars in ===")
    hashes: list[str] = []
    for i in range(n):
        t0 = time.time()
        raw = provider.complete_json(achievements.prompt(text), achievements.schema())
        items = raw.get("claims", [])
        h = digest(items)
        hashes.append(h)
        print(f"  run {i + 1:2}  {time.time() - t0:5.1f}s  {len(items):2} items  {h}")

    counts = Counter(hashes)
    print(f"\n  distinct outputs: {len(counts)} of {n}")
    for h, c in counts.most_common():
        print(f"    {h}  x{c}")


def whole_pipeline(n: int, model: str) -> None:
    """End to end, which is what actually has to be reproducible."""
    doc = read(CV)
    print(f"\n=== whole pipeline, {n} runs · {model} ===")
    hashes: list[str] = []
    for i in range(n):
        t0 = time.time()
        graph, counts = extract(doc, provider=OllamaProvider(model), graph_id="cg_repro")
        # The claim set, ignoring anything that legitimately varies per run.
        shape = sorted(
            (c.kind.value, c.provenance.char_start, c.provenance.char_end, str(c.value))
            for c in graph.claims
        )
        h = digest(shape)
        hashes.append(h)
        print(
            f"  run {i + 1:2}  {time.time() - t0:5.1f}s  {len(graph.claims):2} claims  "
            f"proposed={counts}  {h}"
        )

    counts_by_hash = Counter(hashes)
    print(f"\n  distinct claim sets: {len(counts_by_hash)} of {n}")
    for h, c in counts_by_hash.most_common():
        print(f"    {h}  x{c}")


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    model_id = sys.argv[2] if len(sys.argv) > 2 else "qwen3:1.7b"
    one_pass(runs, model_id)
    whole_pipeline(max(3, runs // 3), model_id)
