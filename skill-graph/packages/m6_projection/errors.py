"""Failure modes of the projection, each one distinguishable."""


class ProjectionError(Exception):
    """Base class. Callers may catch this to fail one verification without
    taking down a batch run."""


class ContractViolation(ProjectionError):
    """An invariant from projection-rules.yaml was broken while building the
    batch. This is a bug in this module, never bad input — malformed input
    raises MalformedReport instead."""


class MalformedReport(ProjectionError):
    """The VerificationReport is missing something the projection needs. Raised
    rather than guessed at: a silently-skipped claim is indistinguishable from a
    claim that produced no evidence."""


class UnknownSkill(ProjectionError):
    """A skill string did not resolve through the alias table. The event is
    quarantined rather than dropped — see EvidenceEventBatch.quarantined."""
