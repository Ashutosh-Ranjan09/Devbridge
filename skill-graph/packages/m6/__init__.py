"""DevBridge Module 6 — the skill graph layer.

Six submodules composed into one interface:

    6.0  event projection     m6_projection   verified artefacts -> evidence events
    6.1  ontology service     m6_ontology     skills, volatility tiers, edges
    6.2  evidence ingestor    m6_ingestor     validation, idempotency, consent, log
    6.3  scoring engine       m6_scoring      observation, Kalman, decay, propagation
    6.4  query api            m6_query        intervals, explain, tiered search
    6.5  integrity analytics  m6_integrity    findings about the shape of evidence

    from m6 import M6
    with M6("evidence.db") as m6:
        m6.ingest_report(report)
        print(m6.profile("subj_7a3f9e21", date(2026, 8, 24)))

No trained models. No optimiser. No labelled data. No overall trust score.
"""
__version__ = "1.0.0"

from .api import make_handler, serve
from .facade import M6

__all__ = ["M6", "serve", "make_handler", "__version__"]
