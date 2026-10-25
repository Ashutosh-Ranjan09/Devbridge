"""The HTTP surface — §05 of the integration spec, in one process.

The spec draws three services: `cvv-api` orchestrating, `cvv-understanding` owning
extraction and narration, `cvv-judgement` owning the rules. This system collapsed
that into one package by an explicit decision, so the three route groups live here
and call functions instead of each other. The BOUNDARIES survive: `/v1/narrate`
still accepts only a FindingsReport, `/v1/evaluate` still accepts only a ClaimGraph.
Those restrictions are the point of the split, and they hold whether the call crosses
a network or a stack frame.

What is deliberately absent: a queue. `arq` and Redis are in the stack's "not used"
list, and `BackgroundTasks` runs a verification in this process. That is honest for a
single-process service and is the first thing to replace when it stops being one.
"""

from __future__ import annotations

import datetime
import json
import secrets
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Any

import httpx
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUpload

from cvv import __version__
from cvv.config import settings
from cvv.extract import extract
from cvv.gather import gather
from cvv.ids import stable_id
from cvv.ingest import document_info, read
from cvv.logs import configure, get
from cvv.models import (
    ApiError,
    ClaimGraph,
    DocumentInfo,
    EvidenceBundle,
    FindingsReport,
    Gap,
    GapReason,
    Narrative,
    ProvenanceView,
    ReportProvenance,
    ReportStatus,
    Subject,
    Usage,
    VerificationAccepted,
    VerificationReport,
    VerificationRequest,
    Webhook,
)
from cvv.narrative import PROMPT_VERSION, narrate
from cvv.pipeline import CONTRACT_VERSION, verification_report
from cvv.providers import default_provider
from cvv.report import assemble, coverage
from cvv.rules import REGISTRY
from cvv.store import STORE, Duplicate

SNIPPET_MARGIN = 120

# The API is imported rather than invoked through the CLI when a server runs it, so
# it configures logging itself. `configure` is idempotent.
configure(settings.log_level)
log = get("cvv.api")

app = FastAPI(
    title="cvv — CV Verification Engine",
    version=__version__,
    description=(
        "Verifies developer CVs against the systems they name. Produces no score and "
        "no verdict: it reports evidence and states what it could not check."
    ),
)

# Generated when unset, and printed at startup. A verification handles personal data,
# so an open-by-default surface is the wrong default — and refusing to start is the
# wrong answer for a research tool nobody has configured yet.
API_KEY = settings.api_key or secrets.token_urlsafe(24)


def authorise(authorization: Annotated[str | None, Header()] = None) -> None:
    """Bearer token, compared in constant time.

    `secrets.compare_digest` rather than `==`: string comparison returns early on the
    first differing byte, which leaks the shared prefix to anyone who can time it.
    """
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not supplied or not secrets.compare_digest(supplied, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supply the API key as `Authorization: Bearer <key>`.",
            headers={"WWW-Authenticate": "Bearer"},
        )


Auth = Annotated[None, Depends(authorise)]


# --------------------------------------------------------------------------- #
# Running one verification
# --------------------------------------------------------------------------- #


def _offline_bundle(graph: ClaimGraph, bundle_id: str) -> EvidenceBundle:
    """The document-only path, as a bundle of typed gaps.

    Every check that needed a source abstains WITH ITS REASON, which is the invariant
    made concrete: a CV naming no account still produces a complete, honest report.
    """
    return EvidenceBundle(
        bundle_id=bundle_id,
        graph_id=graph.graph_id,
        gathered_at=datetime.datetime.now(datetime.UTC),
        gaps=[
            Gap(
                source=source,
                reason=GapReason.NO_CONSENT,
                detail="Requested with options.offline; no external source was consulted.",
            )
            for source in ("github", "codeforces", "leetcode")
        ],
    )


