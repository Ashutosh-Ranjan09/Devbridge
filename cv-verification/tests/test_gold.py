"""The gold-set scorer: matching, the field comparisons, and refusing a bad gold file.

No model here: the graphs are built by hand, so what is tested is the scoring, not an
extractor. `cvv gold` runs the extractor itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cvv.gold import GOLD_DIR, GoldError, load, same, score
from cvv.ingest import read
from cvv.models import ClaimKind
from tests.cvdata import CF_RANK, CF_RATING, DOCUMENT, make_claim, make_graph

ROOT = Path(__file__).resolve().parents[1]


def gold_file(tmp_path: Path, *claims: dict) -> Path:
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"document": "x.pdf", "claims": list(claims)}))
    return path


def rating(**fields: object):
    return make_claim(CF_RATING, DOCUMENT, claim_id="cach01", kind=ClaimKind.ACHIEVEMENT,
                      platform="codeforces", metric="max_rating", value=1495, **fields)


def test_a_matching_extraction_is_a_true_positive_with_its_fields_right(tmp_path: Path) -> None:
    gold = load(gold_file(tmp_path, {"kind": "achievement", "anchor": "1495",
                                     "fields": {"platform": "codeforces", "value": 1495}}), DOCUMENT)
    s = score(make_graph([rating()], DOCUMENT), gold)
    assert (s.total().tp, s.total().fp, s.total().fn) == (1, 0, 0)
    assert s.fields == {"platform": (1, 1), "value": (1, 1)}


def test_a_missed_claim_and_an_extra_one_are_counted_apart(tmp_path: Path) -> None:
    gold = load(gold_file(tmp_path, {"kind": "achievement", "anchor": "1106"}), DOCUMENT)
    s = score(make_graph([rating()], DOCUMENT), gold)  # the 1495 claim is not the 1106 one
    k = s.kinds["achievement"]
    assert (k.tp, k.fp, k.fn) == (0, 1, 1)
    assert k.precision == 0.0 and k.recall == 0.0 and k.f1 == 0.0
    assert s.missed == ["achievement: 1106"]


def test_matching_is_one_to_one(tmp_path: Path) -> None:
    """Two labelled claims cannot both be satisfied by one extracted claim."""
    gold = load(gold_file(tmp_path, {"kind": "achievement", "anchor": "peak Codeforces"},
                          {"kind": "achievement", "anchor": "1495"}), DOCUMENT)
    s = score(make_graph([rating()], DOCUMENT), gold)
    assert (s.total().tp, s.total().fn) == (1, 1)


def test_the_kind_must_match_as_well_as_the_span(tmp_path: Path) -> None:
    gold = load(gold_file(tmp_path, {"kind": "profile", "anchor": "1495"}), DOCUMENT)
    assert score(make_graph([rating()], DOCUMENT), gold).total().tp == 0


def test_tokens_are_exact_and_prose_may_be_normalised() -> None:
    assert not same("handle", "ar009", "AR009"), "another casing is another account"
    assert same("org", "Vellore Institute of Technology, Vellore", "vellore institute of technology")
    assert same("skill_refs", ["Go", "React"], ["react", "go"])
    assert same("value", 1495.0, 1495) and not same("value", 1494, 1495)
    assert same("platform", None, None) and not same("platform", None, "codeforces")


def test_an_anchor_not_in_the_document_or_in_it_twice_is_refused(tmp_path: Path) -> None:
    with pytest.raises(GoldError, match="not in the document"):
        load(gold_file(tmp_path, {"kind": "achievement", "anchor": "rating of 9999"}), DOCUMENT)
    doubled = DOCUMENT + " " + CF_RANK
    with pytest.raises(GoldError, match="more than once"):
        load(gold_file(tmp_path, {"kind": "achievement", "anchor": CF_RANK}), doubled)


def test_a_field_the_scorer_does_not_compare_is_refused(tmp_path: Path) -> None:
    with pytest.raises(GoldError, match="no field"):
        load(gold_file(tmp_path, {"kind": "achievement", "anchor": "1495", "fields": {"colour": "red"}}), DOCUMENT)


def test_every_committed_gold_file_resolves_against_its_document() -> None:
    """A gold file that drifted from its PDF would score nothing and say nothing."""
    files = sorted(GOLD_DIR.glob("*.json"))
    assert files
    for f in files:
        document = read(ROOT / json.loads(f.read_text())["document"])
        assert load(f, document.text)
