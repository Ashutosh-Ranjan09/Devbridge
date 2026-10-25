"""Failures the ontology can have, kept distinct from every other kind.

An invalid ontology is not a bad request and not a bad batch. It is a broken
deployment: the contract file that decides which skills exist and how fast each
one decays is wrong, and every score computed against it would be wrong in a way
no downstream check could notice.
"""
from __future__ import annotations


class OntologyError(Exception):
    """Base class, so a caller can catch the whole family."""


class InvalidOntology(OntologyError):
    """The seed file does not describe a usable graph.

    Carries every problem found, not just the first. Fixing a contract file one
    error per run is how a half-corrected ontology gets deployed.
    """

    def __init__(self, problems: list[str], path: str | None = None) -> None:
        self.problems = list(problems)
        self.path = path
        where = f" in {path}" if path else ""
        super().__init__(f"{len(self.problems)} problem(s){where}:\n  - "
                         + "\n  - ".join(self.problems))


class UnknownSkill(OntologyError):
    """Asked about a node the ontology does not carry.

    Only raised by the strict accessors. `knows()` returns False instead, because
    the ingestor's whole quarantine behaviour is built on asking that question
    about skills it expects to be absent.
    """
