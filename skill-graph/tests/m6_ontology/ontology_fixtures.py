"""Fixtures for the ontology suite.

Named `ontology_fixtures` rather than `fixtures` so it cannot shadow the
ingestor suite's module of that name — the runner imports test siblings by bare
name, so two `fixtures` modules in one run would silently cross-wire.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

import yaml  # noqa: E402

from m6_ontology import SeedOntology  # noqa: E402

SEED_PATH = ROOT / "contracts" / "ontology-seed.yaml"

# A graph small enough to reason about entirely, with one edge of each shape the
# real seed uses. Tests that are about VALIDATION mutate a copy of this rather
# than the shipped contract.
GOOD = {
    "ontology_version": "test-1.0",
    "tiers": {"fundamental": "slow", "ecosystem": "medium", "framework": "fast"},
    "skills": {
        "algorithms": {"tier": "fundamental", "label": "Algorithms"},
        "cpp": {"tier": "fundamental", "label": "C++"},
        "typescript": {"tier": "ecosystem", "label": "TypeScript"},
        "react": {"tier": "framework", "label": "React"},
    },
    "edges": [
        {"from": "cpp", "to": "algorithms", "type": "REQUIRES"},
        {"from": "react", "to": "typescript", "type": "PREREQUISITE_OF"},
    ],
}


def raw(**over) -> dict:
    import copy
    doc = copy.deepcopy(GOOD)
    doc.update(over)
    return doc


def build(doc: dict | None = None) -> SeedOntology:
    """An ontology straight from a dict, skipping the file entirely."""
    doc = doc if doc is not None else raw()
    return SeedOntology(doc.get("skills") or {}, doc.get("ontology_version", "0.0.0"),
                        doc.get("edges") or [], doc.get("tiers") or {})


def written(doc: dict) -> pathlib.Path:
    """The dict as a real YAML file, so `load` is exercised through its own path."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(doc, handle)
    handle.close()
    return pathlib.Path(handle.name)


def problems(**over) -> list[str]:
    return build(raw(**over)).validate()


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")
