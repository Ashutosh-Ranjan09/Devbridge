"""Claims to evidence — every outbound request in the system lives here.

Four connectors: Codeforces and LeetCode (public, no auth), GitHub (REST + GraphQL),
and HTTP liveness. The first two are the best return available in the whole system —
one unauthenticated call turns "peak rating 1495" from an assertion into a settled
fact, because the platform is the authority on its own numbers.

CodeChef is deliberately absent. It publishes no API, so a scraper is the only route,
and a scraper is a source that breaks silently and answers wrongly.

Every failure path writes a typed Gap and gathering continues. One dead source must
never fail the bundle: a rule that cannot run abstains with the gap's reason attached,
and that reason reaches the reader. Silence would read as a pass.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field

import httpx

from cvv.github import gather_github
from cvv.leetcode import gather_leetcode
from cvv.logs import get
from cvv.models import (
    ArtefactType,
    ClaimGraph,
    ClaimKind,
    ContestResult,
    DeploymentEvidence,
    EvidenceBundle,
    Gap,
    GapReason,
    Platform,
    PlatformEvidence,
)

CODEFORCES_API = "https://codeforces.com/api"
# Codeforces asks for no more than one request every two seconds.
CF_MIN_INTERVAL = 2.1
USER_AGENT = "cvv/0.1 (CV verification research; contact via repository)"
# One retry, after this long, before a silent URL is reported as silent.
PROBE_RETRY_SECONDS = 2.0

log = get("cvv.gather")


def _cf_get(client: httpx.Client, endpoint: str, **params: str) -> list[dict[str, object]]:
    response = client.get(f"{CODEFORCES_API}/{endpoint}", params=params, timeout=30.0)
    response.raise_for_status()
    body = response.json()
    if body.get("status") != "OK":
        raise LookupError(body.get("comment", "codeforces returned a non-OK status"))
    result: list[dict[str, object]] = body["result"]
    return result


def gather_codeforces(handle: str) -> PlatformEvidence | Gap:
    """user.info for the rating, user.rating for contest history, user.status for
    distinct solved problems.

    Codeforces is the authority on its own numbers, which is what makes P1-P3
    decisive. Handle ownership is irrelevant here: the handle resolved, and the
    platform's own record settles the question.
    """
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        try:
            info = _cf_get(client, "user.info", handles=handle)[0]
        except LookupError as exc:
            return Gap(source="codeforces", reason=GapReason.NOT_FOUND, detail=str(exc))
        except httpx.HTTPStatusError as exc:
            reason = (
                GapReason.RATE_LIMITED
                if exc.response.status_code == 429
                else GapReason.UNREACHABLE
            )
            return Gap(source="codeforces", reason=reason, detail=str(exc))
        except httpx.HTTPError as exc:
            return Gap(source="codeforces", reason=GapReason.UNREACHABLE, detail=str(exc))

        contests: list[ContestResult] = []
        solved: int | None = None

        time.sleep(CF_MIN_INTERVAL)
        try:
            for c in _cf_get(client, "user.rating", handle=handle):
                contests.append(
                    ContestResult(
                        name=str(c["contestName"]),
                        rank=int(c["rank"]),  # type: ignore[call-overload]
                        date=datetime.datetime.fromtimestamp(
                            int(c["ratingUpdateTimeSeconds"]),  # type: ignore[call-overload]
                            tz=datetime.UTC,
                        ).date(),
                        rating_after=int(c["newRating"]),  # type: ignore[call-overload]
                    )
                )
        except (httpx.HTTPError, LookupError, KeyError):
            pass  # rating history missing is a partial gap, not a failed gather

        time.sleep(CF_MIN_INTERVAL)
        try:
            subs = _cf_get(client, "user.status", handle=handle, **{"from": "1", "count": "10000"})
            accepted = {
                (s["problem"]["contestId"], s["problem"]["index"])  # type: ignore[index]
                for s in subs
                if s.get("verdict") == "OK"
            }
            solved = len(accepted)
        except (httpx.HTTPError, LookupError, KeyError):
            pass

    return PlatformEvidence(
        platform=Platform.CODEFORCES,
        handle=str(info["handle"]),
        found=True,
        current_rating=int(info["rating"]) if info.get("rating") is not None else None,  # type: ignore[call-overload]
        max_rating=int(info["maxRating"]) if info.get("maxRating") is not None else None,  # type: ignore[call-overload]
        rank_title=str(info["rank"]) if info.get("rank") else None,
        problems_solved=solved,
        contests=contests,
    )


def probe(url: str, *, timeout: float = 15.0, attempts: int = 2) -> DeploymentEvidence:
    """An HTTP GET, tried twice before it gives up.

    A status code is an ANSWER and is recorded as evidence: the host said something,
    and W1 reads what it said. No answer at all — a timeout, a refused connection, a
    DNS failure — is not evidence about the deployment. It is equally a blip on this
    machine's network, so it comes back with `status_code=None` and `gather` opens a
    transient gap for it rather than letting W1 call the site dead.

    Identifies itself, as the Codeforces client does. Pretending to be a browser to
    get past bot protection would be evasion; a refusal is reported as a refusal.
    """
    now = datetime.datetime.now(datetime.UTC)
    for attempt in range(attempts):
        try:
            response = httpx.get(
                url,
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
            return DeploymentEvidence(
                url=url,
                reachable=response.status_code < 400,
                status_code=response.status_code,
                checked_at=now,
            )
        except httpx.HTTPError:
            if attempt + 1 < attempts:
                time.sleep(PROBE_RETRY_SECONDS)
    return DeploymentEvidence(url=url, reachable=False, status_code=None, checked_at=now)


@dataclass(frozen=True)
class Account:
    """The GitHub account a CV names, and how each linked repository relates to it.

    Naming is not owning. Nothing here says the account is the candidate's — that
    needs the candidate to prove control (an OAuth grant, later), and G3 says so on
    every report until then. What this settles is narrower: WHICH account the CV's
    GitHub claims are about, so each repository can be checked against it.
    """

    login: str | None  # None: no account named, or no honest way to pick one
    own: list[str] = field(default_factory=list)  # repository names under that account
    elsewhere: list[tuple[str, str]] = field(default_factory=list)  # (owner, name), others'
    undecided: list[str] = field(default_factory=list)  # owners tied, when that is why

    @property
    def ambiguous(self) -> bool:
        return self.login is None and bool(self.undecided)


def github_account(graph: ClaimGraph) -> Account:
    """The account the CV's GitHub claims are about.

    Version 1 took `sorted(owners)[0]`. A CV linking its own `ar009/cf-connect` and
    an open-source `apache/kafka` then had Apache investigated: every named repository
    fetched under `apache`, cf-connect reported missing, decisively, and G8 and G9
    reading a foundation's account as a person's.

    A username reaches a CV two ways, and both count:

    1. STATED — "GitHub: ar009", a profile link. The CV saying which account is
       the strongest signal it holds, so a stated handle wins.
    2. Inside a repository URL. With no stated handle, the owner of the linked
       repositories is the account; with several owners, the one most of them sit
       under. A tie decides nothing, and nothing is guessed.

    Repositories under any other owner are not set aside. They are checked as what
    they are — the named account's possible contributions to someone else's code.
    """
    casing: dict[str, str] = {}  # lowercased login -> the document's own casing
    linked: dict[str, list[str]] = {}  # lowercased owner -> repository names, as linked
    for c in graph.claims:
        for a in c.artefacts:
            if a.type is not ArtefactType.REPO or not a.owner:
                continue
            key = a.owner.lower()
            casing.setdefault(key, a.owner)
            name = a.url.rstrip("/").split("/")[-1]
            if name not in linked.setdefault(key, []):
                linked[key].append(name)

    stated: list[str] = []
    for c in graph.claims:
        if c.kind is not ClaimKind.PROFILE or (c.platform or "").lower() != "github":
            continue
        if not c.handle:
            continue
        key = c.handle.lower()
        # A handle sitting inside one of its own repository URLs was read off that URL
        # — by the pre-pass, or by a model copying it. It is not a statement of which
        # account the CV is about, and an open-source link must not become one.
        if f"github.com/{key}/" in c.provenance.verbatim.lower():
            continue
        casing.setdefault(key, c.handle)
        if key not in stated:
            stated.append(key)

    candidates = stated or list(linked)
    if not candidates:
        return Account(login=None)
    ranked = sorted(candidates, key=lambda o: (-len(linked.get(o, [])), o))
    top = len(linked.get(ranked[0], []))
    if len(ranked) > 1 and len(linked.get(ranked[1], [])) == top:
        tied = [o for o in ranked if len(linked.get(o, [])) == top]
        return Account(login=None, undecided=[casing[o] for o in tied])

    chosen = ranked[0]
    return Account(
        login=casing[chosen],
        own=linked.get(chosen, []),
        elsewhere=[
            (casing[owner], name)
            for owner, names in linked.items()
            if owner != chosen
            for name in names
        ],
    )


def gather(graph: ClaimGraph, *, bundle_id: str = "eb_001") -> EvidenceBundle:
    """Everything the CV named, or a typed gap saying why not."""
    began = time.monotonic()
    from cvv.extract import platform_handles  # local import: gather is imported by tests

    platforms: list[PlatformEvidence] = []
    gaps: list[Gap] = []

    handles = platform_handles(graph)
    if Platform.CODEFORCES in handles:
        result = gather_codeforces(handles[Platform.CODEFORCES])
        (gaps if isinstance(result, Gap) else platforms).append(result)  # type: ignore[arg-type]
    else:
        gaps.append(
            Gap(
                source="codeforces",
                reason=GapReason.NO_HANDLE_IN_CV,
                detail="No Codeforces handle found in the document.",
            )
        )

    if Platform.LEETCODE in handles:
        result = gather_leetcode(handles[Platform.LEETCODE])
        (gaps if isinstance(result, Gap) else platforms).append(result)  # type: ignore[arg-type]

    if Platform.CODECHEF in handles:
        gaps.append(
            Gap(
                source=Platform.CODECHEF.value,
                reason=GapReason.NOT_SUPPLIED,
                detail=f"Handle {handles[Platform.CODECHEF]!r} was found, but CodeChef "
                "publishes no API — a scraper is the only route and is deliberately "
                "not built yet.",
            )
        )

    urls = sorted(
        {a.url for c in graph.claims for a in c.artefacts if a.type.value == "deployment"}
    )
    deployments = [probe(u) for u in urls]
    if silent := [d for d in deployments if d.status_code is None]:
        gaps.append(
            Gap(
                source="deployments",
                # Transient on purpose: it marks the report completed_degraded,
                # because re-running from a better network may settle it.
                reason=GapReason.UNREACHABLE,
                detail=f"{len(silent)} claimed live URL(s) gave no response to this "
                "machine at all — a timeout or a refused connection. That can be "
                "either side's network, so nothing is concluded; re-running may "
                "settle it.",
            )
        )

    github = None
    account = github_account(graph)
    if account.login:
        gh = gather_github(account.login, account.own, elsewhere=account.elsewhere)
        if isinstance(gh, Gap):
            gaps.append(gh)
        else:
            github = gh
    elif account.ambiguous:
        gaps.append(
            Gap(
                source="github",
                reason=GapReason.NOT_SUPPLIED,
                detail=f"The CV links repositories under {len(account.undecided)} "
                f"accounts equally ({', '.join(account.undecided)}) and states no "
                "GitHub username, so which account its GitHub claims are about cannot "
                "be decided. Checking the wrong one would report a stranger's account.",
            )
        )
    else:
        gaps.append(
            Gap(
                source="github",
                reason=GapReason.NO_HANDLE_IN_CV,
                detail="No GitHub username or repository URL found in the document.",
            )
        )

    log.info(
        "gather.done",
        bundle_id=bundle_id,
        platforms=[p.platform.value for p in platforms],
        repos=len(github.repos) if github else 0,
        deployments=len(deployments),
        # The REASONS, never the details — a gap detail can quote a URL or a handle.
        gaps={gap.source: gap.reason.value for gap in gaps},
        seconds=round(time.monotonic() - began, 1),
    )
    return EvidenceBundle(
        bundle_id=bundle_id,
        graph_id=graph.graph_id,
        github=github,
        platforms=platforms,
        deployments=deployments,
        gathered_at=datetime.datetime.now(datetime.UTC),
        gaps=gaps,
    )
