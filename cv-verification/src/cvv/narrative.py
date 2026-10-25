"""Findings to prose — the second and last place a model is called.

The faithfulness guarantee is structural, in three layers, and the third one exists
because the first two were not enough.

**The signature.** `narrate` takes a `FindingsReport` and nothing else. It cannot
reach the document, the claim graph or the evidence bundle, so it cannot introduce a
fact nobody computed — not because the prompt asks it not to, but because the
function has no way to obtain one.

**The shape of the answer.** The model does not write a briefing. It writes ONE
SENTENCE PER FINDING, and Python assembles the briefing around them. Asked for free
prose about a report with four attention findings, qwen3:1.7b opened with "the CV
does not contradict any rules, as all claimed information is verified" — a verdict,
about findings it had been given, in a system whose first principle is that it does
not produce verdicts. Every numeral in that sentence was legal, because there were
none. A model that never writes a global sentence cannot write a false one.

**Containment, per finding.** Each sentence is checked against the finding it claims
to be about, not against the report as a whole. A number that belongs to P1 appearing
in a sentence about G5 is rejected — the same failure the extraction filters exist to
stop, arriving at the other end of the pipeline. A finding with no sentence is
rejected too: omission is how the previous version told its lie.

The model translates, Python verifies, and the verification is what is trusted.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from cvv.models import Discrepancy, FindingsReport, Tier
from cvv.providers import LLMProvider

PROMPT_VERSION = "narrative/v3"

_NUMERAL = re.compile(r"\d+(?:\.\d+)?")

INSTRUCTION = """\
Rewrite each finding below as ONE sentence a busy reviewer can read at a glance.

Rules, all of them absolute:
  - One sentence per finding, and nothing else. No summary, no opening, no closing.
  - Use ONLY what that finding says. Every number in your sentence must appear in it.
  - Where a finding carries an innocent reading, put it in the same sentence, with
    the same weight. "X, though Y" — never X alone.
  - State no verdict. Do not say whether anything is good, bad, or hiring-relevant.
  - Copy the `ref` value exactly into the `ref` field.
  - Do NOT name the rule inside the sentence. The id is printed beside it already,
    so "P2 says the CV claims..." renders as "[P2] P2 says the CV claims...".\
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"ref": {"type": "string"}, "sentence": {"type": "string"}},
                "required": ["ref", "sentence"],
            },
        }
    },
    "required": ["points"],
}


@dataclass(frozen=True)
class Narrative:
    """Prose, and whether it survived the containment check.

    `rejected` is not an error path — it is the normal, safe outcome when a model
    embellishes. The caller prints `text` either way; the difference is that a
    rejected narrative is the deterministic summary rather than the model's.
    """

    text: str
    faithful: bool
    rejected_because: str | None = None


def refs(findings: list[Discrepancy]) -> dict[str, Discrepancy]:
    """A key per finding the model copies back. The rule id when it is unique, so the
    common case is unchanged; `P2#1`, `P2#2` when a rule fired more than once.

    Version 2 keyed sentences by rule id, so a rule firing twice overwrote its own
    first finding, one finding never got a sentence, and every such narrative was
    rejected for omission.
    """
    counts = Counter(f.rule_id for f in findings)
    seen: Counter[str] = Counter()
    out: dict[str, Discrepancy] = {}
    for f in findings:
        seen[f.rule_id] += 1
        out[f.rule_id if counts[f.rule_id] == 1 else f"{f.rule_id}#{seen[f.rule_id]}"] = f
    return out


def facts(finding: Discrepancy, ref: str | None = None) -> dict[str, object]:
    """Exactly what the model may see about one finding.

    No claim text, no document, no evidence bundle. A fact absent here cannot be
    written, and `allowed` below is the same string the sentence is checked against —
    so what the model is shown and what it is held to are the same thing by
    construction rather than by intention.
    """
    return {
        "ref": ref or finding.rule_id,
        "rule": finding.rule_id,
        "says": finding.explanation,
        "innocent_reading": finding.innocent_explanation,
        "details": finding.params,
    }


def strip_rule_prefix(sentence: str, rule_id: str) -> str:
    """Remove a leading "P2 says" / "P2:" / "Rule P2 —" the model prepended.

    The frame already prints `[P2]` beside the sentence, so the model naming it again
    renders as "[P2] P2 says the CV claims...". Asked in the prompt not to, qwen3:1.7b
    did it anyway — guardrail 11, on this system's own second model call: a prompt is
    not an enforcement mechanism, so the id is stripped by code the model cannot
    reach. Only a LEADING mention goes; a rule id in the body of a sentence is a
    citation and stays.
    """
    pattern = rf"^\s*(?:rule\s+)?{re.escape(rule_id)}\s*(?:says|states|reports|found)?\s*[:\u2014\u2013-]?\s*"
    stripped = re.sub(pattern, "", sentence, count=1, flags=re.I)
    if not stripped:
        return sentence
    # Restore the capital the prefix was carrying.
    return stripped[0].upper() + stripped[1:]


