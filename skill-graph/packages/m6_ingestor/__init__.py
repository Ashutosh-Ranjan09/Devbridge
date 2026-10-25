"""M6 submodule 6.2 — evidence ingestor.

Accepts EvidenceEventBatch documents into an append-only log that 6.3 folds.

    from m6_ingestor import EventLog, Ingestor
    with EventLog("evidence.db") as log:
        receipt = Ingestor(log).ingest(batch)

Validation, idempotency, consent refusal, immutable persistence, quarantine for
unknown skills — and deliberately no modelling of any kind. Skill resolution is
6.1's: the ingestor holds a SkillResolver and never reaches past `knows()`.
"""
__version__ = "1.0.0"

from .api import make_handler, serve
from .errors import (ConflictingEvent, ConsentRefused, ImmutableLog, IngestError,
                     SchemaInvalid)
from .ingestor import Ingestor, Receipt
from .store import EventLog, StoredEvent, content_hash

__all__ = ["Ingestor", "Receipt", "EventLog", "StoredEvent", "content_hash",
           "make_handler", "serve", "IngestError", "SchemaInvalid", "ConsentRefused",
           "ConflictingEvent", "ImmutableLog", "__version__"]

# The ontology is NOT re-exported here. 6.1 owns it, and every consumer imports
# it from m6_ontology directly — importing it through the ingestor is what made
# 6.3 and 6.4 depend on 6.2 for a graph the ingestor is not even allowed to
# traverse. tests/m6_ontology/test_boundaries.py holds that line.