def run_verification(
    verification_id: str,
    path: Path,
    *,
    offline: bool,
    want_narrative: bool,
    subject: Subject | None = None,
) -> None:
    """The whole pipeline, and never an exception.

    A crash here runs in a background task where nothing is watching, so it is caught
    and stored as `status: failed` with the reason. A verification that vanishes is
    worse than one that reports its own failure: the client polls a 404 forever and
    has nothing to report to the person whose CV it was.
    """
    created = datetime.datetime.now(datetime.UTC)
    log.info("verification.started", verification_id=verification_id, offline=offline)
    document: DocumentInfo | None = None
    try:
        doc = read(path)
        document = document_info(doc)
        graph, _ = extract(
            doc,
            provider=default_provider(),
            graph_id=f"cg_{doc.document_id[4:]}",
        )
        bundle = (
            _offline_bundle(graph, f"eb_{doc.document_id[4:]}")
            if offline
            else gather(graph, bundle_id=f"eb_{doc.document_id[4:]}")
        )
        findings = assemble(
            graph,
            bundle,
            report_id=f"fr_{doc.document_id[4:]}",
            document=document,
        )
        report = verification_report(
            verification_id=verification_id,
            document=document,
            graph=graph,
            bundle=bundle,
            findings=findings,
            subject=subject,
            narrative=_narrative(findings) if want_narrative else None,
        )
        log.info(
            "verification.completed",
            verification_id=verification_id,
            status=report.status.value,
            claims=len(graph.claims),
            dropped=graph.extraction_meta.span_failures,
            findings=len(findings.discrepancies),
            gaps=len(bundle.gaps),
            seconds=round(
                (datetime.datetime.now(datetime.UTC) - created).total_seconds(), 1
            ),
        )
        STORE.complete(report)
    except Exception as exc:
        # The client sees `status: failed` and one line. Without this the stack that
        # produced it is gone, and the task ran in a thread nobody was watching.
        log.exception(
            "verification.failed", verification_id=verification_id, error=type(exc).__name__
        )
        STORE.complete(
            _failed(verification_id, f"{type(exc).__name__}: {exc}", document, subject)
        )
    finally:
        path.unlink(missing_ok=True)
        _fire_webhooks(verification_id)


def _failed(
    verification_id: str,
    reason: str,
    document: DocumentInfo | None = None,
    subject: Subject | None = None,
) -> VerificationReport:
    """A failure is still a report. Claims, evidence and findings are empty rather
    than absent, because a client parsing VerificationReport must not need two
    shapes. `document` is what was read before the failure — None when the file
    itself could not be read, which is the one report the contract cannot express."""
    now = datetime.datetime.now(datetime.UTC)
    from cvv.models import Buckets, ExtractionMeta, SourceInfo

    empty_graph = ClaimGraph(
        graph_id="cg_failed",
        source=SourceInfo(
            document_id=document.document_id if document else "doc_failed",
            normalised_text="",
        ),
        claims=[],
        extraction_meta=ExtractionMeta(
            model_id="-", prompt_version="-", input_hash="sha256:-", extracted_at=now
        ),
    )
    findings = FindingsReport(
        report_id="fr_failed",
        graph_id="cg_failed",
        discrepancies=[],
        rule_outcomes=[],
        buckets=Buckets(
            verified=[], contradicted=[], needs_context=[], not_evaluated=[], out_of_scope=[]
        ),
        evaluated_at=now,
    )
    return VerificationReport(
        verification_id=verification_id,
        status=ReportStatus.FAILED,
        subject=subject or Subject(subject_ref=f"subject:{verification_id}"),
        document=document,
        claim_graph=empty_graph,
        evidence_bundle=EvidenceBundle(
            bundle_id="eb_failed", graph_id="cg_failed", gathered_at=now
        ),
        findings=findings,
        coverage=coverage(findings),
        provenance=ReportProvenance(
            cvv_version=__version__,
            contract_version=CONTRACT_VERSION,
            rule_versions={rule.rule_id: rule.rule_version for rule in REGISTRY},
        ),
        valid_as_of=now,
        failure=reason,
    )


def _narrative(findings: FindingsReport) -> Narrative:
    provider = default_provider()
    result = narrate(findings, provider)
    return Narrative(
        summary=result.text,
        cited_finding_ids=[f.finding_id for f in findings.discrepancies],
        model_id=provider.model_id,
        prompt_version=PROMPT_VERSION,
        fallback_used=not result.faithful,
        rejected_because=result.rejected_because,
    )


def _fire_webhooks(verification_id: str) -> None:
    """Best effort, and it says so. A webhook that cannot be delivered must not fail
    the verification that was already completed and stored."""
    for hook in STORE.webhooks():
        try:
            httpx.post(
                hook.url,
                json={"verification_id": verification_id, "status": "completed"},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            log.warning(
                "webhook.failed", webhook_id=hook.webhook_id, error=type(exc).__name__
            )
            continue


# --------------------------------------------------------------------------- #
# cvv-api — the public surface
# --------------------------------------------------------------------------- #


async def _incoming(http: Request) -> tuple[VerificationRequest, UploadFile | None]:
    """The spec's body, "multipart or JSON". In multipart, `document` is the file and
    `options` / `external_signals` / `document_url` are form fields, the first two
    JSON-encoded. Anything malformed is a 422 that says which field.

    A dependency rather than parameters because FastAPI cannot take a file and a JSON
    model in one signature: the first version declared both, so a JSON body never
    reached `body` and a multipart upload's `options` were silently dropped.
    """
    kind = http.headers.get("content-type", "")
    try:
        if kind.startswith("multipart/form-data"):
            form = await http.form()
            upload = form.get("document")
            fields: dict[str, Any] = {
                k: v
                for k in ("options", "external_signals", "document_url")
                if isinstance(v := form.get(k), str)
            }
            for k in ("options", "external_signals"):
                if k in fields:
                    fields[k] = json.loads(fields[k])
            return (
                VerificationRequest.model_validate(fields),
                upload if isinstance(upload, StarletteUpload) else None,  # type: ignore[return-value]
            )
        if kind.startswith("application/json"):
            return VerificationRequest.model_validate(await http.json()), None
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ApiError(error="invalid_request", detail=str(exc)).model_dump(),
        ) from exc
    return VerificationRequest(), None  # nothing usable: _payload says "no_document"


