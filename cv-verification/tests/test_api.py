"""The HTTP surface. No model, no network — the pipeline itself is stubbed.

What is under test is the transport: what it accepts, what it refuses, what it says
when it cannot do something, and the two contract restrictions the spec exists to
enforce. Running a real verification through it is a live test.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from cvv import api, pipeline, store
from cvv.models import (
    ClaimGraph,
    ReportStatus,
    VerificationReport,
)
from tests.cvdata import contract_report

NOW = datetime.datetime(2026, 9, 4, tzinfo=datetime.UTC)
CV = Path("docs/CV-SDE-AR.pdf")


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch: pytest.MonkeyPatch) -> store.MemoryStore:
    """A store per test. Without it, `usage` counts every earlier test's runs and the
    assertions become order-dependent — the same failure the cache isolation fixed."""
    fresh = store.MemoryStore()
    monkeypatch.setattr(store, "STORE", fresh)
    monkeypatch.setattr(api, "STORE", fresh)
    return fresh


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {api.API_KEY}"}


def empty_report(verification_id: str, status: ReportStatus) -> VerificationReport:
    return contract_report(verification_id, status)


class TestHealthNamesTheBackendThatRuns:
    """/healthz said qwen3:1.7b and /readyz probed Ollama while every verification
    ran on Claude. Both now ask the configured backend."""

    def test_health_names_the_configured_model(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api.settings, "llm_backend", "claude-code")
        monkeypatch.setattr(api.settings, "claude_code_model", "sonnet")
        body = client.get("/healthz").json()
        assert body["backend"] == "claude-code"
        assert body["model"] == "claude-code:sonnet"

    @respx.mock
    def test_a_claude_service_is_ready_when_the_wrapper_answers(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wrapper has no health route; a 404 from it still means it is up. And
        Ollama being down is irrelevant to a Claude-backed service."""
        monkeypatch.setattr(api.settings, "llm_backend", "claude-code")
        monkeypatch.setattr(api.settings, "claude_code_url", "http://wrapper.test")
        respx.get("http://wrapper.test").mock(return_value=httpx.Response(404))
        ollama = respx.get(url__startswith=api.settings.ollama_url).mock(
            side_effect=httpx.ConnectError("off")
        )
        assert client.get("/readyz").status_code == 200
        assert not ollama.called

    @respx.mock
    def test_a_claude_service_is_not_ready_when_the_wrapper_is_down(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api.settings, "llm_backend", "claude-code")
        monkeypatch.setattr(api.settings, "claude_code_url", "http://wrapper.test")
        respx.get("http://wrapper.test").mock(side_effect=httpx.ConnectError("refused"))
        r = client.get("/readyz")
        assert r.status_code == 503
        assert "Claude Code wrapper" in r.json()["detail"]

    @respx.mock
    def test_an_ollama_service_still_checks_ollama(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api.settings, "llm_backend", "ollama")
        respx.get(f"{api.settings.ollama_url}/api/tags").mock(return_value=httpx.Response(500))
        assert client.get("/readyz").status_code == 503


