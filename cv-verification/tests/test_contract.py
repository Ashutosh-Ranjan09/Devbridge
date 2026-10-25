"""Our models against the authoritative schemas.

CLAUDE.md says to build `models/` from the schemas and "prove it by round-tripping
the three reference payloads". That test existed once, was lost in the clean-slate
rebuild, and was never restored — so roughly twenty model changes went unchecked and
the output stopped validating without anybody noticing.

The integration spec predicted precisely this: *"the failure mode is silent — one
person adds a field locally, the other never sees it, and integration breaks in week
7 for reasons nobody can reconstruct."*

So `KNOWN_EXTENSIONS` below is not a suppression list. It is the reviewed, named set
of fields this system adds beyond the contract, each with the check that needs it.
Anything NOT on it fails. Adding to it is a deliberate act with a comment attached,
which is the opposite of what happened here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from cvv import models as M  # noqa: N812 - a table of model classes reads better short

SCHEMAS = Path("../schemas")
EXAMPLES = Path("../schemas/examples")
REPORT_SCHEMA = SCHEMAS / "verification-report.schema.json"

pytestmark = pytest.mark.skipif(
    not REPORT_SCHEMA.is_file(), reason="the contract schemas are not present"
)

# Fields we add that the contract does not define. Every one is load-bearing for a
# check, and every one is REJECTED by a consumer validating against the schema,
# because 25 of its 27 definitions set additionalProperties: false. Resolving that
# needs a contract version bump, which the spec says takes both owners — so this list
# records the debt rather than hiding it.
KNOWN_EXTENSIONS = {
    "ExtractionMeta.filtered",          # D2 2.0 — filtered is not ungroundable
    "RepoEvidence.authored_files",      # G7 2.0 — a lock file is not substance
    "RepoEvidence.authored_bytes",      # G7 2.0
    "RepoEvidence.homepage",            # W1 2.0 — ties a deployment to its repo
    "GitHubEvidence.public_repos",      # skills the CV never mentions
    "GitHubEvidence.public_repo_count",
    "RuleOutcome.note",                 # what a Corroborated rule CONFIRMED
    "Narrative.rejected_because",       # why the model's prose was not used
    "VerificationReport.failure",       # why a verification failed; no contract field
    "VerificationReport.skill_resolution",  # which shared skill each name means, for M6
}


def defs(schema: Path) -> dict[str, Any]:
    return json.loads(schema.read_text())["$defs"]


REPORT_DEFS = defs(REPORT_SCHEMA) if REPORT_SCHEMA.is_file() else {}

PAIRED = [
    ("Claim", M.Claim, "report"), ("Resolution", M.Resolution, "report"),
    ("SpanProvenance", M.SpanProvenance, "report"), ("Interval", M.Interval, "report"),
    ("FuzzyDate", M.FuzzyDate, "report"), ("ExtractionMeta", M.ExtractionMeta, "report"),
    ("EvidenceBundle", M.EvidenceBundle, "report"), ("RepoEvidence", M.RepoEvidence, "report"),
    ("GitHubEvidence", M.GitHubEvidence, "report"),
    ("PlatformEvidence", M.PlatformEvidence, "report"),
    ("CredentialEvidence", M.CredentialEvidence, "report"),
    ("Discrepancy", M.Discrepancy, "report"), ("RuleOutcome", M.RuleOutcome, "report"),
    ("SectionConfidence", M.SectionConfidence, "report"),
    ("Narrative", M.Narrative, "report"), ("ReportProvenance", M.ReportProvenance, "report"),
    ("VerificationCoverage", M.VerificationCoverage, "report"),
    ("VerificationReport", M.VerificationReport, "report"),
]


def schema_for(name: str, which: str) -> dict[str, Any] | None:
    if name == "VerificationReport":  # the root of the schema, not one of its $defs
        return json.loads(REPORT_SCHEMA.read_text())
    return REPORT_DEFS.get(name)


class TestNoFieldIsSilentlyMissing:
    """A field the contract defines and we lack means we cannot PARSE what a
    partner sends. That is not a stylistic difference — it is an integration
    failure, and it is how `Claim.resolution` and `EvidenceEvent.observed_at` went
    unnoticed."""

    @pytest.mark.parametrize(("name", "model", "which"), PAIRED, ids=[p[0] for p in PAIRED])
    def test_every_contract_field_exists_on_our_model(
        self, name: str, model: type, which: str
    ) -> None:
        schema = schema_for(name, which)
        if schema is None:
            pytest.skip(f"{name} is not in the schema")
        missing = sorted(set(schema.get("properties", {})) - set(model.model_fields))
        assert not missing, f"{name} lacks {missing} — a payload carrying them cannot parse"


class TestNoFieldIsSilentlyAdded:
    @pytest.mark.parametrize(("name", "model", "which"), PAIRED, ids=[p[0] for p in PAIRED])
    def test_extensions_are_declared(self, name: str, model: type, which: str) -> None:
        """25 of 27 definitions set additionalProperties: false, so an undeclared
        field is not a harmless addition — it makes our output invalid."""
        schema = schema_for(name, which)
        if schema is None:
            pytest.skip(f"{name} is not in the schema")
        added = {
            f"{name}.{f}" for f in set(model.model_fields) - set(schema.get("properties", {}))
        }
        assert not (added - KNOWN_EXTENSIONS), (
            f"undeclared extension(s) {sorted(added - KNOWN_EXTENSIONS)}. Either the "
            "contract gains the field with a version bump, or the value belongs in an "
            "open field like `context`. Adding it to KNOWN_EXTENSIONS is a decision, "
            "not a fix."
        )

    def test_the_debt_list_stays_honest(self) -> None:
        """An entry that is no longer an extension has been resolved and must leave
        the list, or the list stops meaning anything."""
        live = {
            f"{name}.{f}"
            for name, model, which in PAIRED
            if (s := schema_for(name, which))
            for f in set(model.model_fields) - set(s.get("properties", {}))
        }
        assert not (KNOWN_EXTENSIONS - live), (
            f"{sorted(KNOWN_EXTENSIONS - live)} is no longer an extension — remove it"
        )


class TestTheReferencePayloadsParse:
    """The phase 0 guarantee, restored. If the three committed payloads survive a
    parse, the models agree with the contract on the shapes a partner actually
    sends."""

    @pytest.mark.parametrize("name", ["report-full.json", "report-degraded.json"])
    @pytest.mark.skipif(not EXAMPLES.is_dir(), reason="reference payloads are not present")
    def test_a_reference_report_parses(self, name: str) -> None:
        raw = json.loads((EXAMPLES / name).read_text())
        # The fixtures truncate `normalised_text`, so spans do not index it. The
        # waiver exists for exactly this and no production path passes it.
        graph = M.ClaimGraph.model_validate(
            raw["claim_graph"], context={"source_text_truncated": True}
        )
        assert graph.claims
        M.EvidenceBundle.model_validate(raw["evidence_bundle"])
        M.FindingsReport.model_validate(raw["findings"])

    @pytest.mark.parametrize("name", ["report-full.json", "report-degraded.json"])
    @pytest.mark.skipif(not EXAMPLES.is_dir(), reason="reference payloads are not present")
    def test_a_whole_reference_report_parses(self, name: str) -> None:
        """The stages parsing is not the report parsing. Until the report itself was
        built from the contract, ours lacked the evidence bundle, the subject and the
        provenance — and nothing failed, because nothing parsed the whole thing."""
        raw = json.loads((EXAMPLES / name).read_text())
        report = M.VerificationReport.model_validate(raw, context={"source_text_truncated": True})
        assert report.evidence_bundle.bundle_id

    @pytest.mark.skipif(not EXAMPLES.is_dir(), reason="reference payloads are not present")
    def test_a_resolution_survives_the_round_trip(self) -> None:
        """Nothing here resolves anything, so this field is the one most likely to be
        dropped on the floor without a test noticing."""
        raw = json.loads((EXAMPLES / "report-full.json").read_text())
        graph = M.ClaimGraph.model_validate(
            raw["claim_graph"], context={"source_text_truncated": True}
        )
        resolved = [c for c in graph.claims if c.resolution]
        assert resolved, "the reference payload carries resolutions to round-trip"
        again = M.ClaimGraph.model_validate(
            json.loads(graph.model_dump_json()), context={"source_text_truncated": True}
        )
        assert again == graph


class TestWhatWeEmit:
    """Our own output, against the schema a consumer would use — M6 among them."""

    def test_a_report_is_valid_except_for_the_named_extensions(self) -> None:
        """Built by the function the CLI and the API both call, over a graph with
        claims and a bundle with real evidence, so the deep shapes are exercised.

        Not `jsonschema.validate`: our output IS invalid, by exactly the fields in
        KNOWN_EXTENSIONS, and that is the debt this file records. So every error must
        be an unexpected field on that list, and anything else is a real break."""
        from cvv.models import ClaimKind, DocumentInfo, IngestMethod
        from cvv.pipeline import verification_report
        from cvv.report import assemble
        from tests.cvdata import CF_RATING, DOCUMENT, SKILLS_LINE, make_claim, make_graph
        from tests.test_rules import bundle, codeforces, github, repo

        graph = make_graph(
            [
                make_claim(SKILLS_LINE, DOCUMENT, claim_id="cskl01", kind=ClaimKind.SKILL,
                           skill_refs=["python"]),
                make_claim(CF_RATING, DOCUMENT, claim_id="cach01", kind=ClaimKind.ACHIEVEMENT,
                           platform="codeforces", metric="max_rating", value=1495),
            ],
            DOCUMENT,
        )
        evidence = bundle(graph, github=github(repos=(repo("x", languages=("Python",)),)),
                          platforms=[codeforces()])
        document = DocumentInfo(
            document_id="doc_t", sha256="0" * 64, pages=1, ingest_method=IngestMethod.PDF_TEXT
        )
        report = verification_report(
            verification_id="vr_t", document=document, graph=graph, bundle=evidence,
            findings=assemble(graph, evidence, report_id="fr_t", document=document),
        )
        payload = json.loads(report.model_dump_json())
        allowed = {name.split(".")[1] for name in KNOWN_EXTENSIONS}
        errors = list(
            jsonschema.Draft202012Validator(json.loads(REPORT_SCHEMA.read_text()))
            .iter_errors(payload)
        )

        def owed(e: jsonschema.ValidationError) -> bool:
            """An unexpected field on the debt list — directly, or as the only thing
            wrong with one branch of a `oneOf` (`github` is GitHubEvidence or null,
            so its extensions surface as "valid under none of the schemas")."""
            if e.validator == "additionalProperties":
                return set(re.findall(r"'([^']+)'", e.message)) <= allowed
            if e.validator in ("oneOf", "anyOf"):
                branches: dict[object, list[jsonschema.ValidationError]] = {}
                for sub in e.context or []:
                    branches.setdefault(sub.relative_schema_path[0], []).append(sub)
                return any(all(owed(sub) for sub in subs) for subs in branches.values())
            return False

        unexpected = [
            f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
            for e in errors
            if not owed(e)
        ]
        assert not unexpected, unexpected
        assert payload["evidence_bundle"]["github"], "the bundle travels with the report"

    def test_document_dates_are_iso_date_times(self) -> None:
        """jsonschema checks `format: date-time` only with an optional package this
        project does not install, so the test above passes a PDF's `D:2025…` string.
        M6 does not: it refused the first real report it was given."""
        import datetime

        from cvv.ingest import document_info, read

        cv = Path("docs/CV-SDE-AR.pdf")
        if not cv.is_file():
            pytest.skip("the reference CV is not present")
        info = document_info(read(cv))
        for value in (info.created_at, info.modified_at):
            assert value is not None
            assert datetime.datetime.fromisoformat(value).tzinfo is not None
