"""A result → an EvidenceEventBatch for the skill graph (M6).

The batch is checked against ../schemas/evidence-event.schema.json before it leaves,
the same contract M6's ingestor checks on arrival. The event carries FACTS — the
pattern's skill, its level, how many hidden tests passed — and how far to trust them
(contracts/evidence.yaml). What a score is WORTH is M6's decision, in its parameter
file; this module never computes an ability.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any

import yaml

from assess import __version__
from assess.config import REPO, ROOT
from assess.models import Result

SCHEMA = REPO / "schemas" / "evidence-event.schema.json"
CONTRACT = ROOT / "contracts" / "evidence.yaml"


class NotEvidenceError(ValueError):
    """The result is not evidence of anything — the sandbox never ran it."""


def _ts(moment: datetime.datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def batch(result: Result) -> dict[str, Any]:
    rules = yaml.safe_load(CONTRACT.read_text())["assessment_result"]
    if not result.scored or result.score is None or result.outcome.value not in rules["emitted_for"]:
        raise NotEvidenceError(f"{result.session_id}: outcome {result.outcome.value} measured nothing")
    event_id = "ev_" + hashlib.sha256(
        f"{result.session_id}|assessment_result|{result.skill}".encode()).hexdigest()[:12]
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "batch_id": "evb_" + hashlib.sha256(result.session_id.encode()).hexdigest()[:12],
        "verification_id": result.session_id,
        "subject_ref": result.candidate_ref,
        "emitted_at": _ts(result.submitted_at),
        "events": [{
            "event_id": event_id,
            "kind": "assessment_result",
            "occurred_at": _ts(result.submitted_at),
            "observed_at": _ts(result.submitted_at),
            "skill_refs": [{"skill_id": result.skill, "relevance": float(rules["relevance"])}],
            "strength": float(rules["strength"]),
            "reliability": float(rules["reliability_base"]),
            "reliability_base": float(rules["reliability_base"]),
            "reliability_factors": [],
            "direction": "positive",
            "source": {"module": "assessment", "module_version": __version__,
                       "origin": "sandbox", "verification_id": result.session_id,
                       "evidence_ref": f"{result.pattern_id}@v{result.pattern_version}:{result.variant_id}"},
            "payload": {
                "pattern": result.pattern_id, "pattern_version": result.pattern_version,
                "variant_id": result.variant_id, "level": result.level.value,
                "passed": result.score.passed, "total": result.score.total,
                "core": f"{result.score.core_passed}/{result.score.core_total}",
                "twist": f"{result.score.twist_passed}/{result.score.twist_total}",
                "outcome": result.outcome.value,
                "attempt": result.attempt,             # which submission counted: the last
                "time_used_seconds": result.time_used_seconds,
            },
        }],
        "not_emitted": [],
    }
    validate(doc)
    return doc


def validate(doc: dict[str, Any]) -> None:
    import jsonschema

    jsonschema.validate(doc, json.loads(SCHEMA.read_text()))
