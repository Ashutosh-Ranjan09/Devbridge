"""What the extraction is for.

6.1 used to live inside 6.2. Every consumer therefore imported the graph from
the ingestor, which made 6.3 and 6.4 depend on 6.2 for something the ingestor is
not even allowed to traverse. These tests hold the new line, because the old
arrangement worked perfectly well right up until someone had to reason about it.
"""
import pathlib
import re

from ontology_fixtures import ROOT, build, raises

import m6_ingestor
from m6_ontology import AcceptAll, SeedOntology, SkillResolver

PACKAGES = ROOT / "packages"
ONTOLOGY_NAMES = ("SeedOntology", "AcceptAll", "SkillResolver", "default_ontology")


def sources() -> list[pathlib.Path]:
    return [p for p in sorted(PACKAGES.rglob("*.py"))
            if "__pycache__" not in p.parts]


# ── the dependency direction ────────────────────────────────────────────────
def test_no_module_imports_the_ontology_through_the_ingestor():
    """The regression this whole package exists to prevent. Re-exporting from
    m6_ingestor would make every consumer's import work again — and quietly put
    the dependency back the way it was."""
    pattern = re.compile(r"from m6_ingestor import ([^\n]*)")
    offenders = []
    for path in sources() + [p for p in (ROOT / "tests").rglob("*.py")
                             if "__pycache__" not in p.parts]:
        for imported in pattern.findall(path.read_text()):
            if any(name in imported for name in ONTOLOGY_NAMES):
                offenders.append(f"{path.relative_to(ROOT)}: {imported.strip()}")
    assert not offenders, offenders


def test_the_ingestor_does_not_export_the_ontology():
    for name in ONTOLOGY_NAMES:
        assert not hasattr(m6_ingestor, name), name
        assert name not in m6_ingestor.__all__


def test_the_ontology_depends_on_no_other_m6_package():
    """6.1 is the leaf. If it grew an import of 6.2 or 6.3 the graph would have
    a cycle and 'which module owns this' would stop having an answer."""
    for path in sorted((PACKAGES / "m6_ontology").rglob("*.py")):
        text = path.read_text()
        for other in ("m6_ingestor", "m6_scoring", "m6_query", "m6_integrity",
                      "m6_projection", "from m6 import"):
            assert other not in text, f"{path.name} imports {other}"


def test_the_graph_is_defined_in_the_contract_not_in_code():
    """No skill, tier or edge is hard-coded. Someone who does not read Python
    has to be able to review which skills exist and how fast each decays."""
    onto = SeedOntology.load(ROOT / "contracts" / "ontology-seed.yaml")
    assert len(onto) > 0
    assert SeedOntology({}, "empty").skill_ids() == []


# ── the port stays narrow ───────────────────────────────────────────────────
class OnlyTheProtocol:
    """A resolver that answers the two port methods and explodes on anything
    else — including the edges. If the ingestor ever reaches past `knows()`,
    this fails rather than silently letting 6.2 start doing modelling."""

    ontology_version = "port-only"

    def __init__(self, known=("python", "typescript", "cpp")):
        self._known = set(known)

    def knows(self, skill_id: str) -> bool:
        return skill_id in self._known

    def __getattr__(self, name: str):
        raise AssertionError(
            f"the ingestor reached for {name!r}; the port is knows() and "
            "ontology_version, and widening it is how propagation ends up "
            "happening at write time")


def test_the_port_trap_actually_fires():
    """A guard that never fires is not a guard."""
    raises(AssertionError, getattr, OnlyTheProtocol(), "edges")


def test_the_ingestor_runs_against_the_bare_port():
    import sys
    sys.path.insert(0, str(ROOT / "tests" / "m6_ingestor"))
    from fixtures import consented, ingestor
    from m6_ingestor import EventLog

    receipt = ingestor(log=EventLog(":memory:"),
                       ontology=OnlyTheProtocol()).ingest(consented())
    assert receipt.ontology_version == "port-only"


def test_both_implementations_satisfy_the_protocol():
    assert isinstance(build(), SkillResolver)
    assert isinstance(AcceptAll(), SkillResolver)


def test_accept_all_admits_everything_and_says_so_in_the_receipt():
    """Its version is not a version number on purpose: `accept-all` in a receipt
    is a legible admission that nothing was checked, where `0.0.0` would read
    like a real ontology that happened to be empty."""
    resolver = AcceptAll()
    assert resolver.knows("quantum_telepathy")
    assert resolver.ontology_version == "accept-all"


def test_a_substituted_ontology_changes_what_is_quarantined():
    """6.1 was always meant to be a substitution rather than a refactor. This is
    the property that made that true."""
    import sys
    sys.path.insert(0, str(ROOT / "tests" / "m6_ingestor"))
    from fixtures import consented, ingestor
    from m6_ingestor import EventLog

    tiny = SeedOntology({"python": {"tier": "ecosystem"}}, "tiny-1.0")
    held = ingestor(log=EventLog(":memory:"), ontology=tiny).ingest(consented())
    passed = ingestor(log=EventLog(":memory:"), ontology=AcceptAll()).ingest(consented())
    assert held.quarantined and not passed.quarantined


def test_an_empty_ontology_is_honoured_rather_than_replaced():
    """`self.ontology = ontology or default_ontology()` looks harmless and is
    not: an ontology that knows nothing is falsy, so `or` swaps the caller's
    resolver for the seed and quarantines against a graph they never chose.
    Found the moment AcceptAll grew a __len__.
    """
    import sys
    sys.path.insert(0, str(ROOT / "tests" / "m6_ingestor"))
    from fixtures import consented
    from m6_ingestor import EventLog, Ingestor

    empty = SeedOntology({}, "empty-1.0")
    assert not empty, "the premise: an empty ontology is falsy"
    receipt = Ingestor(EventLog(":memory:"), ontology=empty).ingest(consented())
    assert receipt.ontology_version == "empty-1.0"
    assert receipt.quarantined, "nothing resolves against an empty graph"


def test_the_composed_module_honours_it_too():
    import sys
    sys.path.insert(0, str(ROOT / "packages"))
    from m6 import M6

    with M6(":memory:", ontology=SeedOntology({}, "empty-1.0")) as m6:
        assert m6.versions()["ontology"] == "empty-1.0"
