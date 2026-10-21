"""Deterministic filters between the model and the rules.

Grounding proves a claim's text is really in the document. It does **not** prove the
model classified that text correctly — and misclassification is just as capable of
producing a false decisive finding as a hallucination.

Every filter here exists because a real model failed on a real CV:

- `qwen3:1.7b` returned two JEE ranks labelled `platform: "codeforces"`. P2 would have
  looked for rank 873 in the Codeforces contest history, failed to find it, and fired a
  decisive contradiction against a candidate who did nothing wrong.
- It assigned "500+ problems across LeetCode, Codeforces and GeeksforGeeks" to
  Codeforces alone. P3 would then compare 500 against one platform's count.
- The education pass returned three projects as degrees, and the skills pass invented
  `expert` bands out of project prose.
- It emitted the same rating claim five times.

None of these is fixable by prompting. `qwen3:4b`, told explicitly to ignore JEE ranks,
returned them anyway. A prompt is not an enforcement mechanism.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from cvv.models import Claim, ClaimKind, Platform, Proficiency
from cvv.reference import excluded_exams

# X1 — entrance rank against a published cutoff is excluded on fairness grounds. JEE
# cutoffs vary enormously by reservation category, so a category-blind comparison
# systematically flags reserved-category candidates for a rank that is entirely valid.
#
# The NAMES are regional data (data/excluded-exams.json); the enforcement is here, in
# code, matched against the VERBATIM rather than the model's platform label. The model
# controls the label and got it wrong — qwen3:1.7b returned JEE ranks relabelled as
# `codeforces` — but it cannot alter text it copied from the document.

# Platforms a claim may name. Two or more in one sentence means the number is an
# aggregate and cannot be attributed to any single source.
#
# Built FROM the contract's enum rather than beside it: a platform added to `Platform`
# and forgotten here would stop being counted toward an aggregate, and P3 would
# compare a three-source total against one source. The extras are sites this system
# will never connect to but that a CV names in the same breath — they matter for
# detecting the aggregate, not for checking it.
_UNCONNECTED = ("hackerearth", "geeksforgeeks", "spoj", "topcoder", "codingninjas", "kaggle")
PLATFORM_MENTION = re.compile(
    r"\b(?:" + "|".join(sorted({*(p.value for p in Platform), *_UNCONNECTED})) + r")\b",
    re.I,
)

# Lower is more specific. A specific claim wins a span it shares with a vaguer one.
_PRIORITY: dict[ClaimKind, int] = {
    ClaimKind.IDENTIFIER: 0,
    ClaimKind.PROFILE: 1,
    ClaimKind.DECLARATION_MARKER: 2,
    ClaimKind.ACHIEVEMENT: 3,
    ClaimKind.CERTIFICATION: 4,
    ClaimKind.PROJECT: 5,
    ClaimKind.EMPLOYMENT: 6,
    ClaimKind.EDUCATION: 7,
    ClaimKind.SKILL: 8,
}

# Kinds that describe a whole region of the document. Two of these overlapping is a
# classification conflict. The others legitimately nest inside them — a profile handle
# lives inside the achievement sentence that mentions it.
_CONTAINER_KINDS = frozenset(
    {
        ClaimKind.ACHIEVEMENT,
        ClaimKind.CERTIFICATION,
        ClaimKind.PROJECT,
        ClaimKind.EMPLOYMENT,
        ClaimKind.EDUCATION,
        ClaimKind.SKILL,
    }
)


def names_excluded_exam(verbatim: str) -> bool:
    return excluded_exams().search(verbatim) is not None


def platforms_named(verbatim: str) -> set[str]:
    return {m.lower() for m in PLATFORM_MENTION.findall(verbatim)}


def is_aggregate(verbatim: str) -> bool:
    """"500+ problems across LeetCode, Codeforces and GeeksforGeeks" names three
    sources, so the number belongs to no single one of them. A rule that compares it
    against one platform's count is comparing the wrong things."""
    return len(platforms_named(verbatim)) >= 2


