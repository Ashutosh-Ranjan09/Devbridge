"""M6 submodule 6.1 — ontology service.

Owns the answer to three questions that every other submodule asks and none of
them may decide for itself: does this skill exist, how fast does it decay, and
what does it imply.

    from m6_ontology import default_ontology
    onto = default_ontology()
    onto.knows("typescript")      # 6.2 — quarantine or accept
    onto.tier("typescript")       # 6.3 — which half-life applies
    onto.neighbours("cpp")        # 6.3 — where evidence may propagate
    onto.skill_ids()              # 6.4 — the filter UI

The graph itself is ../schemas/skills/ontology.yaml. Nothing here defines a skill,
a tier or an edge in code.
"""
__version__ = "1.0.0"

from .errors import InvalidOntology, OntologyError, UnknownSkill
from .graph import SEED, SKILL_ID, Edge, SeedOntology, Skill, default_ontology
from .resolver import AcceptAll, SkillResolver

__all__ = ["SeedOntology", "Skill", "Edge", "SkillResolver", "AcceptAll",
           "default_ontology", "SEED", "SKILL_ID", "OntologyError",
           "InvalidOntology", "UnknownSkill", "__version__"]
