"""The GitHub connector — one source, eleven checks.

**Server-side timestamps only.** `git commit --date=` and `GIT_COMMITTER_DATE` both set
dates to anything the author likes, and both live inside the repository. Only GitHub's
own record of when something happened is trustworthy: `created_at` and `pushed_at`.
Nothing here reads a commit's date, and `first_commit` stays null unless a server-side
bound supplies it.

Two fetch depths. The repositories the CV named are fetched deeply — metadata,
language bytes, dependency manifests, tree. The whole account is fetched shallowly in
one listing. The second is what stops the system judging a candidate on what they
happened to write down: a CV cannot list everything, and Python used in a repository
nobody mentioned still corroborates a Python claim.
"""

from __future__ import annotations

import base64
import datetime
import json
import re
from typing import Any

import httpx

from cvv import cache
from cvv.config import settings
from cvv.models import Gap, GapReason, GitHubEvidence, Ownership, RepoEvidence

API = "https://api.github.com"
SOURCE = "github"

# Dependency manifests, and how to pull framework names out of each.
MANIFESTS = ("package.json", "requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml")

# Files that carry no work. Everything else counts as substance, however small —
# G7 asks whether there is anything here but a README, not whether the file count is
# low. A two-file Python program is a program.
BOILERPLATE = frozenset(
    {
        "README.md", "README", "README.rst", "README.txt",
        "LICENSE", "LICENSE.md", "LICENCE", "COPYING",
        ".gitignore", ".gitattributes", "CNAME",
    }
)


class RateLimited(Exception):  # noqa: N818 - a typed gap reason, not an error
    """The API said no. Becomes a Gap; gathering continues."""


def _get(client: httpx.Client, path: str) -> Any | None:
    """One request, cached. None means 404 — an absence, not a failure."""
    if (hit := cache.get(SOURCE, path)) is not None:
        return hit if hit != {"__absent__": True} else None

    response = client.get(f"{API}{path}", timeout=30.0)
    if response.status_code == 404:
        cache.put(SOURCE, path, {"__absent__": True})
        return None
    if response.status_code in (403, 429):
        remaining = response.headers.get("x-ratelimit-remaining")
        raise RateLimited(
            f"GitHub returned {response.status_code}"
            + (f" with {remaining} requests remaining" if remaining else "")
            + (". Set CVV_GITHUB_TOKEN — unauthenticated access allows 60 an hour."
               if not settings.github_token else ".")
        )
    response.raise_for_status()
    body = response.json()
    cache.put(SOURCE, path, body)
    return body


def _client() -> httpx.Client:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cvv/0.1 (CV verification research)",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return httpx.Client(headers=headers, follow_redirects=True)


def _as_date(value: str | None) -> datetime.date | None:
    """GitHub returns `2025-03-09T14:22:01Z`; the contract wants a date.

    Truncating rather than parsing loosely is deliberate — a timezone-shifted
    datetime silently moving a repository's creation across a day boundary is exactly
    the kind of quiet error that makes a G5 finding wrong.
    """
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _frameworks(client: httpx.Client, owner: str, repo: str, files: set[str]) -> list[str]:
    """Parsed from dependency manifests.

    The languages endpoint gives LANGUAGES, not frameworks: a Next.js application
    reports as TypeScript. Any rule comparing a claimed stack against `languages`
    alone reports a contradiction on every React project, which is why this exists.
    """
    found: set[str] = set()

    if "package.json" in files:
        raw = _get(client, f"/repos/{owner}/{repo}/contents/package.json")
        if isinstance(raw, dict) and raw.get("content"):
            try:
                pkg = json.loads(base64.b64decode(raw["content"]).decode("utf-8", "replace"))
            except (ValueError, json.JSONDecodeError):
                pkg = {}
            for section in ("dependencies", "devDependencies"):
                found.update(k.lower() for k in (pkg.get(section) or {}))

    if "requirements.txt" in files:
        raw = _get(client, f"/repos/{owner}/{repo}/contents/requirements.txt")
        if isinstance(raw, dict) and raw.get("content"):
            text = base64.b64decode(raw["content"]).decode("utf-8", "replace")
            for line in text.splitlines():
                if name := re.match(r"^\s*([A-Za-z0-9_.-]+)", line):
                    found.add(name.group(1).lower())

    return sorted(found)


