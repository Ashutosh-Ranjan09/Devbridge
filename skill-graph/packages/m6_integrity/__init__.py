"""M6 submodule 6.5 — integrity analytics.

Reads the evidence log and reports what a careful reader should notice about the
SHAPE of the evidence. It writes nothing and changes no score.

    from m6_integrity import IntegrityAnalyser
    report = IntegrityAnalyser(engine=engine).analyse(events, as_of, states=states)
"""
__version__ = "1.0.0"

from .analyser import IntegrityAnalyser
from .findings import SEVERITIES, Finding, IntegrityReport
from .rules import IntegrityRules, default_rules

__all__ = ["IntegrityAnalyser", "IntegrityReport", "Finding", "SEVERITIES",
           "IntegrityRules", "default_rules", "__version__"]
