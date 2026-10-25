
"""ClaimGraph + EvidenceBundle + FindingsReport → EvidenceEventBatch.

The one job: decide what capability signal each verified artefact carries, and
how far to trust it. Nothing here decides whether a claim is true — that already
happened in M5 — and nothing here computes a score, which is M6's scoring engine.

Deterministic and side-effect free: same report in, byte-identical batch out.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from .errors import ContractViolation, MalformedReport
from .models import (EvidenceEvent, EvidenceEventBatch, EventSource, ReliabilityFactor,
                     SkillRef, Suppressed, SUPPRESSION_REASONS)
from .params import Rules, default_rules
from .rules import (apply_factors, event_id, framework_relevance, language_relevances,
                    normalise_skill, repo_strength, substance_band)

MODULE = "m5-cv-verification"
VERIFIED_OWNERSHIP = frozenset(("verified_oauth", "verified_challenge"))
PLATFORM_BASE_RELEVANCE = {"algorithms": 0.95, "problem_solving": 0.90}
PLATFORM_EXTRA_RELEVANCE = 0.70
NON_CAPABILITY_KINDS = frozenset(("employment", "education", "identifier", "profile",
                                  "declaration_marker"))


def _as_date(value: Any) -> date:
    """Normalise any timestamp to its UTC calendar day.

    Truncating the string to its first ten characters would take the *local*
    day, so `2025-03-01T20:30:00-08:00` — instant 2025-03-02T04:30Z — would be
    recorded as the 1st. occurred_at is the fold ordering key and the subject of
    the future-event invariant, so it has to be canonical rather than merely
    close. A bare `YYYY-MM-DD` carries no offset and is taken as given.
    """
    if isinstance(value, datetime):
        return _utc_day(value)
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            if len(text) == 10:
                return date.fromisoformat(text)
            return _utc_day(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError as exc:
            raise MalformedReport(f"cannot read a date from {value!r}") from exc
    raise MalformedReport(f"cannot read a date from {value!r}")


def _utc_day(moment: datetime) -> date:
    """The UTC calendar day of an instant. A naive datetime is already UTC by
    contract — M5 emits Z — so it is read as such rather than as local time."""
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(timezone.utc).date()


def _claims(report: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    return [c for c in report["claim_graph"]["claims"] if c.get("kind") == kind]


def _repo_segment(url: Any) -> str:
    """The repository name a URL points at, or "" if it points at no repository.

    `https://github.com/dev/ATMA-Final` → `atma-final`; a deployment host with an
    empty path → "". Trailing slashes and a `.git` suffix are stripped.
    """
    path = urlparse(str(url or "")).path.rstrip("/")
    if not path:
        return ""
    segment = path.rsplit("/", 1)[-1]
    if segment.endswith(".git"):
        segment = segment[:-4]
    return segment.lower()


def _confirms(plat: Mapping[str, Any], claim: Mapping[str, Any], rules: Rules) -> bool:
    """Whether a platform's own record reaches what the claim asserts.

    Only for metrics where more is better, and only on numbers both sides state —
    a claim the platform falls short of is not confirmed, and stays a cv_claim.
    """
    metric = claim.get("metric")
    claimed, actual = claim.get("value"), plat.get(metric)
    if metric not in rules.confirmable_metrics or claimed is None or actual is None:
        return False
    return float(claimed) <= float(actual)


def _links_repo(claim: Mapping[str, Any], repo_name: str) -> bool:
    """Whether a claim cites this repository.

    Substring matching (`repo["name"] in url`) would attribute a repository
    called `ATMA` to a claim about `ATMA-Final`. claim_refs is the audit trail a
    recruiter is shown, and in a system with no overall trust score the
    explanation is the product — so the final path segment must match exactly.
    """
    wanted = repo_name.strip().lower()
    return any(_repo_segment(a.get("url")) == wanted for a in claim.get("artefacts") or [])


def project(
    report: Mapping[str, Any],
    *,
    rules: Rules | None = None,
    module_version: str = "0.0.0",
    now: date | None = None,
) -> EvidenceEventBatch:
    """Project one VerificationReport. Raises MalformedReport on missing
    structure; never guesses."""
    r = rules or default_rules()
    try:
        vid = report["verification_id"]
        subject = report["subject"]
        bundle = report["evidence_bundle"]
    except KeyError as exc:  # pragma: no cover - defensive
        raise MalformedReport(f"report is missing {exc}") from exc

    valid_as_of = _as_date(report.get("valid_as_of") or bundle["gathered_at"])
    emitted_at = now or valid_as_of

    # An uncorroborated CV claim is evidence about the moment the CV was written,
    # not about the moment someone verified it. Dating it at verification time
    # would hand the weakest evidence in the system perfect freshness, so a
    # two-year-old assertion would never decay. Fall back to valid_as_of only
    # when the document carries no date of its own.
    document = report.get("document") or {}
    asserted_at = _as_date(document.get("created_at") or valid_as_of)
    batch_id = event_id(vid, "batch", subject["subject_ref"]).replace("ev_", "evb_")

    base = dict(batch_id=batch_id, verification_id=vid,
                subject_ref=subject["subject_ref"], emitted_at=emitted_at)

    events: list[EvidenceEvent] = []
    suppressed: list[Suppressed] = []
    quarantined: list[str] = []

    github = bundle.get("github")
    unverified = bool(github) and github.get("ownership") not in VERIFIED_OWNERSHIP
    cap = ("ownership_unverified",) if unverified else ()

    def source(origin: str, claim_refs: Iterable[str] = (), ref: str | None = None) -> EventSource:
        return EventSource(module=MODULE, module_version=module_version, origin=origin,
                           verification_id=vid, claim_refs=tuple(claim_refs), evidence_ref=ref)

    def build(kind: str, disc: str, occurred: date, strength: float, skills: Mapping[str, float],
              origin: str, *, factors: tuple[str, ...] = (), direction: str = "positive",
              claim_refs: Iterable[str] = (), payload: dict[str, Any] | None = None) -> None:
        rule_base = r.priors(kind).reliability_base
        reliability, applied = apply_factors(rule_base, direction, factors, r)
        refs = tuple(SkillRef(s, v) for s, v in sorted(skills.items()) if v > 0)
        if not refs:
            quarantined.append(f"{kind}:{disc} — no resolvable skill")
            return
        events.append(EvidenceEvent(
            event_id=event_id(vid, kind, disc), kind=kind, occurred_at=occurred,
            observed_at=_as_date(bundle["gathered_at"]), skill_refs=refs,
            strength=strength, reliability=reliability, direction=direction,
            reliability_base=rule_base,
            reliability_factors=tuple(ReliabilityFactor(n, v, why) for n, v, why in applied),
            source=source(origin, claim_refs, disc), payload=payload or {}))

    # ── platform ratings — authoritative, never capped ──────────────────────
    corroborated_platforms: set[str] = set()
    # metric -> the platforms that independently reported it, and what they said.
    verified_metrics: dict[str, list[dict[str, Any]]] = {}
    achievements = _claims(report, "achievement")
    confirmed_claims: set[str] = set()
    for plat in bundle.get("platforms") or []:
        if not plat.get("found") or plat.get("max_rating") is None:
            continue
        name = plat["platform"]
        for metric in r.corroboratable_metrics:
            if plat.get(metric) is not None:
                verified_metrics.setdefault(metric, []).append(
                    {"platform": name, "value": plat[metric]})
        linked = [c for c in achievements if c.get("platform") == name]
        skills = dict(PLATFORM_BASE_RELEVANCE)
        for c in linked:
            for s in c.get("skill_refs") or []:
                skills.setdefault(normalise_skill(s, r), PLATFORM_EXTRA_RELEVANCE)
        when = next((_as_date(c["date"]) for c in plat.get("contests") or []
                     if c.get("rating_after") == plat["max_rating"]),
                    _as_date(bundle["gathered_at"]))
        # Ownership is never capped here — the handle resolved and the platform
        # is the authority on its own ratings. HOW we read it is a different
        # question: a scraped page can be stale or misparsed in ways an API
        # response cannot, so that discount does apply.
        quality = str(plat.get("source_quality") or "").lower()
        plat_factors = (("scraped_source",)
                        if quality in r.scraped_source_qualities else ())
        if name not in r.rated_platforms:
            # A scale 6.3 cannot place. The platform still confirms what the CV
            # claimed, and that needs no scale — see rating_reference.
            confirmed = [c for c in linked if _confirms(plat, c, r)]
            for c in confirmed:
                build("claim_corroborated", f"{c['claim_id']}:{name}", when,
                      r.priors("claim_corroborated").strength, skills, f"{name}_api",
                      factors=plat_factors, claim_refs=[c["claim_id"]],
                      payload={"platform": name, "metric": c.get("metric"),
                               "claimed": c.get("value"),
                               "platform_value": plat.get(c.get("metric")),
                               "source_quality": plat.get("source_quality")})
            confirmed_claims.update(c["claim_id"] for c in confirmed)
            if not confirmed:
                suppressed.append(Suppressed(
                    f"{name} rating {plat['max_rating']} — no reference distribution "
                    "places this platform's scale, and no claim it confirms",
                    "not_a_capability_signal"))
            continue
        corroborated_platforms.add(name)
        build("platform_rating", f"{name}:{plat.get('handle', '')}", when,
              r.priors("platform_rating").strength, skills, f"{name}_api",
              factors=plat_factors,
              claim_refs=[c["claim_id"] for c in linked],
              payload={"platform": name, "max_rating": plat["max_rating"],
                       "rank_title": plat.get("rank_title"),
                       "problems_solved": plat.get("problems_solved"),
                       "source_quality": plat.get("source_quality")})

    # ── repositories ────────────────────────────────────────────────────────
    projects = _claims(report, "project")
    repo_languages: dict[str, list[dict[str, Any]]] = {}
    for repo in (github or {}).get("repos") or []:
        if not (repo.get("exists") and repo.get("owner_matches")
                and not repo.get("is_fork") and not repo.get("is_readme_only")):
            suppressed.append(Suppressed(
                f"{repo.get('name')} — fork, shell or not owned", "not_a_capability_signal"))
            continue
        band, index = substance_band(repo, r)
        skills = language_relevances(repo.get("languages") or {}, r)
        for fw in repo.get("frameworks") or []:
            s = normalise_skill(fw, r)
            skills[s] = max(skills.get(s, 0.0), framework_relevance(s, r))
        for s in skills:
            repo_languages.setdefault(s, []).append(repo)
        linked = [c for c in projects if _links_repo(c, repo["name"])]
        build("repo_artifact", repo["name"], _as_date(repo["last_commit"]),
              repo_strength(index, r), skills, "github_api", factors=cap,
              claim_refs=[c["claim_id"] for c in linked],
              payload={"repo": repo["name"], "substance_band": band,
                       "commit_count": repo.get("commit_count"), "size_kb": repo.get("size_kb"),
                       "languages": repo.get("languages"), "is_fork": False})

    # ── skill claims: corroborated, or merely claimed ───────────────────────
    disclaimed = {s for c in _claims(report, "declaration_marker") for s in c.get("scope") or []}
    for claim in _claims(report, "skill"):
        for raw in claim.get("skill_refs") or []:
            skill = normalise_skill(raw, r)
            backing = repo_languages.get(skill)
            if backing:
                when = max(_as_date(x["last_commit"]) for x in backing)
                build("claim_corroborated", f"{claim['claim_id']}:{skill}", when,
                      r.priors("claim_corroborated").strength, {skill: 1.0}, "github_api",
                      factors=cap, claim_refs=[claim["claim_id"]],
                      payload={"proficiency": claim.get("proficiency"),
                               "corroborating_repos": [x["name"] for x in backing]})
            else:
                build("cv_claim", f"{claim['claim_id']}:{skill}", asserted_at,
                      r.priors("cv_claim").strength, {skill: 1.0}, "cv_document",
                      claim_refs=[claim["claim_id"]],
                      payload={"proficiency": claim.get("proficiency")})

    # ── achievements with no platform behind them ───────────────────────────
    ach_map = r._t.get("achievement_skill_map", {})  # noqa: SLF001 - contract accessor
    for claim in achievements:
        if claim.get("platform") in corroborated_platforms:
            continue  # already carried by the platform_rating event
        if claim["claim_id"] in confirmed_claims:
            continue  # already carried by its claim_corroborated event
        skills = {normalise_skill(s, r): 1.0
                  for s in (claim.get("skill_refs") or ach_map.get(claim.get("metric"), []))}
        if not skills:
            suppressed.append(Suppressed(
                f"{claim['claim_id']} — {claim.get('metric') or 'achievement'} has no skill mapping",
                "no_skill_mapping"))
            continue
        # An aggregate over several platforms where only some were verified is
        # not the same evidence as an unbacked assertion. The verified counts go
        # into the payload so the scoring engine can weigh the real number rather
        # than the asserted one, while the claim itself is discounted to the
        # remainder — the verified part is already carried by platform_rating.
        metric = claim.get("metric")
        context = claim.get("context") or {}
        confirmed = [v for v in verified_metrics.get(metric, [])
                     if v["platform"] in (context.get("platforms") or [v["platform"]])]
        payload = {"metric": metric, "value": claim.get("value")}
        if context.get("platforms"):
            payload["platforms_claimed"] = context["platforms"]
        if confirmed:
            payload["independently_confirmed"] = confirmed

        build("cv_claim", f"{claim['claim_id']}:achievement", asserted_at,
              r.priors("cv_claim").strength, skills, "cv_document",
              factors=r.claim_discount_factors(claim.get("flags"), context.get("bound")),
              claim_refs=[claim["claim_id"]], payload=payload)

    # ── deployments ─────────────────────────────────────────────────────────
    for dep in bundle.get("deployments") or []:
        url = dep["url"]
        if not dep.get("reachable"):
            suppressed.append(Suppressed(
                f"W1 — {url} returns {dep.get('status_code')}", "not_a_capability_signal"))
            continue
        linked = [c for c in projects
                  if any(url == a.get("url") for a in c.get("artefacts") or [])]
        declared = {normalise_skill(fw, r)
                    for c in linked
                    for repo in (github or {}).get("repos") or []
                    if _links_repo(c, repo["name"])
                    for fw in repo.get("frameworks") or []}
        primary = next((fw for fw in r.deployment_frameworks if fw in declared), None)
        skills = {"deployment": 0.70}
        if primary:
            skills[primary] = 0.60
        build("artifact_live", url, _as_date(dep.get("checked_at") or bundle["gathered_at"]),
              r.priors("artifact_live").strength, skills, "http_probe", factors=cap,
              claim_refs=[c["claim_id"] for c in linked],
              payload={"url": url, "status_code": dep.get("status_code")})

    # ── credentials ─────────────────────────────────────────────────────────
    # A certification CLAIM is what the CV asserts; a credential in the bundle is
    # what the issuer confirmed. They are matched here so the event carries the
    # claim it corroborates, and so an asserted certification nobody could
    # confirm is still accounted for rather than quietly disappearing.
    certifications = _claims(report, "certification")
    verified_certs: set[str] = set()
    for cred in bundle.get("credentials") or []:
        status = cred.get("status")
        if not (cred.get("verified") or status == "verified"):
            continue
        cred_id = cred.get("credential_id")
        linked = [c for c in certifications
                  if (cred_id and c.get("credential_id") == cred_id)
                  or (c.get("issuer") and c.get("issuer") == cred.get("issuer"))]
        verified_certs.update(c["claim_id"] for c in linked)
        skills = {normalise_skill(s, r): 1.0
                  for s in (cred.get("skill_refs")
                            or [s for c in linked for s in c.get("skill_refs") or []])}
        build("credential_verified", cred_id or cred.get("issuer", "?"),
              _as_date(cred.get("issued_at") or bundle["gathered_at"]),
              r.priors("credential_verified").strength, skills, "issuer_api",
              claim_refs=[c["claim_id"] for c in linked],
              payload={"issuer": cred.get("issuer"), "credential_id": cred_id})

    # A certification the issuer did not confirm is a self-report like any other.
    for claim in certifications:
        if claim["claim_id"] in verified_certs:
            continue
        skills = {normalise_skill(s, r): 1.0 for s in claim.get("skill_refs") or []}
        if not skills:
            suppressed.append(Suppressed(
                f"{claim['claim_id']} — certification from "
                f"{claim.get('issuer') or 'an unnamed issuer'} names no skill",
                "no_skill_mapping"))
            continue
        build("cv_claim", f"{claim['claim_id']}:certification", asserted_at,
              r.priors("cv_claim").strength, skills, "cv_document",
              claim_refs=[claim["claim_id"]],
              payload={"issuer": claim.get("issuer"),
                       "credential_id": claim.get("credential_id"),
                       "issuer_confirmed": False})

    # ── project claims nothing corroborated ─────────────────────────────────
    # A project whose repository is a fork, missing, or never supplied is still
    # an assertion the candidate made. Treated exactly like an unbacked skill
    # claim: weak evidence, not absent evidence.
    carried = {ref for e in events for ref in e.source.claim_refs}
    for claim in projects:
        if claim["claim_id"] in carried:
            continue
        skills = {normalise_skill(s, r): 1.0 for s in claim.get("skill_refs") or []}
        if not skills:
            suppressed.append(Suppressed(
                f"{claim['claim_id']} — project claim with no verifiable artefact "
                "and no skill named",
                "no_skill_mapping"))
            continue
        build("cv_claim", f"{claim['claim_id']}:project", asserted_at,
              r.priors("cv_claim").strength, skills, "cv_document",
              claim_refs=[claim["claim_id"]],
              payload={"project": claim.get("title"), "artefact_verified": False})

    # ── standing suppressions ───────────────────────────────────────────────
    non_capability = [c["claim_id"] for c in report["claim_graph"]["claims"]
                      if c.get("kind") in NON_CAPABILITY_KINDS]
    if non_capability:
        suppressed.append(Suppressed(
            "employment, education, identifier and profile claims — "
            f"{', '.join(sorted(non_capability))}", "no_skill_mapping"))
    if disclaimed:
        suppressed.append(Suppressed(
            f"claims disclaimed by the document itself: {', '.join(sorted(disclaimed))}",
            "institution_disclaimed"))
    if unverified:
        suppressed.append(Suppressed(
            "G3 — GitHub ownership unproven; expressed as a reliability factor, not an event",
            "non_scoring_rule"))

    events.sort(key=lambda e: (_as_date(e.occurred_at), e.event_id))
    batch = EvidenceEventBatch(**base, events=tuple(events),
                               not_emitted=tuple(suppressed), quarantined=tuple(quarantined))
    _check_invariants(batch, r,
                      claim_ids=[c["claim_id"] for c in report["claim_graph"]["claims"]])
    return batch


def _check_invariants(batch: EvidenceEventBatch, rules: Rules,
                      claim_ids: Iterable[str] = ()) -> None:
    """The invariants from projection-rules.yaml, enforced rather than trusted."""
    seen: set[str] = set()
    for e in batch.events:
        if not e.skill_refs:
            raise ContractViolation(f"{e.event_id} has no skill_refs")
        if e.event_id in seen:
            raise ContractViolation(f"duplicate event_id {e.event_id}")
        seen.add(e.event_id)
        expected = e.reliability_base or 0.0
        for f in e.reliability_factors:
            expected *= f.value
        if abs(expected - e.reliability) > 1e-6:
            raise ContractViolation(
                f"{e.event_id}: reliability {e.reliability} != base × factors {expected}")
        if not 0.0 <= e.reliability <= 1.0 or not 0.0 <= e.strength <= 1.0:
            raise ContractViolation(f"{e.event_id}: strength/reliability out of [0,1]")
        for ref in e.skill_refs:
            if not 0.0 <= ref.relevance <= 1.0:
                raise ContractViolation(f"{e.event_id}: relevance out of [0,1]")
        if _as_date(e.occurred_at) > _as_date(batch.emitted_at):
            raise ContractViolation(f"{e.event_id}: occurred_at is in the future")
    for s in batch.not_emitted:
        if s.reason not in SUPPRESSION_REASONS:
            raise ContractViolation(f"suppression reason {s.reason!r} is not in the schema enum")

    # Silence is never an option. Every claim M5 extracted must be visible in the
    # output — carried by an event, or named in not_emitted with a reason. A claim
    # kind nobody wrote a branch for used to vanish here without trace; this makes
    # that a loud failure instead of a quiet one.
    referenced = {ref for e in batch.events for ref in e.source.claim_refs}
    explained = " ".join(s.what for s in batch.not_emitted)
    orphans = sorted(c for c in claim_ids
                     if c not in referenced and c not in explained)
    if orphans:
        raise ContractViolation(
            f"claims accounted for neither by an event nor a suppression: "
            f"{', '.join(orphans)}")
