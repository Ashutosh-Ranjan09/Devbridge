"""Pure decision functions. No I/O, no clock, no report structure — everything
here takes plain values so each rule is testable on its own.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping

from .params import Rules


def normalise_skill(name: str, rules: Rules) -> str:
    """Lower-case and resolve through the alias table. `mongoose` and `next` are
    build-tool names, not skills."""
    key = name.strip().lower()
    return rules.aliases.get(key, key.replace(" ", "_"))


def substance_band(repo: Mapping[str, Any], rules: Rules) -> tuple[str, int]:
    """Which substance band a repository falls in.

    Bands are evaluated in declared order. Within a band, `*_lt` conditions are
    OR-ed (any one is enough to demote) and `*_gte` conditions are AND-ed (all
    must hold to promote). A repository matching nothing lands in `substantial`,
    the neutral middle — never in `large` by default.

    An UNKNOWN counter is not zero. M5 sends `commit_count: null` when it never
    asked — for a repository the candidate owns, it reads the files instead — and
    `or 0` turned that into "fewer than ten commits", so every repository on the
    first real report was `trivial`, including one with 111 authored files. A
    condition over an unknown value is skipped: it can neither demote nor promote,
    and a repository can only reach `large` on counters that were actually read.
    """
    if repo.get("is_readme_only"):
        return "trivial", rules.band_spec("trivial")["index"]

    values = {"commits": repo.get("commit_count"), "size_kb": repo.get("size_kb")}

    for name in rules.band_order:
        spec = rules.band_spec(name)
        lts = [values[k[:-3]] < v for k, v in spec.items()
               if k.endswith("_lt") and values[k[:-3]] is not None]
        gtes = [values[k[:-4]] is not None and values[k[:-4]] >= v
                for k, v in spec.items() if k.endswith("_gte")]
        if lts and any(lts):
            return name, spec["index"]
        if gtes and all(gtes):
            return name, spec["index"]
    return "substantial", rules.band_spec("substantial")["index"]


def repo_strength(band_index: int, rules: Rules) -> float:
    base, per = rules.repo_strength
    return round(base + per * band_index, 4)


def language_relevances(languages: Mapping[str, int], rules: Rules) -> dict[str, float]:
    """Bytes per language into skill relevance.

    A language below `min_bytes_share` of the repository is incidental — a CSS
    file in a TypeScript project is not evidence of CSS ability — and is dropped
    rather than emitted at low relevance, which would fill the graph with skills
    nobody claimed.
    """
    cfg = rules.language
    total = sum(languages.values())
    if total <= 0:
        return {}
    out: dict[str, float] = {}
    for lang, num_bytes in languages.items():
        share = num_bytes / total
        if share < cfg["min_bytes_share"]:
            continue
        rel = cfg["intercept"] + cfg["slope"] * share
        out[normalise_skill(lang, rules)] = round(min(max(rel, cfg["min"]), cfg["max"]), 4)
    return out


def framework_relevance(skill: str, rules: Rules) -> float:
    fw = rules.framework
    return float(fw["secondary"] if skill in fw["secondary_skills"] else fw["primary"])


def apply_factors(
    base: float,
    direction: str,
    factor_names: Iterable[str],
    rules: Rules,
) -> tuple[float, tuple[tuple[str, float, str], ...]]:
    """Multiply reliability_base by each named factor, respecting direction scope.

    `ownership_unverified` is `positive_only`: a self-claimed account that
    CONTRADICTS the CV is credible, because nobody lists a handle that
    undermines them. One that corroborates could be anyone's. So the cap applies
    only to events that would raise a score.
    """
    reliability = base
    applied: list[tuple[str, float, str]] = []
    for name in factor_names:
        value, scope, rationale = rules.factor(name)
        if scope == "positive_only" and direction != "positive":
            continue
        if value == 1.0:
            continue  # inert by declaration; recording it would be noise
        reliability *= value
        applied.append((name, value, rationale))
    return round(reliability, 6), tuple(applied)


def event_id(verification_id: str, kind: str, discriminator: str) -> str:
    """Stable across re-runs of the same report, so replaying a batch is a no-op.

    O4 needs event ids for the total order it folds in; idempotent ingestion
    needs them to be reproducible. A random id would break both.
    """
    digest = hashlib.sha256(f"{verification_id}|{kind}|{discriminator}".encode()).hexdigest()
    return f"ev_{digest[:12]}"
