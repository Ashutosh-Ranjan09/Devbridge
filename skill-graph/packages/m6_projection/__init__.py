"""Event projection: an M5 VerificationReport becomes M6 skill-graph evidence.

    from m6_projection import project
    batch = project(json.load(open("report-full.json")))
    json.dump(batch.to_dict(), out)

Implements contracts/projection-rules.yaml. Output validates against
../schemas/evidence-event.schema.json.
"""
__version__ = "1.0.0"          # tracks contracts/projection-rules.yaml contract_version

from .errors import ContractViolation, MalformedReport, ProjectionError, UnknownSkill
from .models import (EvidenceEvent, EvidenceEventBatch, EventSource, ReliabilityFactor,
                     SkillRef, Suppressed)
from .params import Rules, default_rules
from .projector import project

__all__ = ["project", "Rules", "default_rules", "EvidenceEvent", "EvidenceEventBatch",
           "EventSource", "ReliabilityFactor", "SkillRef", "Suppressed",
           "ProjectionError", "ContractViolation", "MalformedReport", "UnknownSkill",
           "__version__"]
