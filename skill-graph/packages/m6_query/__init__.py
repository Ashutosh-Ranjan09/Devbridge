"""M6 submodule 6.4 — query API.

Skills endpoint, /explain to the fixed response shape, as_of queries, and search
that returns TIERS rather than a ranking.

    from m6_query import QueryService
    service = QueryService(log, ontology=default_ontology())
    service.explain("subj_7a3f9e21", "typescript", date(2026, 8, 24))

Two constraints shape every response here: there is no overall trust score, and
two candidates may only be ordered when their intervals do not overlap.
"""
__version__ = "1.0.0"

from .api import build_routes, make_handler, serve
from .errors import AggregateRefused, QueryError, UnknownSkill, UnknownSubject
from .ranking import Candidate, Tier, meets_threshold, tiers
from .service import QueryService, SkillView

__all__ = ["QueryService", "SkillView", "Candidate", "Tier", "tiers", "meets_threshold",
           "make_handler", "build_routes", "serve", "QueryError", "UnknownSubject",
           "UnknownSkill", "AggregateRefused", "__version__"]
