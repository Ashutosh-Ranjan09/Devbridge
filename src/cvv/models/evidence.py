"""What the outside world returned — the EvidenceBundle.

Produced by gather, consumed by rules. A bundle carrying nothing but gaps is the
document-only path working correctly, not a failure.
"""

from __future__ import annotations

import datetime

from pydantic import Field

from cvv.models.claims import Frozen, Id, Model, Url
from cvv.models.enums import GapReason, Ownership, Platform, SourceQuality


class ContestResult(Model):
    name: str
    rank: int = Field(ge=1)
    date: datetime.date | None = None
    rating_after: int | None = None


class PlatformEvidence(Model):
    """A competitive-programming profile.

    `platform` is the closed enum here, while Claim.platform stays a plain string — a
    claim may name `github`, which is not a contest platform.
    """

    platform: Platform
    handle: str
    found: bool
    current_rating: int | None = None
    max_rating: int | None = None
    rank_title: str | None = None
    problems_solved: int | None = Field(default=None, ge=0)
    contests: list[ContestResult] = Field(default_factory=list)
    source_quality: SourceQuality = SourceQuality.OFFICIAL_API


class RepoEvidence(Model):
    """Every date here is server-side or null.

    `first_commit` in particular: GitHub exposes no trustworthy server-side
    first-commit timestamp, so it stays null unless a contributions-calendar bound
    supplies one. A date from a clone or the REST commits endpoint is forgeable —
    `git commit --date=` sets it to anything.
    """

    name: str
    exists: bool
    is_fork: bool | None = None
    owner_matches: bool | None = None
    created_at: datetime.date | None = None  # repo.created_at — trustworthy
    first_commit: datetime.date | None = None  # null unless server-side evidence bounds it
    last_commit: datetime.date | None = None  # from pushed_at, not from a commit object
    commit_count: int | None = Field(default=None, ge=0)
    size_kb: int | None = Field(default=None, ge=0)
    is_readme_only: bool | None = None
    # Bytes per language. Gives LANGUAGES, not frameworks: React and Next.js both
    # appear as TypeScript. Framework detection parses dependency manifests instead.
    languages: dict[str, int] = Field(default_factory=dict)
    frameworks: list[str] = Field(default_factory=list)


class GitHubEvidence(Model):
    """Two depths. `repos` are the ones the CV named, fetched deeply. `public_repos`
    is the whole account, shallow — one query, metadata and languages only.

    The second list is what stops the system judging a candidate on what they happened
    to write down. A CV cannot list everything.
    """

    handle: str
    ownership: Ownership
    account_created: datetime.date | None = None
    repos: list[RepoEvidence] = Field(default_factory=list)
    public_repos: list[RepoEvidence] = Field(default_factory=list)
    # None means NOT GATHERED, which is a gap. 0 means an account with no public
    # repositories, which is a finding. Never conflate them.
    public_repo_count: int | None = Field(default=None, ge=0)
    org_memberships: list[str] = Field(default_factory=list)
    # A LOWER BOUND ON EVIDENCE, not when the person first wrote the language. The
    # only defensible derivation is min(repo.created_at) over repos using it.
    first_commit_by_language: dict[str, datetime.date] = Field(default_factory=dict)


class DeploymentEvidence(Model):
    url: Url
    reachable: bool
    status_code: int | None = None
    checked_at: datetime.datetime | None = None


class Gap(Model):
    """Why a source could not be consulted.

    `source` is a free string — it names connectors not built yet and systems that are
    not ours. `reason` is closed, because that is what a rule reads when it abstains.
    """

    source: str
    reason: GapReason
    detail: str | None = None


class EvidenceBundle(Frozen):
    bundle_id: Id
    graph_id: Id
    github: GitHubEvidence | None = None
    platforms: list[PlatformEvidence] = Field(default_factory=list)
    deployments: list[DeploymentEvidence] = Field(default_factory=list)
    gathered_at: datetime.datetime
    gaps: list[Gap] = Field(default_factory=list)
