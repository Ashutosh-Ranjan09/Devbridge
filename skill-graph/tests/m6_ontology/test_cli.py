"""`python3 -m m6_ontology` — the way the graph gets reviewed by a person.

`check` in particular is meant for CI: a broken seed has to fail a build rather
than be discovered in a score three weeks later.
"""
import contextlib
import io

from ontology_fixtures import SEED_PATH, raw, written

from m6_ontology.__main__ import main


def run(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_check_passes_on_the_shipped_seed():
    code, out, _ = run("check", "--seed", str(SEED_PATH))
    assert code == 0
    assert "35 skills" in out and "no problems" in out


def test_check_fails_and_names_every_problem():
    path = written(raw(edges=[{"from": "cpp", "to": "haskell", "type": "REQUIRES"},
                              {"from": "react", "to": "react", "type": "RELATED_TO"}]))
    code, _, err = run("check", "--seed", str(path))
    assert code == 1
    assert "haskell" in err and "imply itself" in err


def test_a_missing_seed_is_reported_not_raised():
    code, _, err = run("check", "--seed", "/nowhere/ontology.yaml")
    assert code == 1 and "cannot read the seed" in err


def test_skills_can_be_filtered_to_one_tier():
    _, out, _ = run("skills", "--tier", "framework", "--seed", str(SEED_PATH))
    assert "react" in out and "algorithms" not in out


def test_edges_shows_direction_and_type():
    _, out, _ = run("edges", "--seed", str(SEED_PATH))
    line, = [l for l in out.splitlines() if l.strip().startswith("cpp ")
             and "algorithms" in l]
    assert "--REQUIRES" in line and "-> algorithms" in line


def test_show_reports_both_directions_of_propagation():
    """Which way evidence can move is the question someone actually has when
    they look up a skill, and the direction is easy to get backwards."""
    _, out, _ = run("show", "cpp", "--seed", str(SEED_PATH))
    assert "propagates to: algorithms (REQUIRES)" in out
    assert "propagating in from: nothing" in out


def test_show_an_unknown_skill_fails_cleanly():
    code, _, err = run("show", "haskell", "--seed", str(SEED_PATH))
    assert code == 1 and "haskell" in err


def test_dump_is_json_a_client_can_read():
    import json
    _, out, _ = run("dump", "--seed", str(SEED_PATH))
    doc = json.loads(out)
    assert doc["ontology_version"] == "0.2.0"
    assert len(doc["skills"]) == 35 and len(doc["edges"]) == 15


def test_a_broken_seed_still_lists_but_warns():
    """Refusing to show a broken graph would make it harder to fix."""
    path = written(raw(edges=[{"from": "cpp", "to": "haskell", "type": "REQUIRES"}]))
    code, out, err = run("skills", "--seed", str(path))
    assert code == 0 and "cpp" in out
    assert "run `check`" in err


def test_show_without_a_skill_is_a_usage_error_not_a_traceback():
    try:
        run("show", "--seed", str(SEED_PATH))
    except SystemExit as exc:
        assert exc.code == 2, "argparse's usage exit, not a crash"
    else:
        raise AssertionError("expected a usage error")
