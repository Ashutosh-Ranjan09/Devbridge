"""Query failures, typed so the transport can map them to status codes."""
from __future__ import annotations


class QueryError(Exception):
    status = 400


class UnknownSubject(QueryError):
    """No evidence on record. Distinct from "a developer with a low score" —
    conflating the two would let an empty graph read as a negative assessment."""
    status = 404


class UnknownSkill(QueryError):
    """The skill has no evidence and no path to any for this developer."""
    status = 404


class AggregateRefused(QueryError):
    """Someone asked for one number summarising a developer.

    There is no overall trust score in this system, by design: a single number
    invites exactly the ranking-by-vibe the whole evidence model exists to avoid,
    and it cannot be explained the way a per-skill interval can. Refused loudly
    rather than quietly unimplemented, so the reason is discoverable.
    """
    status = 400


class BadRequirements(QueryError):
    """Job requirements that do not match schemas/job-requirements.schema.json."""
    status = 400