@app.post("/v1/verifications", status_code=status.HTTP_202_ACCEPTED)
def create_verification(
    _: Auth,
    background: BackgroundTasks,
    response: Response,
    incoming: Annotated[tuple[VerificationRequest, UploadFile | None], Depends(_incoming)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> VerificationAccepted:
    """Accept a CV and start verifying it. 202, always — the work takes ~20 seconds.

    A retry carrying the same `Idempotency-Key` gets the FIRST verification's id back
    rather than starting a second run. Without that, a client retrying a timed-out
    upload reloads the model and spends someone's API rate limit again for a document
    already being processed.
    """
    if idempotency_key and (known := STORE.existing(idempotency_key)):
        response.status_code = status.HTTP_200_OK
        return VerificationAccepted(
            verification_id=known, status="known", estimated_seconds=0
        )

    request, document = incoming
    suffix, payload = _payload(document, request)

    verification_id = "vr_" + stable_id(uuid.uuid4().hex)[:12]
    with NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(payload)
        path = Path(handle.name)

    try:
        STORE.accept(verification_id, idempotency_key=idempotency_key)
    except Duplicate as clash:
        # Two retries of the same upload arrived together and the store settled it.
        # The loser gets the winner's id and starts nothing.
        path.unlink(missing_ok=True)
        response.status_code = status.HTTP_200_OK
        return VerificationAccepted(
            verification_id=clash.verification_id, status="known", estimated_seconds=0
        )

    background.add_task(
        run_verification,
        verification_id,
        path,
        offline=request.options.offline,
        want_narrative=request.options.narrative,
        subject=request.subject,
    )
    return VerificationAccepted(
        verification_id=verification_id, status="queued", estimated_seconds=30
    )


def _payload(document: UploadFile | None, request: VerificationRequest) -> tuple[str, bytes]:
    """The bytes to verify, from an upload or a URL, with the extension that says how
    to read them. An unrecognised extension is refused here rather than guessed at."""
    if document is not None and document.filename:
        suffix = Path(document.filename).suffix.lower()
        payload = document.file.read()
    elif request.document_url:
        try:
            fetched = httpx.get(request.document_url, timeout=30.0, follow_redirects=True)
            fetched.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=ApiError(error="unreadable_document", detail=str(exc)).model_dump(),
            ) from exc
        suffix = Path(str(request.document_url).split("?")[0]).suffix.lower()
        payload = fetched.content
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ApiError(
                error="no_document",
                detail="Supply a file as `document`, or a `document_url` in the body.",
            ).model_dump(),
        )

    if suffix not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ApiError(
                error="unreadable_document",
                detail=f"{suffix or 'a file with no extension'} is not supported; "
                "send .pdf or .docx. A scanned PDF is read by OCR automatically.",
            ).model_dump(),
        )
    return suffix, payload


@app.get("/v1/verifications/{verification_id}")
def get_verification(_: Auth, verification_id: str, response: Response) -> Any:
    """200 with the report, or 202 while it is still running."""
    if (report := STORE.report(verification_id)) is not None:
        return report
    if (job := STORE.pending(verification_id)) is not None:
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "verification_id": verification_id,
            "status": "running",
            "created_at": job.created_at,
        }
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such verification.")


@app.get("/v1/verifications/{verification_id}/claims/{claim_id}/provenance")
def get_provenance(_: Auth, verification_id: str, claim_id: str) -> ProvenanceView:
    """Where a claim came from, so a reviewer can find it on the page.

    The snippet is cut from the graph's own normalised text — the exact string every
    offset in the system indexes into — so what is shown is what was checked.
    """
    report = STORE.report(verification_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such verification.")

    claim = next((c for c in report.claim_graph.claims if c.claim_id == claim_id), None)
    if claim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{claim_id} is not a claim in this verification.",
        )

    text = report.claim_graph.source.normalised_text
    p = claim.provenance
    return ProvenanceView(
        claim_id=claim.claim_id,
        verbatim=p.verbatim,
        char_start=p.char_start,
        char_end=p.char_end,
        page=p.page,
        # Null until ingest keeps per-character geometry. A guessed rectangle would
        # send a reviewer to the wrong line, which is worse than showing none.
        bbox=None,
        snippet=text[max(0, p.char_start - SNIPPET_MARGIN) : p.char_end + SNIPPET_MARGIN],
    )


