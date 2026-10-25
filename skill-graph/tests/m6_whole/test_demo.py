"""The demo is a deliverable, so it is tested like one.

A walkthrough that silently stops working is worse than no walkthrough — someone
runs it in front of a supervisor. These check that the input is valid, that the
script runs, and that it demonstrates what its README says it demonstrates.
"""
import json
import pathlib
import subprocess
import sys

from whole_fixtures import DEMO_AS_OF, DEMO_SUBJECT, ROOT, demo_report, loaded

DEMO = ROOT / "demo"
SCRIPT = DEMO / "run_demo.py"


def test_the_input_validates_against_the_committed_m5_schema():
    """It is an M5 output, so M5's contract is what makes it a fair example."""
    import jsonschema
    schema = json.loads(
        (ROOT / "docs" / "docs" / "schemas" / "verification-report.schema.json").read_text())
    jsonschema.validate(instance=demo_report(), schema=schema)


def test_the_input_is_richer_than_the_golden_example():
    """The point of a second fixture is to reach machinery the first does not."""
    from whole_fixtures import report
    demo, golden = demo_report(), report()
    assert len(demo["claim_graph"]["claims"]) > len(golden["claim_graph"]["claims"])
    assert (len(demo["evidence_bundle"]["github"]["repos"])
            > len(golden["evidence_bundle"]["github"]["repos"]))


def test_the_input_exercises_every_claim_kind_the_schema_allows():
    kinds = {c["kind"] for c in demo_report()["claim_graph"]["claims"]}
    schema = json.loads(
        (ROOT / "docs" / "docs" / "schemas" / "verification-report.schema.json").read_text())
    allowed = set(schema["$defs"]["Claim"]["properties"]["kind"]["enum"])
    assert kinds == allowed, f"missing: {sorted(allowed - kinds)}"


def test_the_input_reaches_the_machinery_the_readme_claims():
    with loaded(demo_report()) as m6:
        batch = m6.project(demo_report())
        kinds = {e["kind"] for e in batch["events"]}
        assert {"repo_artifact", "platform_rating", "cv_claim", "claim_corroborated",
                "artifact_live", "credential_verified"} <= kinds

        factors = {f["factor"] for e in batch["events"]
                   for f in e.get("reliability_factors") or []}
        assert "scraped_source" in factors, "the CodeChef scrape discount"
        assert "aggregate_across_sources" in factors, "the 900+ problems claim"
        assert "open_bound" in factors

        reasons = {s["reason"] for s in batch["not_emitted"]}
        assert {"not_a_capability_signal", "no_skill_mapping",
                "institution_disclaimed"} <= reasons

    # A fresh log: the M6 above already holds this report, so re-ingesting it
    # there would be a replay and the receipt would be empty by design.
    with loaded() as fresh:
        receipt = fresh.ingest_report(demo_report())
        held = {s for skills in receipt.quarantined.values() for s in skills}
        assert "haskell" in held, "an unknown skill must be quarantined"


def test_cv_claims_are_dated_at_the_document_not_the_verification():
    """The README calls this out; it must stay true."""
    with loaded() as m6:
        batch = m6.project(demo_report())
    dates = {e["occurred_at"][:10] for e in batch["events"] if e["kind"] == "cv_claim"}
    assert dates == {"2026-07-12"}, dates


def test_the_walkthrough_runs_end_to_end():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--http"],
        capture_output=True, text=True, timeout=180,
        env={"PYTHONPATH": str(ROOT / "packages"), "PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr[-2000:]
    for marker in ("STEP 1", "STEP 9", "6.0  EVENT PROJECTION", "6.5  INTEGRITY",
                   "THE GUARANTEES", "Done."):
        assert marker in result.stdout, marker
    assert "ERROR:" not in result.stdout


def test_a_single_step_can_be_run_alone():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--step", "7"],
        capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": str(ROOT / "packages"), "PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr[-2000:]
    assert "STEP 7" in result.stdout and "STEP 1" not in result.stdout


def test_the_walkthrough_writes_every_output_file():
    subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, timeout=180,
                   env={"PYTHONPATH": str(ROOT / "packages"), "PATH": "/usr/bin:/bin"})
    for name in ("01-projected-batch.json", "02-ingest-receipt.json",
                 "03-skill-graph.json", "04-explain.json", "05-integrity.json"):
        path = DEMO / "output" / name
        assert path.exists(), name
        json.loads(path.read_text())          # must be readable JSON


def test_the_written_batch_still_conforms_to_the_event_schema():
    import jsonschema
    schema = json.loads(
        (ROOT / "docs" / "docs" / "schemas" / "evidence-event.schema.json").read_text())
    batch = json.loads((DEMO / "output" / "01-projected-batch.json").read_text())
    jsonschema.validate(instance=batch, schema=schema)


def test_the_walkthrough_accepts_a_different_report():
    """--input is not decorative: the script must work on any M5 output."""
    golden = ROOT / "docs" / "docs" / "examples" / "report-full.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(golden), "--skill", "typescript"],
        capture_output=True, text=True, timeout=180,
        env={"PYTHONPATH": str(ROOT / "packages"), "PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr[-2000:]
    assert "subj_7a3f9e21" in result.stdout


def test_the_readmes_numbers_match_what_the_demo_produces():
    """The README quotes 21 events and 7 suppressions. A README that drifts from
    the thing it describes is worse than none."""
    readme = (DEMO / "README.md").read_text()
    with loaded() as m6:
        batch = m6.project(demo_report())
    assert f"{len(batch['events'])} events" in readme
    assert f"{len(batch['not_emitted'])} recorded suppressions" in readme
