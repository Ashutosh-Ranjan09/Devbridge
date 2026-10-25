"""The port every other submodule depends on — deliberately two methods wide.

6.2 must be able to ask "is this a real node?" and nothing else. If the ingestor
could reach the edges it would eventually start traversing them, and propagation
would quietly move from read time in 6.3 to write time in 6.2, where it cannot
be turned off or explained. Keeping the port narrow is what prevents that, so
the narrowness is a constraint rather than an accident of what was needed first.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SkillResolver(Protocol):
    """What an ingestor needs from an ontology, and nothing more."""

    def knows(self, skill_id: str) -> bool: ...

    @property
    def ontology_version(self) -> str: ...


class AcceptAll:
    """Resolves everything. For tests that are not about quarantine, and for a
    deployment that deliberately wants the ontology to grow from evidence.

    Its version string is not a version number on purpose: a receipt saying
    `ontology_version: accept-all` is a legible admission that nothing was
    checked, where `0.0.0` would read like a real ontology that happened to be
    empty.
    """

    ontology_version = "accept-all"

    def knows(self, skill_id: str) -> bool:  # noqa: ARG002 - the point is it ignores it
        return True
