"""Module 6, composed.

Six submodules, one object. Each is independently useful and independently
tested; this exists so a caller does not have to know the wiring order or which
piece owns which contract.

    with M6("evidence.db") as m6:
        m6.ingest_report(report)
        m6.skills("subj_7a3f9e21", as_of)

The wiring itself is the interesting part, and it is deliberately one-way:

    report --6.0--> events --6.2--> log --6.3--> states --6.4--> answers
                                     |                             ^
                                    6.1 ontology ------------------+
                                     |
                                    6.5 reads the log and the states, writes nothing
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from m6_ingestor import EventLog, Ingestor, Receipt
from m6_ontology import default_ontology
from m6_integrity import IntegrityAnalyser, IntegrityReport
from m6_projection import project
from m6_query import QueryService
from m6_scoring import Propagator, ScoringEngine, edges_from_ontology

__all__ = ["M6"]


class M6:
    """The whole skill-graph layer behind one interface."""

    def __init__(self, db_path: str = ":memory:", *, ontology: Any = None,
                 module_version: str = "1.0.0") -> None:
        # `is None`, not `or` — see Ingestor.__init__.
        self.ontology = default_ontology() if ontology is None else ontology  # 6.1
        self.log = EventLog(db_path)                            # 6.2 storage
        self.ingestor = Ingestor(self.log, ontology=self.ontology)
        self.engine = ScoringEngine(ontology=self.ontology)     # 6.3
        self.query = QueryService(self.log, self.engine, ontology=self.ontology)  # 6.4
        self.integrity_analyser = IntegrityAnalyser(engine=self.engine)           # 6.5
        self.module_version = module_version

    # ── lifecycle ───────────────────────────────────────────────────────────
    def close(self) -> None:
        self.log.close()

    def __enter__(self) -> "M6":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── writing ─────────────────────────────────────────────────────────────
    def project(self, report: Mapping[str, Any]) -> dict[str, Any]:
        """6.0 alone — useful when you want to see the events before storing."""
        return project(report, module_version=self.module_version,
                       ontology=self.ontology).to_dict()

    def ingest_report(self, report: Mapping[str, Any]) -> Receipt:
        """6.0 then 6.2. Idempotent: the same report twice stores one copy.

        One CV per developer: the report is then recorded as one of theirs, and whichever
        was checked last is the one that counts — an older report's evidence is skipped
        from then on. A FAILED check is not recorded, so an unreadable upload never
        replaces a CV that worked. Recorded after the ingest, so a refused report is not
        recorded, and a retry of one that failed half way records it then.
        """
        receipt = self.ingestor.ingest(self.project(report))
        if report.get("status") != "failed":
            when = report.get("valid_as_of") or report["evidence_bundle"]["gathered_at"]
            self.log.record_cv(report["verification_id"], report["subject"]["subject_ref"], str(when))
        return receipt

    def ingest_batch(self, batch: Mapping[str, Any]) -> Receipt:
        """6.2 alone — for a batch that arrived over the wire already projected."""
        return self.ingestor.ingest(batch)

    # ── reading ─────────────────────────────────────────────────────────────
    def subjects(self) -> list[str]:
        return self.query.subjects()

    def events(self, subject_ref: str | None = None) -> list[dict[str, Any]]:
        return [e.document for e in self.log.events(subject_ref)]

    def skills(self, subject_ref: str, as_of: date, **kw) -> list[Any]:
        return self.query.skills(subject_ref, as_of, **kw)

    def explain(self, subject_ref: str, skill_id: str, as_of: date, **kw) -> dict[str, Any]:
        return self.query.explain(subject_ref, skill_id, as_of, **kw)

    def search(self, skill_id: str, as_of: date, **kw) -> list[Any]:
        return self.query.search(skill_id, as_of, **kw)

    def states(self, subject_ref: str, as_of: date, *, propagate: bool = True
               ) -> dict[str, Any]:
        """Raw SkillStates — what 6.5 reads and what 6.4 renders."""
        # Per skill, through the log's filtered read — same reason as 6.4:
        # a quarantined skill has no admissible evidence and must not be scored.
        direct = {s: self.engine.fold(
                      [e.document for e in self.log.events_for_skill(s, subject_ref=subject_ref)],
                      s, as_of,
                      subject_ref=subject_ref)
                  for s in self.log.resolved_skills(subject_ref)}
        if not propagate:
            return direct
        return Propagator(self.engine).propagate(
            direct, edges_from_ontology(self.ontology), as_of)

    def integrity(self, subject_ref: str, as_of: date) -> IntegrityReport:
        """6.5. Reads the log and the states; changes nothing."""
        return self.integrity_analyser.analyse(
            self.events(subject_ref), as_of, subject_ref=subject_ref,
            states=self.states(subject_ref, as_of),
            quarantined=self.log.quarantined())

    # ── one call that answers "what do we know about this person" ───────────
    def profile(self, subject_ref: str, as_of: date) -> dict[str, Any]:
        """Everything 6.4 and 6.5 can say, in one document.

        Note what is NOT in here: any number summarising the person. The skills
        are a list of intervals and the integrity findings sit beside them, not
        folded into them.
        """
        return {
            "subject_ref": subject_ref,
            "as_of": as_of.isoformat(),
            "parameter_version": self.engine.p.parameter_version,
            "ontology_version": self.ontology.ontology_version,
            "skills": [v.to_dict() for v in self.skills(subject_ref, as_of)],
            "integrity": self.integrity(subject_ref, as_of).to_dict(),
            "note": ("Per-skill intervals with an integrity report beside them. "
                     "This layer publishes no overall score, and nothing in the "
                     "integrity report changes a number in the skills list."),
        }

    # ── introspection ───────────────────────────────────────────────────────
    def versions(self) -> dict[str, str]:
        """Every contract and package version that shaped an answer. A score
        without these cannot be reproduced or disputed."""
        import m6_ingestor, m6_integrity, m6_ontology, m6_projection
        import m6_query, m6_scoring
        from m6_projection.params import default_rules as projection_rules
        return {
            "m6": __import__("m6").__version__,
            "m6_projection": m6_projection.__version__,
            "m6_ontology": m6_ontology.__version__,
            "m6_ingestor": m6_ingestor.__version__,
            "m6_scoring": m6_scoring.__version__,
            "m6_query": m6_query.__version__,
            "m6_integrity": m6_integrity.__version__,
            "projection_rules": projection_rules().contract_version,
            "parameters": self.engine.p.parameter_version,
            "integrity_rules": self.integrity_analyser.rules.contract_version,
            "ontology": self.ontology.ontology_version,
        }