def semantic_key(claim: Claim) -> tuple[object, ...]:
    """Identity for deduplication.

    Not the span: the model returns the same claim with slightly different verbatims,
    which ground to different offsets and survive a span-keyed dedup. Five copies of
    the same rating got through that way.
    """
    if claim.kind is ClaimKind.ACHIEVEMENT:
        return (claim.kind, claim.platform, claim.metric, claim.value)
    if claim.kind is ClaimKind.PROFILE:
        return (claim.kind, claim.platform, claim.handle)
    if claim.kind is ClaimKind.SKILL:
        return (claim.kind, tuple(sorted(claim.skill_refs)), claim.proficiency)
    if claim.kind is ClaimKind.PROJECT:
        return (claim.kind, claim.title)
    if claim.kind is ClaimKind.EDUCATION:
        return (claim.kind, claim.degree, claim.org)
    return (claim.kind, claim.provenance.char_start, claim.provenance.char_end)


def _overlaps(a: Claim, b: Claim) -> bool:
    pa, pb = a.provenance, b.provenance
    return pa.char_start < pb.char_end and pb.char_start < pa.char_end


# A number as a CV writes it, grouping commas included — "1,80,000" is the Indian
# grouping of 180000, and "38,000+" is 38000.
_NUMBER = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    """Every whole number in a text, commas removed."""
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


def value_is_in_its_own_span(claim: Claim) -> bool:
    """The number a claim asserts must appear in the sentence the claim cites.

    THE failure this catches, observed on a real CV: qwen3:1.7b found one achievement
    — Codeforces 1495 Specialist — and then emitted those same field values against
    fourteen different verbatims, including the CV's name header and an unrelated
    OpenSoft line. Grammar-constrained generation repeats a pattern once it has
    committed to one, and `required` fields force it to fill them with something.

    Grounding cannot catch this. Every verbatim is genuine and 1495 is a genuine
    rating; only the pairing is invented. Checking the document is not enough — the
    number has to be in THIS span.

    As a whole NUMBER, not a substring. Version 1 asked `str(value) in verbatim`, so
    a value of 10 "appeared" in "Ranked 1106" and 149 in "rating of 1495" — a model
    truncating a number passed the very check that exists to catch it. In P2 a lower
    rank is a stronger claim, so rank 10 against a recorded 1109 would have been a
    decisive contradiction of an honest candidate.
    """
    value = claim.value
    if value is None:
        return True
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # 1495.0 is the number 1495, not the text "1495.0"
    wanted = numbers_in(str(value))
    if not wanted:
        return str(value) in claim.provenance.verbatim  # a value with no number in it
    return wanted <= numbers_in(claim.provenance.verbatim)


def proficiency_from_span(claim: Claim) -> Proficiency | None:
    """The band a skill claim asserts must be the one its own sentence uses.

    qwen3:1.7b labelled four skill claims `expert` — a word that appears nowhere in
    the CV. It reads as a judgement about the candidate and it was invented wholesale.
    An unstated band is not a failure: a skill line with no band is common, and None
    is the honest answer. Inventing one feeds a wrong value into the tenure checks.
    """
    named = {
        p for p in Proficiency if re.search(rf"\b{p.value}\b", claim.provenance.verbatim, re.I)
    }
    return named.pop() if len(named) == 1 else None


def platform_from_span(claim: Claim) -> str | None:
    """The platform a claim belongs to is whichever one its own sentence names.

    The model labelled "Reached a peak CodeChef rating of 1733" as `codeforces`. P1
    would then have compared 1733 against the Codeforces API's 1495 and fired a
    decisive contradiction. The model controls its label; it does not control text it
    copied out of the document.

    Returns None when the sentence names no platform at all — an unattributable claim.
    """
    named = platforms_named(claim.provenance.verbatim)
    if len(named) == 1:
        return named.pop()
    return None


