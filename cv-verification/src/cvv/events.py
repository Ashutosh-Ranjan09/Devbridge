"""FindingsReport to the M6 evidence bus — the projection, not a second report.

`M6 does NOT consume discrepancies. It has no interest in fraud.` That single line in
the schema decides everything here: this module's job is to find the CORROBORATED
CAPABILITY SIGNALS inside a verification and leave the rest behind, with a typed
reason for each thing left.

Three rules it follows, all from the schema:

**Emission is fire-and-forget.** The batch is a value returned by a pure function.
Nothing here posts it anywhere, because "the standalone product must not acquire a
hard dependency on platform infrastructure" — a bus that is down must not fail a
verification that succeeded.

**Consent defaults to nothing.** M6 must refuse events whose scope does not cover
skill-graph inclusion, and this system holds no consent record. So it asserts none
and a caller who has one passes it. A batch that M6 refuses is better than one that
claims a permission nobody gave.

**Positive evidence from an unproven account is capped; negative is not.** The
ownership asymmetry, in the schema's own words. Nobody prints a handle that
undermines them, so evidence from a `claimed_unverified` account that contradicts the
CV is worth its full reliability and evidence that corroborates it is not.
"""

from __future__ import annotations

import datetime
import re

from cvv import __version__
from cvv.ids import stable_id
from cvv.logs import get
from cvv.models import (
    ClaimGraph,
    ClaimKind,
    Direction,
    EventKind,
    EventSource,
    EvidenceBundle,
    EvidenceEvent,
    EvidenceEventBatch,
    FindingsReport,
    Ownership,
    ReliabilityFactor,
    SkillRef,
    Suppressed,
    SuppressionReason,
    Tier,
)

log = get("cvv.events")

# The purpose a caller must assert for any of this to reach a skill graph.
SKILL_GRAPH = "skill_graph_inclusion"

# Base reliability by source, from the schema's own guidance: a self-reported claim is
# weak, an authoritative API is strong.
RELIABILITY = {
    EventKind.CV_CLAIM: 0.20,
    EventKind.PLATFORM_RATING: 0.90,
    EventKind.REPO_ARTIFACT: 0.75,
    EventKind.ARTIFACT_LIVE: 0.60,
    EventKind.CLAIM_CONTRADICTED: 0.90,
}

# What a positive signal from an account nobody proved control of is worth.
UNVERIFIED_CAP = 0.5
# What an undated observation is worth, since M6's decay kernel reads `occurred_at`.
UNDATED_CAP = 0.6
# How much of an observation bears on a skill we could not resolve to an ontology.
UNRESOLVED_RELEVANCE = 0.5


def skill(name: str) -> SkillRef:
    """A surface form in an explicit namespace, never passed off as canonical.

    `/v1/resolve` returns 501 because no registry is installed, so there is no honest
    way to produce an ESCO id here. `surface:` says so in the identifier itself, and
    the reduced relevance says it again in the number, so M6 can map or reject it
    knowingly rather than storing something invented.
    """
    return SkillRef(
        skill_id="surface:" + re.sub(r"[^a-z0-9+#.]+", "-", name.lower()).strip("-"),
        relevance=UNRESOLVED_RELEVANCE,
    )


def _cap(
    base: float, factors: list[ReliabilityFactor]
) -> float:
    value = base
    for factor in factors:
        value *= factor.value
    return round(value, 4)