@app.post("/v1/webhooks", status_code=status.HTTP_201_CREATED)
def register_webhook(_: Auth, url: str) -> Webhook:
    hook = Webhook(
        webhook_id="wh_" + stable_id(url)[:12],
        url=url,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    STORE.register(hook)
    return hook


@app.get("/v1/usage")
def usage(_: Auth) -> Usage:
    total, completed, failed = STORE.counts()
    return Usage(
        verifications_total=total,
        verifications_completed=completed,
        verifications_failed=failed,
        since=STORE.started,
    )


@app.get("/healthz")
def healthz() -> dict[str, object]:
    """Unauthenticated on purpose — a health check a load balancer cannot call is not
    a health check. It carries no data about any verification."""
    return {
        "status": "ok",
        "version": __version__,
        "store": STORE.name,
        "rules": len(REGISTRY),
        "model": settings.ollama_model,
    }


@app.get("/readyz")
def readyz() -> Any:
    """Ready means the MODEL answers, not that the process started.

    A service that accepts uploads and cannot reach Ollama returns 202 and then fails
    every one of them in the background, where the client sees a report that says
    `failed` twenty seconds later instead of a refusal now.
    """
    try:
        httpx.get(f"{settings.ollama_url}/api/tags", timeout=5.0).raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Ollama is not reachable at {settings.ollama_url}: {exc}",
        ) from exc
    return {"status": "ready"}


# --------------------------------------------------------------------------- #
# cvv-understanding — the model owns these
# --------------------------------------------------------------------------- #


@app.post("/v1/narrate")
def narrate_endpoint(_: Auth, findings_report: FindingsReport) -> Narrative:
    """Prose from findings, and NOTHING ELSE IS ACCEPTED.

    Not the document, not the claim graph. The guarantee that a narrative cannot
    quote a fact nobody computed is enforced by this signature rather than by the
    prompt — an endpoint that cannot receive the source text cannot leak it into
    prose, whatever the model is asked to do.
    """
    return _narrative(findings_report)


@app.post("/v1/resolve")
def resolve_endpoint(_: Auth) -> Any:
    """Not built, and the reason is data rather than code.

    Resolving a surface form to a canonical id needs the registry to resolve
    against — ESCO for skills, AICTE and UGC for institutions, a companies register
    for employers. None is available here. Returning an empty result would let a
    caller believe resolution ran and found nothing.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=ApiError(
            error="not_implemented",
            detail="Resolution needs a registry to resolve against — ESCO, AICTE, UGC "
            "or a companies register. None is installed, and an empty result would "
            "read as 'resolved to nothing' rather than 'never attempted'.",
        ).model_dump(),
    )


# --------------------------------------------------------------------------- #
# cvv-judgement — the rules own these
# --------------------------------------------------------------------------- #


@app.post("/v1/evaluate")
def evaluate_endpoint(_: Auth, claim_graph: ClaimGraph) -> FindingsReport:
    """Rules over a claim graph, with no evidence and therefore many abstentions.

    Deliberately the document-only path: `rules/` imports no HTTP client, so this
    endpoint cannot gather anything, and every check that needs a source abstains
    with its reason. A caller holding its own evidence posts to /v1/verifications
    with `external_signals` instead.
    """
    return assemble(
        claim_graph,
        _offline_bundle(claim_graph, "eb_evaluate"),
        report_id="fr_" + stable_id(claim_graph.graph_id)[:12],
    )


@app.get("/v1/rules")
def rules_endpoint() -> list[dict[str, object]]:
    """The live catalogue — unauthenticated, because it describes the SYSTEM and
    names no candidate. It exists so a caller's fixtures can assert against the rule
    set and see a new rule the day it lands rather than at integration."""
    return [
        {
            "rule_id": rule.rule_id,
            "version": rule.rule_version,
            "tier": rule.tier.value,
            "scoring": rule.scoring,
            "summary": rule.summary,
        }
        for rule in sorted(REGISTRY, key=lambda r: r.rule_id)
    ]


@app.post("/v1/attest")
def attest_endpoint(_: Auth) -> Any:
    """Not built — C1 to C4, blocked on per-issuer APIs and registry data.

    A credential can only be confirmed by whoever issued it. Anything this endpoint
    returned without an issuer behind it would be a verification outcome nobody
    verified, which is the one thing this system must never produce.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=ApiError(
            error="not_implemented",
            detail="Credential attestation needs the issuer's own API. Only the "
            "issuer can confirm a credential, and an outcome without one behind it "
            "would be a verification nobody performed.",
        ).model_dump(),
    )