def apply(claims: Sequence[Claim]) -> tuple[list[Claim], dict[str, int]]:
    """Run every filter, in order, and report what each removed.

    The counts are not decoration. They are the extraction-quality metric: a filter
    that suddenly starts dropping half the claims means the model or the prompt
    changed underneath you.
    """
    dropped = {
        "excluded_exam": 0,
        "value_not_in_span": 0,
        "unattributable": 0,
        "duplicate": 0,
        "span_conflict": 0,
    }
    corrected = 0

    # 1. Excluded exams — read from the verbatim, not from the model's platform label.
    kept = []
    for c in claims:
        if c.kind is ClaimKind.ACHIEVEMENT and names_excluded_exam(c.provenance.verbatim):
            dropped["excluded_exam"] += 1
            continue
        kept.append(c)

    # 2. Every field must be corroborated by the claim's OWN span. This is the filter
    #    that catches one answer pasted onto fourteen sentences — the failure grounding
    #    is structurally blind to, because both halves are true and only the pairing
    #    is invented.
    corroborated: list[Claim] = []
    for c in kept:
        if c.kind is ClaimKind.SKILL:
            # A proficiency band is a claim about the candidate. It must be the band
            # their own sentence uses, or none at all.
            band = proficiency_from_span(c)
            if band is not c.proficiency:
                corrected += 1
                c = c.model_copy(update={"proficiency": band})
            corroborated.append(c)
            continue

        if c.kind is not ClaimKind.ACHIEVEMENT:
            corroborated.append(c)
            continue

        if not value_is_in_its_own_span(c):
            dropped["value_not_in_span"] += 1
            continue

        if is_aggregate(c.provenance.verbatim):
            # Real claim, unattributable number. Flagged, not dropped: a rule reads
            # the flag and abstains with a reason rather than comparing 500 against
            # one platform's count.
            corroborated.append(
                c.model_copy(
                    update={
                        "flags": [*c.flags, "aggregate_across_sources"],
                        "context": {
                            **(c.context or {}),
                            "platforms": sorted(platforms_named(c.provenance.verbatim)),
                        },
                    }
                )
            )
            continue

        actual = platform_from_span(c)
        if actual is None:
            dropped["unattributable"] += 1
            continue
        if actual != (c.platform or "").lower():
            corrected += 1
            c = c.model_copy(update={"platform": actual})
        corroborated.append(c)

    dropped["platform_corrected"] = corrected
    flagged = corroborated

    # 3. Deduplicate on meaning.
    unique: list[Claim] = []
    seen: set[tuple[object, ...]] = set()
    for c in flagged:
        key = semantic_key(c)
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        unique.append(c)

    # 4. One region, one kind. Two container claims over the same text is a
    #    classification conflict, and the more specific kind wins: a project labelled
    #    as education, or an "expert" skill band conjured out of project prose.
    unique.sort(key=lambda c: (_PRIORITY[c.kind], c.provenance.char_start))
    resolved: list[Claim] = []
    for c in unique:
        if c.kind in _CONTAINER_KINDS and any(
            r.kind in _CONTAINER_KINDS and r.kind is not c.kind and _overlaps(r, c)
            for r in resolved
        ):
            dropped["span_conflict"] += 1
            continue
        resolved.append(c)

    resolved.sort(key=lambda c: c.provenance.char_start)
    return resolved, dropped


def excluded_note(claims: Iterable[Claim]) -> list[str]:
    """What the out_of_scope bucket must say, so the reader never infers that an
    unmentioned thing was checked."""
    notes: list[str] = []
    for c in claims:
        if names_excluded_exam(c.provenance.verbatim):
            notes.append(
                f"{c.provenance.verbatim[:70]} — entrance-exam rank, deliberately not "
                "checked: cutoffs vary by reservation category and a category-blind "
                "comparison would flag valid ranks."
            )
    return notes