def project(
    graph: ClaimGraph,
    bundle: EvidenceBundle,
    report: FindingsReport,
    *,
    verification_id: str,
    subject_ref: str,
    consent_scope: list[str] | None = None,
) -> EvidenceEventBatch:
    """One verification, projected onto the bus.

    `subject_ref` is supplied by the caller and is deliberately not derived from the
    CV. This module must not mint an identifier for a person out of their name or
    their roll number — that is the caller's record to hold, and inventing one here
    would make a candidate identifiable across verifications they never linked.
    """
    scope = consent_scope or []
    now = datetime.datetime.now(datetime.UTC)
    batch_id = "eb_" + stable_id(verification_id, now.isoformat())[:12]
    events: list[EvidenceEvent] = []
    withheld: list[Suppressed] = []

    def emit(
        kind: EventKind,
        *,
        occurred_at: datetime.datetime | None,
        skills: list[str],
        strength: float,
        direction: Direction,
        origin: str,
        claim_refs: list[str],
        evidence_ref: str | None = None,
        ownership: Ownership | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        if not skills:
            withheld.append(
                Suppressed(what=f"{kind.value} from {origin}", reason=SuppressionReason.NO_SKILL_MAPPING)
            )
            return

        factors: list[ReliabilityFactor] = []
        if ownership is Ownership.CLAIMED_UNVERIFIED and direction is Direction.POSITIVE:
            factors.append(
                ReliabilityFactor(
                    factor="ownership_unverified",
                    value=UNVERIFIED_CAP,
                    reason="Control of the account was never proven, and nobody prints "
                    "a handle that undermines them — so corroboration from it is "
                    "capped and contradiction from it is not.",
                )
            )
        if occurred_at is None:
            factors.append(
                ReliabilityFactor(
                    factor="undated_observation",
                    value=UNDATED_CAP,
                    reason="The CV gives this no date, so `occurred_at` is when the "
                    "verification ran rather than when the activity did. M6's decay "
                    "kernel would otherwise read it as happening today.",
                )
            )

        base = RELIABILITY.get(kind, 0.5)
        events.append(
            EvidenceEvent(
                event_id="ev_" + stable_id(batch_id, kind.value, origin, *skills, *claim_refs)[:12],
                kind=kind,
                occurred_at=occurred_at or now,
                # `now` is when this system looked. `occurred_at` falls back to it
                # when the CV gives no date, and the `undated_observation` factor
                # says so — the two being equal is information, not a duplicate.
                observed_at=now,
                skill_refs=[skill(name) for name in skills],
                strength=round(strength, 4),
                reliability_base=base,
                reliability=_cap(base, factors),
                reliability_factors=factors,
                direction=direction,
                source=EventSource(
                    module_version=__version__,
                    origin=origin,
                    verification_id=verification_id,
                    claim_refs=claim_refs,
                    evidence_ref=evidence_ref,
                ),
                payload=payload or {},
            )
        )

    # ----------------------------------------------------------------- consent
    if SKILL_GRAPH not in scope:
        # Everything is withheld, and the batch still goes — a receiver that can see
        # WHAT was withheld and WHY can ask for consent. An empty batch with no
        # explanation looks like a verification that found nothing.
        withheld.append(
            Suppressed(
                what="every event in this verification",
                reason=SuppressionReason.CONSENT_SCOPE_EXCLUDED,
            )
        )
        return EvidenceEventBatch(
            batch_id=batch_id,
            verification_id=verification_id,
            subject_ref=subject_ref,
            emitted_at=now,
            consent_scope=scope,
            events=[],
            not_emitted=withheld,
        )

    # The institution's own caveat scopes everything under it. Passing those claims on
    # as capability signals would launder a disclaimer the issuer wrote.
    if graph.claims and any(c.kind is ClaimKind.DECLARATION_MARKER for c in graph.claims):
        withheld.append(
            Suppressed(
                what="self-declared sections of the document",
                reason=SuppressionReason.INSTITUTION_DISCLAIMED,
            )
        )

    ownership = bundle.github.ownership if bundle.github else None

    # ------------------------------------------------------- platform ratings
    for platform in bundle.platforms:
        if not platform.found:
            continue
        rating = platform.max_rating or platform.current_rating
        if rating is None and platform.problems_solved is None:
            continue
        # The most recent rated contest is when the ability was demonstrated. A peak
        # rating with no contest history carries no date of its own.
        dated = [c.date for c in platform.contests if c.date]
        emit(
            EventKind.PLATFORM_RATING,
            occurred_at=(
                datetime.datetime.combine(max(dated), datetime.time(), datetime.UTC)
                if dated
                else None
            ),
            skills=["competitive programming", "algorithms", "data structures"],
            strength=0.8 if rating else 0.5,
            direction=Direction.POSITIVE,
            origin=f"{platform.platform.value}_api",
            claim_refs=[],
            evidence_ref=f"platforms[{platform.platform.value}]",
            payload={
                "platform": platform.platform.value,
                "max_rating": rating,
                "problems_solved": platform.problems_solved,
                "contests": len(platform.contests),
            },
        )

    # --------------------------------------------------------- repositories
    if bundle.github:
        for repo in bundle.github.repos:
            if not repo.exists or repo.is_fork or not repo.languages:
                continue
            emit(
                EventKind.REPO_ARTIFACT,
                # repo.created_at is server-side. A commit date is not — guardrail 6.
                occurred_at=(
                    datetime.datetime.combine(repo.created_at, datetime.time(), datetime.UTC)
                    if repo.created_at
                    else None
                ),
                skills=[*repo.languages, *repo.frameworks],
                strength=0.7,
                direction=Direction.POSITIVE,
                origin="github_api",
                claim_refs=[],
                evidence_ref=f"github.repos[{repo.name}]",
                ownership=ownership,
                payload={
                    "repo": repo.name,
                    "authored_files": repo.authored_files,
                    "authored_bytes": repo.authored_bytes,
                },
            )

    # ---------------------------------------------------------- deployments
    reachable = {d.url for d in bundle.deployments if d.reachable}
    checked = {d.url: d.checked_at for d in bundle.deployments}
    for claim in graph.claims:
        if claim.kind is not ClaimKind.PROJECT:
            continue
        for artefact in claim.artefacts:
            if artefact.type.value != "deployment" or artefact.url not in reachable:
                continue
            emit(
                EventKind.ARTIFACT_LIVE,
                occurred_at=checked.get(artefact.url),
                skills=claim.skill_refs,
                strength=0.6,
                direction=Direction.POSITIVE,
                origin="http_probe",
                claim_refs=[claim.claim_id],
                evidence_ref=f"deployments[{artefact.url}]",
                payload={"project": claim.title},
            )

    # ------------------------------------------------------ self-reported skills
    for claim in graph.claims:
        if claim.kind is not ClaimKind.SKILL or not claim.skill_refs:
            continue
        emit(
            EventKind.CV_CLAIM,
            occurred_at=None,  # a CV dates a job, never a skill
            skills=claim.skill_refs,
            strength=0.3,
            direction=Direction.POSITIVE,
            origin="cv_document",
            claim_refs=[claim.claim_id],
            payload={"stated_years": claim.stated_years},
        )

    # ------------------------------------------------------------- findings
    for finding in report.discrepancies:
        if not finding.scoring:
            withheld.append(
                Suppressed(what=f"{finding.rule_id} finding", reason=SuppressionReason.NON_SCORING_RULE)
            )
            continue
        # A contradicted platform statistic IS a capability signal, in the negative
        # direction. A contradicted employment date is not: it says something about
        # a CV, and M6 has no interest in that.
        if not finding.rule_id.startswith("P") or finding.tier is not Tier.DECISIVE:
            withheld.append(
                Suppressed(
                    what=f"{finding.rule_id} finding",
                    reason=SuppressionReason.NOT_A_CAPABILITY_SIGNAL,
                )
            )
            continue
        emit(
            EventKind.CLAIM_CONTRADICTED,
            occurred_at=None,
            skills=["competitive programming"],
            strength=0.7,
            direction=Direction.NEGATIVE,
            origin="cv_document",
            claim_refs=list(finding.claim_refs),
            evidence_ref=finding.finding_id,
            # NOT capped by ownership: the asymmetry runs one way, and the schema
            # says so — negative evidence from an unproven identity is full strength.
            payload={"rule_id": finding.rule_id, "params": dict(finding.params)},
        )

    log.info(
        "events.projected",
        verification_id=verification_id,
        events=len(events),
        withheld=len(withheld),
        consented=SKILL_GRAPH in scope,
    )
    return EvidenceEventBatch(
        batch_id=batch_id,
        verification_id=verification_id,
        subject_ref=subject_ref,
        emitted_at=now,
        consent_scope=scope,
        events=events,
        not_emitted=withheld,
    )