def check(sentence: str, allowed: str) -> str | None:
    """Every numeral in the sentence must be in the finding it is about.

    Per finding, not per report. A number that belongs to P1 turning up in a sentence
    about G5 is the "one answer pasted onto fourteen sentences" failure arriving at
    the other end of the pipeline, and a report-wide check would let it through.
    """
    for numeral in _NUMERAL.findall(sentence):
        if numeral not in allowed:
            return f"a sentence states {numeral!r}, which is not in the finding it cites"
    return None


def summarise(report: FindingsReport) -> str:
    """The deterministic fallback, and what a rejected narrative falls back TO.

    Dull on purpose. It is assembled by counting and by copying explanations that
    Python wrote, so it cannot be unfaithful.
    """
    return "\n".join(_frame(report, {}))


def _frame(report: FindingsReport, sentences: dict[str, str]) -> list[str]:
    """The briefing itself, written by Python.

    The counts, the ordering and the "not evaluated" line are never the model's to
    write — they are the parts a reader takes as fact. The model only supplies the
    wording of individual findings, and `sentences` is empty when it supplied none.
    """
    decisive = [f for f in report.discrepancies if f.tier is Tier.DECISIVE]
    attention = [f for f in report.discrepancies if f.tier is Tier.ATTENTION]

    out = [
        f"{len(decisive)} contradicted · {len(attention)} needing context · "
        f"{len(report.buckets.verified)} corroborated · "
        f"{len(report.buckets.not_evaluated)} not evaluated. No score is produced.",
        "",
    ]
    for f in (*decisive, *attention):
        out.append(f"  [{f.rule_id}] {sentences.get(f.finding_id) or f.explanation}")
        # Printed by Python, never by the model. Guardrail 5 says an attention
        # finding is unconstructable without its innocent reading, and a reader must
        # see the two together — that cannot depend on a model remembering to
        # include it. Asked to, qwen3:1.7b copied the headline and dropped this.
        if f.innocent_explanation:
            out.append(f"        though: {f.innocent_explanation}")
    if not decisive and not attention:
        out.append("  No check raised anything. That is not the same as a clean CV —")
        out.append(f"  {len(report.buckets.not_evaluated)} checks could not run at all.")
    return out


def narrate(report: FindingsReport, provider: LLMProvider) -> Narrative:
    """Model wording where it survives the check, Python's wording where it does not."""
    findings = [
        f for f in report.discrepancies if f.tier in (Tier.DECISIVE, Tier.ATTENTION)
    ]
    if not findings:
        # Nothing to rewrite, so nothing to call a model about. The frame is the
        # whole briefing, and it is already true.
        return Narrative("\n".join(_frame(report, {})), faithful=True)

    by_ref = refs(findings)
    payloads = {f.finding_id: json.dumps(facts(f, r), default=str) for r, f in by_ref.items()}
    prompt = (
        f"{INSTRUCTION}\n\nFindings:\n"
        + json.dumps([facts(f, r) for r, f in by_ref.items()], default=str, indent=2)
        + "\n\nReturn JSON only."
    )

    try:
        answer = provider.complete_json(prompt, SCHEMA)
    except Exception as exc:  # a model outage must never fail a report
        return Narrative(summarise(report), faithful=False, rejected_because=str(exc))

    sentences: dict[str, str] = {}
    for point in answer.get("points") or []:
        if not isinstance(point, dict):
            continue
        finding = by_ref.get(str(point.get("ref", "")).strip())
        if finding is None:
            return Narrative(
                summarise(report),
                faithful=False,
                rejected_because=(
                    f"a sentence cites {point.get('ref')!r}, which is no finding's ref"
                ),
            )
        sentence = strip_rule_prefix(str(point.get("sentence", "")).strip(), finding.rule_id)
        if reason := check(sentence, payloads[finding.finding_id]):
            return Narrative(summarise(report), faithful=False, rejected_because=reason)
        sentences[finding.finding_id] = sentence

    missing = [r for r, f in by_ref.items() if f.finding_id not in sentences]
    if missing:
        # Omission is how the previous version lied: given four attention findings it
        # opened with "all claimed information is verified" and cited nothing.
        return Narrative(
            summarise(report),
            faithful=False,
            rejected_because=f"no sentence was written for {', '.join(missing)}",
        )

    return Narrative("\n".join(_frame(report, sentences)), faithful=True)
