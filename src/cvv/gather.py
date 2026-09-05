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

import httpx

from cvv.github import gather_github
from cvv.leetcode import gather_leetcode
from cvv.models import (
    ClaimGraph,
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


def probe(url: str, *, timeout: float = 15.0) -> DeploymentEvidence:
    """One HTTP GET. A claimed live product either responds or it does not.

    Unreachable is recorded as evidence, not as a gap: the probe ran and got an
    answer. A gap is for a source we could not consult at all.
    """
    now = datetime.datetime.now(datetime.UTC)
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        return DeploymentEvidence(
            url=url,
            reachable=response.status_code < 400,
            status_code=response.status_code,
            checked_at=now,
        )
    except httpx.HTTPError:
        return DeploymentEvidence(url=url, reachable=False, status_code=None, checked_at=now)


def gather(graph: ClaimGraph, *, bundle_id: str = "eb_001") -> EvidenceBundle:
    """Everything the CV named, or a typed gap saying why not."""
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

    github = None
    owners = {
        a.owner
        for c in graph.claims
        for a in c.artefacts
        if a.type.value == "repo" and a.owner
    }
    named = sorted(
        {
            a.url.rstrip("/").split("/")[-1]
            for c in graph.claims
            for a in c.artefacts
            if a.type.value == "repo"
        }
    )
    if owners:
        # One CV, one account. More than one owner means repositories belonging to
        # different people, which is a claim about collaboration rather than
        # ownership — out of scope for now.
        owner = sorted(owners)[0]
        gh = gather_github(owner, named)
        if isinstance(gh, Gap):
            gaps.append(gh)
        else:
            github = gh
    else:
        gaps.append(
            Gap(
                source="github",
                reason=GapReason.NO_HANDLE_IN_CV,
                detail="No GitHub repository URL found in the document.",
            )
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
