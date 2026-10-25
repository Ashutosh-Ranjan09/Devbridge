"""What 6.5 produces.

A finding is a statement about the SHAPE of the evidence, addressed to whoever
reads the graph. Three properties are structural, not stylistic:

  it names its evidence      every finding carries the event ids or skills it is
                             about, so a reader can go and look
  it states the innocent     every pattern here has a mundane explanation, and
  explanation                the finding is required to carry it. A signal
                             presented without one reads as an accusation
  it changes no number       findings are attached to a graph, never folded into
                             it
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITIES = ("notice", "attention")
# attention first, then notice — a reader works down the list and should not
# have to scan past the low-signal rows to find the ones that matter.
SEVERITY_ORDER = {"attention": 0, "notice": 1}


@dataclass(frozen=True, slots=True)
class Finding:
    check_id: str
    severity: str
    summary: str
    detail: str
    innocent_explanation: str
    skills: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "severity": self.severity,
            "summary": self.summary,
            "detail": self.detail,
            "innocent_explanation": self.innocent_explanation,
            "skills": list(self.skills),
            "event_ids": list(self.event_ids),
            "metrics": self.metrics,
        }


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    subject_ref: str
    as_of: str
    contract_version: str
    findings: tuple[Finding, ...] = ()
    events_examined: int = 0
    skills_examined: int = 0
    truncated: int = 0

    @property
    def clean(self) -> bool:
        return not self.findings

    def by_severity(self, severity: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == severity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_ref": self.subject_ref,
            "as_of": self.as_of,
            "contract_version": self.contract_version,
            "events_examined": self.events_examined,
            "skills_examined": self.skills_examined,
            "clean": self.clean,
            "counts": {s: len(self.by_severity(s)) for s in SEVERITIES},
            "truncated": self.truncated,
            "findings": [f.to_dict() for f in self.findings],
            # Said explicitly rather than left to be inferred from an empty list.
            "note": ("Nothing to flag about the shape of this evidence."
                     if self.clean else
                     "These describe the evidence, not the person. No score below "
                     "is changed by anything in this report."),
        }