def _repo_evidence(
    client: httpx.Client, owner: str, name: str, *, deep: bool
) -> RepoEvidence:
    data = _get(client, f"/repos/{owner}/{name}")
    if data is None:
        return RepoEvidence(name=name, exists=False)

    evidence: dict[str, Any] = {
        "name": data.get("name", name),
        "exists": True,
        "is_fork": data.get("fork"),
        "owner_matches": (data.get("owner") or {}).get("login", "").lower() == owner.lower(),
        # Both server-side. Never a commit date.
        "created_at": _as_date(data.get("created_at")),
        "last_commit": _as_date(data.get("pushed_at")),
        # No trustworthy server-side first-commit timestamp exists, so this stays
        # null and the dependent rules open a gap rather than guessing.
        "first_commit": None,
        "size_kb": data.get("size"),
    }
    if not deep:
        primary = data.get("language")
        evidence["languages"] = {primary: 0} if primary else {}
        return RepoEvidence(**evidence)

    languages = _get(client, f"/repos/{owner}/{name}/languages")
    evidence["languages"] = languages if isinstance(languages, dict) else {}

    branch = data.get("default_branch", "HEAD")
    tree = _get(client, f"/repos/{owner}/{name}/git/trees/{branch}?recursive=1")
    files = {
        entry["path"].split("/")[-1]
        for entry in (tree or {}).get("tree", [])
        if entry.get("type") == "blob"
    }
    # "Is there anything here but a README" — NOT "are there few files". Counting
    # files marked a real 11 KB Python chat application as readme-only because it
    # lives in two files, which would have produced a false G7 finding. A small
    # program is not an empty repository.
    evidence["is_readme_only"] = not any(
        path.split("/")[-1] not in BOILERPLATE and not path.startswith(".")
        for entry in (tree or {}).get("tree", [])
        if entry.get("type") == "blob"
        for path in [entry["path"]]
    )
    evidence["frameworks"] = _frameworks(client, owner, name, files & set(MANIFESTS))

    return RepoEvidence(**evidence)


def _first_commit_by_language(repos: list[RepoEvidence]) -> dict[str, datetime.date]:
    """A LOWER BOUND ON EVIDENCE, not when the person first wrote the language.

    GitHub exposes no server-side first-commit timestamp: the contributions calendar
    has dates but no languages, and the commits endpoint has attacker-controlled
    dates. The only defensible derivation is the earliest repository creation among
    repositories using the language, and `repo.created_at` is server-side.
    """
    earliest: dict[str, datetime.date] = {}
    for repo in repos:
        if repo.created_at is None:
            continue
        for language in repo.languages:
            if language and (language not in earliest or repo.created_at < earliest[language]):
                earliest[language] = repo.created_at
    return earliest


def gather_github(owner: str, named_repos: list[str]) -> GitHubEvidence | Gap:
    """The account, the repositories it names, and the rest of the account shallowly."""
    with _client() as client:
        try:
            user = _get(client, f"/users/{owner}")
            if user is None:
                return Gap(
                    source=SOURCE,
                    reason=GapReason.NOT_FOUND,
                    detail=f"No GitHub account exists at github.com/{owner}.",
                )

            listing = _get(client, f"/users/{owner}/repos?per_page=100&type=owner&sort=created")
            public = [
                RepoEvidence(
                    name=r["name"],
                    exists=True,
                    is_fork=r.get("fork"),
                    owner_matches=True,
                    created_at=_as_date(r.get("created_at")),
                    last_commit=_as_date(r.get("pushed_at")),
                    first_commit=None,
                    size_kb=r.get("size"),
                    languages={r["language"]: 0} if r.get("language") else {},
                )
                for r in (listing or [])
            ]

            named = [
                _repo_evidence(client, owner, name, deep=True)
                for name in dict.fromkeys(named_repos)
            ]

        except RateLimited as limit:
            return Gap(source=SOURCE, reason=GapReason.RATE_LIMITED, detail=str(limit))
        except httpx.HTTPError as exc:
            return Gap(source=SOURCE, reason=GapReason.UNREACHABLE, detail=str(exc))

    return GitHubEvidence(
        handle=user.get("login", owner),
        # The handle came off a repository URL printed on the CV. Nobody proved they
        # control the account, so corroborating evidence from it is capped — and
        # contradicting evidence is not, because nobody lists a handle that
        # undermines them.
        ownership=Ownership.CLAIMED_UNVERIFIED,
        account_created=_as_date(user.get("created_at")),
        repos=named,
        public_repos=public,
        # None would mean NOT GATHERED. 0 means an account with no public
        # repositories, which is a finding. Never conflate them.
        public_repo_count=user.get("public_repos", len(public)),
        org_memberships=[],
        first_commit_by_language=_first_commit_by_language(public + named),
    )
