"""Extraction against a hand-labelled answer: precision, recall and F1 per claim kind.

`cvv evaluate` measures the RULES — corrupt one fact, does the check responsible
notice. It cannot say whether extraction found what the CV claims, because every
mutation starts from the claims extraction already returned. This is the other half
of Phase 5: a person labels what a CV claims, and the extractor is scored against it.

A gold file names its document and lists the claims a careful reader finds in it:

    {"document": "tests/fixtures/cv-vit-synthetic.pdf",
     "claims": [{"kind": "achievement", "anchor": "peak rating 1612",
                 "fields": {"platform": "codeforces", "metric": "max_rating", "value": 1612}}]}

`anchor` is text from the CV that the claim's span must overlap — not the whole
verbatim, because where a model ends a span is not what is being measured. It must
occur exactly once in the document, or the gold file is refused: an ambiguous anchor
would let any claim on either occurrence match.

Fields are compared by the kind of value they hold, the same split guardrail 1 makes.
Tokens (handle, platform, metric, value, years) must be exactly right — a handle off by
one character is someone else's account. Prose (org, title, degree) only has to agree
once case and spacing are set aside, either containing the other, because a model may
legitimately normalise "Vellore Institute of Technology, Vellore". Skills compare as
case-insensitive sets.

Gold files for real CVs hold personal data: keep them under `out/` (ignored by git).
Only the synthetic CV's file is committed, in `data/gold/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cvv.models import Claim, ClaimGraph

GOLD_DIR = Path(__file__).resolve().parents[2] / "data" / "gold"

TOKEN_FIELDS = frozenset({"platform", "handle", "metric", "value", "stated_years", "employment_type"})
PROSE_FIELDS = frozenset({"org", "title", "degree", "issuer"})
SET_FIELDS = frozenset({"skill_refs"})
FIELDS = TOKEN_FIELDS | PROSE_FIELDS | SET_FIELDS


class GoldError(ValueError):
    """A gold file that cannot be scored against its document."""


@dataclass(frozen=True)
class GoldClaim:
    kind: str
    anchor: str
    start: int
    end: int
    fields: dict[str, Any]


@dataclass
class KindScore:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None:
            return None
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class GoldScore:
    document: str
    kinds: dict[str, KindScore] = field(default_factory=dict)
    fields: dict[str, tuple[int, int]] = field(default_factory=dict)  # name -> (right, checked)
    missed: list[str] = field(default_factory=list)  # "kind: anchor" the extractor did not find
    extra: list[str] = field(default_factory=list)  # "kind: verbatim" with no gold claim
    wrong: list[str] = field(default_factory=list)  # "kind.field: got X, gold Y"

    def total(self) -> KindScore:
        out = KindScore()
        for k in self.kinds.values():
            out.tp, out.fp, out.fn = out.tp + k.tp, out.fp + k.fp, out.fn + k.fn
        return out


def load(path: Path, text: str) -> list[GoldClaim]:
    """The gold claims of one file, each located in the document's normalised text."""
    raw = json.loads(path.read_text())
    out: list[GoldClaim] = []
    for i, c in enumerate(raw.get("claims") or []):
        anchor = str(c["anchor"])
        at = text.find(anchor)
        if at < 0:
            raise GoldError(f"{path.name} claim {i}: anchor {anchor!r} is not in the document")
        if text.find(anchor, at + 1) >= 0:
            raise GoldError(f"{path.name} claim {i}: anchor {anchor!r} occurs more than once")
        unknown = set(c.get("fields") or {}) - FIELDS
        if unknown:
            raise GoldError(f"{path.name} claim {i}: no field {sorted(unknown)} is scored")
        out.append(GoldClaim(str(c["kind"]), anchor, at, at + len(anchor), dict(c.get("fields") or {})))
    return out


def _norm(value: object) -> str:
    return " ".join(str(value).casefold().split())


def same(name: str, got: object, want: object) -> bool:
    if got is None:
        return want is None
    if name in SET_FIELDS:
        if not isinstance(got, list | tuple) or not isinstance(want, list | tuple):
            return False
        return {_norm(x) for x in got} == {_norm(x) for x in want}
    if name in PROSE_FIELDS:
        g, w = _norm(got), _norm(want)
        return g in w or w in g
    if isinstance(want, int | float) and isinstance(got, int | float):
        return float(got) == float(want)
    if name == "handle":
        return str(got) == str(want)  # the document's casing: guardrail 1
    return _norm(got) == _norm(want)


def _overlaps(claim: Claim, gold: GoldClaim) -> bool:
    return claim.provenance.char_start < gold.end and gold.start < claim.provenance.char_end


def score(graph: ClaimGraph, gold: list[GoldClaim], document: str = "") -> GoldScore:
    """One-to-one matching, in document order: a gold claim takes the first unmatched
    extracted claim of its kind whose span overlaps its anchor."""
    result = GoldScore(document)
    taken: set[str] = set()
    for g in sorted(gold, key=lambda g: g.start):
        ks = result.kinds.setdefault(g.kind, KindScore())
        match = next(
            (c for c in graph.claims
             if c.claim_id not in taken and c.kind.value == g.kind and _overlaps(c, g)),
            None,
        )
        if match is None:
            ks.fn += 1
            result.missed.append(f"{g.kind}: {g.anchor}")
            continue
        taken.add(match.claim_id)
        ks.tp += 1
        for name, want in g.fields.items():
            got = getattr(match, name)
            got = got.value if hasattr(got, "value") else got  # an enum, as its value
            right, checked = result.fields.get(name, (0, 0))
            ok = same(name, got, want)
            result.fields[name] = (right + ok, checked + 1)
            if not ok:
                result.wrong.append(f"{g.kind}.{name}: got {got!r}, gold {want!r} ({g.anchor})")
    for c in graph.claims:
        if c.claim_id not in taken:
            result.kinds.setdefault(c.kind.value, KindScore()).fp += 1
            result.extra.append(f"{c.kind.value}: {c.provenance.verbatim[:70]}")
    return result


def _pct(x: float | None) -> str:
    return "   —" if x is None else f"{x:4.0%}"


def render(scores: list[GoldScore]) -> str:
    out: list[str] = []
    for s in scores:
        out.append(f"{s.document}")
        out.append(f"  {'kind':20} {'tp':>3} {'fp':>3} {'fn':>3}  precision  recall    f1")
        for kind in sorted(s.kinds):
            k = s.kinds[kind]
            out.append(f"  {kind:20} {k.tp:>3} {k.fp:>3} {k.fn:>3}  {_pct(k.precision):>9}  "
                       f"{_pct(k.recall):>6}  {_pct(k.f1):>4}")
        t = s.total()
        out.append(f"  {'all':20} {t.tp:>3} {t.fp:>3} {t.fn:>3}  {_pct(t.precision):>9}  "
                   f"{_pct(t.recall):>6}  {_pct(t.f1):>4}")
        if s.fields:
            out.append("  fields: " + " · ".join(f"{n} {r}/{c}" for n, (r, c) in sorted(s.fields.items())))
        for label, items in (("missed", s.missed), ("extracted, not in the gold", s.extra),
                             ("wrong field", s.wrong)):
            for item in items:
                out.append(f"  {label}: {item}")
        out.append("")
    out.append("Matched by kind and an anchor the claim's span overlaps. A small gold set "
               "measures one extractor on a few documents; it is not a general accuracy.")
    return "\n".join(out)