class TestWhatIsOpenAndWhatIsNot:
    def test_health_needs_no_key(self, client: TestClient) -> None:
        """A health check a load balancer cannot call is not a health check. It
        carries no data about any verification."""
        body = client.get("/healthz").json()
        assert body["status"] == "ok"
        assert body["store"] == "memory"
        assert "verification" not in str(body).lower()

    def test_the_rule_catalogue_needs_no_key(self, client: TestClient) -> None:
        """It describes the SYSTEM and names no candidate, and a caller's fixtures
        must be able to see a new rule the day it lands."""
        rules = client.get("/v1/rules").json()
        assert len(rules) >= 27
        assert {"rule_id", "version", "tier", "scoring", "summary"} <= set(rules[0])

    @pytest.mark.parametrize(
        "path", ["/v1/usage", "/v1/verifications/vr_x", "/v1/verifications"]
    )
    def test_everything_touching_a_verification_needs_a_key(
        self, client: TestClient, path: str
    ) -> None:
        method = client.post if path == "/v1/verifications" else client.get
        assert method(path).status_code == 401

    def test_a_wrong_key_is_refused(self, client: TestClient) -> None:
        r = client.get("/v1/usage", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401
        assert r.headers.get("WWW-Authenticate") == "Bearer"


class TestAcceptingADocument:
    def test_a_file_is_accepted_and_queued(
        self, client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api, "run_verification", lambda *a, **k: None)
        r = client.post(
            "/v1/verifications", headers=auth, files={"document": ("cv.pdf", b"%PDF-", "application/pdf")}
        )
        assert r.status_code == 202
        assert r.json()["status"] == "queued"
        assert r.json()["verification_id"].startswith("vr_")

    def test_no_document_is_a_422_that_says_what_to_send(
        self, client: TestClient, auth: dict[str, str]
    ) -> None:
        r = client.post("/v1/verifications", headers=auth, json={})
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "no_document"

    def test_an_unsupported_format_is_refused_before_any_work(
        self, client: TestClient, auth: dict[str, str]
    ) -> None:
        """.doc is a different binary format, and a scan needs OCR. Guessing produces
        a document that grounds cleanly and is missing most of its content."""
        r = client.post(
            "/v1/verifications", headers=auth, files={"document": ("cv.doc", b"\xd0\xcf", "application/msword")}
        )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "unreadable_document"

    def test_a_retry_with_the_same_idempotency_key_starts_nothing(
        self, client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A client retrying a timed-out upload would otherwise reload the model and
        spend someone's rate limit again for a document already being processed."""
        started: list[str] = []
        monkeypatch.setattr(api, "run_verification", lambda vid, *a, **k: started.append(vid))
        headers = {**auth, "Idempotency-Key": "abc-123"}
        files: dict[str, Any] = {"document": ("cv.pdf", b"%PDF-", "application/pdf")}

        first = client.post("/v1/verifications", headers=headers, files=files)
        second = client.post("/v1/verifications", headers=headers, files=files)

        assert first.status_code == 202 and second.status_code == 200
        assert second.json()["verification_id"] == first.json()["verification_id"]
        assert second.json()["status"] == "known"
        assert len(started) == 1, "the pipeline must run once"


class TestTheRequestBody:
    """The spec's body is "multipart or JSON". The first version declared a file and a
    JSON model in one signature, which FastAPI cannot honour: a JSON body was a 422
    `no_document` and a multipart upload's options were dropped without a word."""

    @pytest.fixture
    def started(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        monkeypatch.setattr(api, "run_verification", lambda vid, path, **k: calls.append(k))
        return calls

    def test_a_json_body_with_a_document_url_and_options(
        self, client: TestClient, auth: dict[str, str], started: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fetched: list[str] = []

        def fake_get(url: str, **_: object) -> httpx.Response:
            fetched.append(url)
            return httpx.Response(200, content=b"%PDF-", request=httpx.Request("GET", url))

        monkeypatch.setattr(api.httpx, "get", fake_get)
        r = client.post(
            "/v1/verifications",
            headers=auth,
            json={"document_url": "https://example.com/cv.pdf", "options": {"offline": True}},
        )
        assert r.status_code == 202
        assert fetched == ["https://example.com/cv.pdf"]
        assert started == [{"offline": True, "want_narrative": True, "subject": None, "handles": None}]

    def test_multipart_options_reach_the_pipeline(
        self, client: TestClient, auth: dict[str, str], started: list[dict[str, Any]]
    ) -> None:
        r = client.post(
            "/v1/verifications",
            headers=auth,
            files={"document": ("cv.pdf", b"%PDF-", "application/pdf")},
            data={"options": '{"offline": true, "narrative": false}'},
        )
        assert r.status_code == 202
        assert started == [{"offline": True, "want_narrative": False, "subject": None, "handles": None}]

    def test_multipart_subject_reaches_the_pipeline(
        self, client: TestClient, auth: dict[str, str], started: list[dict[str, Any]]
    ) -> None:
        """An upload names its subject too. Without it the report was filed under the
        file's hash, and the caller's candidate never saw their own evidence in M6."""
        r = client.post(
            "/v1/verifications",
            headers=auth,
            files={"document": ("cv.pdf", b"%PDF-", "application/pdf")},
            data={"subject": '{"subject_ref": "subject:3f9a"}'},
        )
        assert r.status_code == 202
        assert started[0]["subject"].subject_ref == "subject:3f9a"

    def test_multipart_handles_reach_the_pipeline(
        self, client: TestClient, auth: dict[str, str], started: list[dict[str, Any]]
    ) -> None:
        """Handles the candidate typed on upload; every one is optional."""
        r = client.post(
            "/v1/verifications",
            headers=auth,
            files={"document": ("cv.pdf", b"%PDF-", "application/pdf")},
            data={"handles": '{"leetcode": "asha_r"}'},
        )
        assert r.status_code == 202
        assert started[0]["handles"].model_dump() == {
            "github": None, "codeforces": None, "leetcode": "asha_r", "codechef": None
        }

    def test_a_malformed_handle_is_a_422(
        self, client: TestClient, auth: dict[str, str], started: list[dict[str, Any]]
    ) -> None:
        r = client.post(
            "/v1/verifications",
            headers=auth,
            files={"document": ("cv.pdf", b"%PDF-", "application/pdf")},
            data={"handles": '{"github": "a b"}'},
        )
        assert r.status_code == 422 and started == []

    def test_malformed_options_are_a_422_that_says_so(
        self, client: TestClient, auth: dict[str, str], started: list[dict[str, Any]]
    ) -> None:
        r = client.post(
            "/v1/verifications",
            headers=auth,
            files={"document": ("cv.pdf", b"%PDF-", "application/pdf")},
            data={"options": "{offline: yes"},
        )
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "invalid_request"
        assert started == []


class TestReadingOneBack:
    def test_pending_is_202_not_404(
        self, client: TestClient, auth: dict[str, str], fresh_store: store.MemoryStore
    ) -> None:
        """404 would tell a polling client the verification does not exist."""
        fresh_store.accept("vr_running")
        r = client.get("/v1/verifications/vr_running", headers=auth)
        assert r.status_code == 202
        assert r.json()["status"] == "running"

    def test_unknown_is_404(self, client: TestClient, auth: dict[str, str]) -> None:
        assert client.get("/v1/verifications/vr_nope", headers=auth).status_code == 404

    def test_a_failure_is_still_a_report(
        self, client: TestClient, auth: dict[str, str], fresh_store: store.MemoryStore
    ) -> None:
        """A verification that vanishes is worse than one reporting its own failure:
        the client polls forever and has nothing to tell the person whose CV it was.
        `claim_graph` and `findings` are empty rather than absent, so a client parsing
        VerificationReport never needs two shapes."""
        fresh_store.complete(api._failed("vr_bad", "ValueError: unreadable"))
        body = client.get("/v1/verifications/vr_bad", headers=auth).json()
        assert body["status"] == "failed"
        assert body["failure"] == "ValueError: unreadable"
        assert body["claim_graph"]["claims"] == []
        assert body["findings"]["discrepancies"] == []


class TestProvenance:
    def report_with_a_claim(self, fresh_store: store.MemoryStore) -> str:
        from cvv.models import ClaimKind
        from tests.cvdata import DOCUMENT, ROLL, make_claim, make_graph

        claim = make_claim(ROLL, DOCUMENT, claim_id="cid001", kind=ClaimKind.IDENTIFIER)
        report = empty_report("vr_prov", ReportStatus.COMPLETED)
        graph = make_graph([claim], DOCUMENT)
        fresh_store.complete(report.model_copy(update={"claim_graph": graph}))
        return claim.claim_id

    def test_the_snippet_comes_from_the_text_that_was_checked(
        self, client: TestClient, auth: dict[str, str], fresh_store: store.MemoryStore
    ) -> None:
        """Cut from the graph's own normalised text — the exact string every offset
        in the system indexes into — so what is shown is what was checked."""
        claim_id = self.report_with_a_claim(fresh_store)
        body = client.get(
            f"/v1/verifications/vr_prov/claims/{claim_id}/provenance", headers=auth
        ).json()
        assert body["verbatim"] == "23CS10004"
        assert "23CS10004" in body["snippet"]
        assert len(body["snippet"]) > len(body["verbatim"])

    def test_bbox_is_null_rather_than_guessed(
        self, client: TestClient, auth: dict[str, str], fresh_store: store.MemoryStore
    ) -> None:
        """A guessed rectangle sends a reviewer to the wrong line, which is worse
        than showing none."""
        claim_id = self.report_with_a_claim(fresh_store)
        body = client.get(
            f"/v1/verifications/vr_prov/claims/{claim_id}/provenance", headers=auth
        ).json()
        assert body["bbox"] is None

    def test_an_unknown_claim_names_itself_in_the_404(
        self, client: TestClient, auth: dict[str, str], fresh_store: store.MemoryStore
    ) -> None:
        self.report_with_a_claim(fresh_store)
        r = client.get("/v1/verifications/vr_prov/claims/c999/provenance", headers=auth)
        assert r.status_code == 404 and "c999" in r.json()["detail"]


class TestTheContractRestrictions:
    """The two boundaries the three-service split existed to enforce. They hold here
    whether the call crosses a network or a stack frame."""

    def test_narrate_accepts_only_a_findings_report(
        self, client: TestClient, auth: dict[str, str]
    ) -> None:
        """Not the document, not the claim graph. An endpoint that cannot receive the
        source text cannot leak it into prose, whatever the model is asked to do."""
        r = client.post(
            "/v1/narrate",
            headers=auth,
            json={"document": "the raw CV text", "normalised_text": "..."},
        )
        assert r.status_code == 422

    def test_evaluate_accepts_only_a_claim_graph(
        self, client: TestClient, auth: dict[str, str]
    ) -> None:
        r = client.post("/v1/evaluate", headers=auth, json={"evidence": {"github": {}}})
        assert r.status_code == 422

    def test_evaluate_runs_the_document_only_path(
        self, client: TestClient, auth: dict[str, str]
    ) -> None:
        """`rules/` imports no HTTP client, so this endpoint cannot gather anything
        and every check needing a source abstains WITH ITS REASON."""
        graph = empty_report("vr_x", ReportStatus.COMPLETED).claim_graph
        body = client.post("/v1/evaluate", headers=auth, json=graph.model_dump(mode="json")).json()
        assert len(body["rule_outcomes"]) >= 27
        abstained = [o for o in body["rule_outcomes"] if o["status"] == "abstained"]
        assert abstained and all(o["reason"] for o in abstained)


class TestWhatIsHonestlyNotBuilt:
    """501 with the reason, never an empty success. An empty result would let a
    caller believe the thing ran and found nothing."""

    def test_resolve_says_it_has_no_registry(
        self, client: TestClient, auth: dict[str, str]
    ) -> None:
        r = client.post("/v1/resolve", headers=auth)
        assert r.status_code == 501
        assert "registry" in r.json()["detail"]["detail"]

    def test_attest_says_only_the_issuer_can_confirm(
        self, client: TestClient, auth: dict[str, str]
    ) -> None:
        r = client.post("/v1/attest", headers=auth)
        assert r.status_code == 501
        assert "issuer" in r.json()["detail"]["detail"]


class TestDegradedMeansSomething:
    """Any gap at all was the first definition and it was useless: CodeChef publishes
    no API, so every run has a gap and every report was degraded."""

    def graph(self, *, degraded: bool) -> ClaimGraph:
        base = empty_report("vr_x", ReportStatus.COMPLETED).claim_graph
        meta = base.extraction_meta.model_copy(update={"degraded": degraded})
        return base.model_copy(update={"extraction_meta": meta})

    def bundle(self, *reasons: str):
        from cvv.models import EvidenceBundle, Gap, GapReason

        return EvidenceBundle(
            bundle_id="eb_t", graph_id="cg_t", gathered_at=NOW,
            gaps=[Gap(source="s", reason=GapReason(r), detail="d") for r in reasons],
        )

    def test_a_missing_connector_is_not_a_degradation(self) -> None:
        """CodeChef having no API is a permanent property of this system, not
        something that went wrong with this run."""
        assert pipeline.status(self.graph(degraded=False), self.bundle("not_supplied")) is (
            ReportStatus.COMPLETED
        )

    def test_an_account_that_does_not_exist_is_a_finding_not_a_failure(self) -> None:
        assert pipeline.status(self.graph(degraded=False), self.bundle("not_found")) is (
            ReportStatus.COMPLETED
        )

    def test_a_transient_outage_is(self) -> None:
        """Re-running may return more, and the client should know that."""
        for reason in ("unreachable", "rate_limited"):
            assert pipeline.status(self.graph(degraded=False), self.bundle(reason)) is (
                ReportStatus.COMPLETED_DEGRADED
            )

    def test_so_is_an_extraction_that_dropped_more_than_it_kept(self) -> None:
        assert pipeline.status(self.graph(degraded=True), self.bundle()) is (
            ReportStatus.COMPLETED_DEGRADED
        )


@pytest.mark.live
@pytest.mark.skipif(not CV.is_file(), reason="the reference CV is not present")
def test_a_real_cv_through_the_http_surface() -> None:
    """The whole pipeline over HTTP: upload, poll, read, trace a claim to its span."""
    client = TestClient(api.app)
    auth = {"Authorization": f"Bearer {api.API_KEY}"}

    with CV.open("rb") as handle:
        accepted = client.post(
            "/v1/verifications",
            headers=auth,
            files={"document": ("cv.pdf", handle, "application/pdf")},
        )
    assert accepted.status_code == 202
    verification_id = accepted.json()["verification_id"]

    report = client.get(f"/v1/verifications/{verification_id}", headers=auth)
    assert report.status_code == 200
    body = report.json()
    assert body["status"] in ("completed", "completed_degraded")
    assert body["claim_graph"]["claims"], "a real CV must yield claims"
    assert len(body["findings"]["rule_outcomes"]) >= 27
    assert body["narrative"]["summary"]
    assert "No score is produced" in body["narrative"]["summary"]

    claim_id = body["claim_graph"]["claims"][0]["claim_id"]
    provenance = client.get(
        f"/v1/verifications/{verification_id}/claims/{claim_id}/provenance", headers=auth
    )
    assert provenance.status_code == 200
    assert provenance.json()["verbatim"] in body["claim_graph"]["source"]["normalised_text"]
