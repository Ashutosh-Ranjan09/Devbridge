"""Roll-number decoding: only where the CV names the institution whose format it is."""

from __future__ import annotations

from cvv.extract import _decode_roll
from cvv.reference import named_scheme


def test_the_named_institution_decodes_its_own_format() -> None:
    parsed = _decode_roll("23CS10004", "B.TECH IIT Kharagpur 2027")
    assert parsed == {"admission_year": 2023, "dept_code": "CS", "serial": 10004}


def test_the_same_shape_under_no_named_institution_is_not_decoded() -> None:
    """A register number from a college with no scheme on record has the same shape.
    Decoding it would read Kharagpur's departments into somebody else's number."""
    assert _decode_roll("23CS10004", "B.Tech, Some Other College, 2027") is None


def test_an_institution_name_matches_as_a_whole_word() -> None:
    """VIT's scheme lists "vit". It must not be found inside "activities"."""
    assert named_scheme("19BCE1234", "EXTRA CURRICULAR ACTIVITIES") is None
    assert named_scheme("19BCE1234", "B.Tech, VIT Vellore, 2023") is not None
