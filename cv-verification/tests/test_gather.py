"""Gathering decisions that need no network: which account, and what a silence means.

`gather` itself makes requests, so the connectors are replaced here. What is under
test is what it DECIDES — which GitHub account the CV's claims are about, which
repositories are checked how, and how a URL that never answered is recorded.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest

from cvv import gather as gather_module
from cvv.extract import _artefact
from cvv.gather import github_account, typed_handles
from cvv.models import ClaimKind, DeploymentEvidence, Gap, GapReason, Handles
from tests.cvdata import CC_RATING, CF_RANK, CF_RATING, DOCUMENT, make_claim, make_graph


def project(verbatim: str, claim_id: str, *urls: str) -> object:
    return make_claim(
        verbatim, DOCUMENT, claim_id=claim_id, kind=ClaimKind.PROJECT, title=claim_id,
        artefacts=[_artefact(u) for u in urls],
    )


def profile(line: str, handle: str, document: str) -> object:
    return make_claim(
        line, document, claim_id="cprofile", kind=ClaimKind.PROFILE, platform="github",
        handle=handle,
    )


class TestWhichAccount:
    """Version 1 took the alphabetically first owner, so a CV linking an Apache
    repository had Apache investigated as the candidate."""

    def test_the_owner_of_most_linked_repositories_is_the_account(self) -> None:
        graph = make_graph(
            [
                project(CF_RANK, "cproj01", "https://github.com/ar009/cf-connect"),
                project(CF_RATING, "cproj02", "https://github.com/ar009/atma"),
                project(CC_RATING, "cproj03", "https://github.com/apache/kafka"),
            ],
            DOCUMENT,
        )
        account = github_account(graph)
        assert account.login == "ar009"
        assert account.own == ["cf-connect", "atma"]
        assert account.elsewhere == [("apache", "kafka")]

    def test_a_stated_username_outranks_a_count(self) -> None:
        """The CV saying which account it is beats arithmetic over links."""
        doc = DOCUMENT + " GitHub: ar009"
        graph = make_graph(
            [
                project(CF_RANK, "cproj01", "https://github.com/ar009/cf-connect"),
                project(CF_RATING, "cproj02", "https://github.com/apache/kafka"),
                project(CC_RATING, "cproj03", "https://github.com/apache/flink"),
                profile("GitHub: ar009", "ar009", doc),
            ],
            doc,
        )
        account = github_account(graph)
        assert account.login == "ar009"
        assert account.elsewhere == [("apache", "kafka"), ("apache", "flink")]

    def test_a_stated_username_needs_no_repository(self) -> None:
        doc = DOCUMENT + " GitHub: ar009"
        account = github_account(make_graph([profile("GitHub: ar009", "ar009", doc)], doc))
        assert account.login == "ar009"
        assert account.own == []

    def test_a_handle_read_off_a_repository_url_is_not_a_statement(self) -> None:
        """The pre-pass emits a profile claim for every repository owner. An
        open-source link must not become the account the CV is about."""
        doc = DOCUMENT + " github.com/apache/kafka"
        graph = make_graph(
            [
                project(CF_RANK, "cproj01", "https://github.com/ar009/cf-connect"),
                project(CF_RATING, "cproj02", "https://github.com/ar009/atma"),
                profile("github.com/apache/kafka", "apache", doc),
            ],
            doc,
        )
        assert github_account(graph).login == "ar009"

    def test_a_tie_decides_nothing(self) -> None:
        graph = make_graph(
            [
                project(CF_RANK, "cproj01", "https://github.com/ar009/cf-connect"),
                project(CF_RATING, "cproj02", "https://github.com/apache/kafka"),
            ],
            DOCUMENT,
        )
        account = github_account(graph)
        assert account.login is None
        assert account.ambiguous
        assert account.undecided == ["apache", "ar009"]

    def test_no_link_and_no_username_is_no_account(self) -> None:
        account = github_account(make_graph([], DOCUMENT))
        assert account.login is None
        assert not account.ambiguous


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str], list[tuple[str, str]]]]:
    """Every connector replaced. Records what GitHub would have been asked."""
    asked: list[tuple[str, list[str], list[tuple[str, str]]]] = []

    def github(owner: str, named: list[str], *, elsewhere: list[tuple[str, str]] | None = None) -> Gap:
        asked.append((owner, named, list(elsewhere or [])))
        return Gap(source="github", reason=GapReason.UNREACHABLE, detail="offline")

    monkeypatch.setattr(gather_module, "gather_github", github)
    monkeypatch.setattr(
        gather_module,
        "gather_codechef",
        lambda handle: Gap(source="codechef", reason=GapReason.UNREACHABLE, detail="offline"),
    )
    monkeypatch.setattr(
        gather_module,
        "probe",
        lambda url: DeploymentEvidence(
            url=url, reachable=False, status_code=None,
            checked_at=datetime.datetime.now(datetime.UTC),
        ),
    )
    return asked


class TestGather:
    def test_the_account_and_every_linked_repository_are_asked_about(
        self, offline: list[tuple[str, list[str], list[tuple[str, str]]]]
    ) -> None:
        graph = make_graph(
            [
                project(CF_RANK, "cproj01", "https://github.com/ar009/cf-connect"),
                project(CF_RATING, "cproj02", "https://github.com/ar009/atma"),
                project(CC_RATING, "cproj03", "https://github.com/apache/kafka"),
            ],
            DOCUMENT,
        )
        gather_module.gather(graph)
        assert offline == [("ar009", ["cf-connect", "atma"], [("apache", "kafka")])]

    def test_a_tie_fetches_nothing_and_says_why(
        self, offline: list[tuple[str, list[str], list[tuple[str, str]]]]
    ) -> None:
        graph = make_graph(
            [
                project(CF_RANK, "cproj01", "https://github.com/ar009/cf-connect"),
                project(CF_RATING, "cproj02", "https://github.com/apache/kafka"),
            ],
            DOCUMENT,
        )
        bundle = gather_module.gather(graph)
        assert offline == []
        assert any("cannot be decided" in (g.detail or "") for g in bundle.gaps)

    def test_a_url_that_never_answered_is_a_transient_gap(
        self, offline: list[tuple[str, list[str], list[tuple[str, str]]]]
    ) -> None:
        """Transient, so the report is completed_degraded: re-running may settle it."""
        graph = make_graph(
            [project(CF_RANK, "cproj01", "https://cf-connect.vercel.app")], DOCUMENT
        )
        bundle = gather_module.gather(graph)
        gap = next(g for g in bundle.gaps if g.source == "deployments")
        assert gap.reason is GapReason.UNREACHABLE
        assert "either side's network" in (gap.detail or "")


class TestTypedHandles:
    """Handles the candidate typed on upload fill in what the CV leaves out. The CV's
    own handle wins: it is what is being checked, and a typed handle that replaced it
    would let a candidate swap in a better account than the one their CV names."""

    @pytest.fixture
    def platforms(
        self, monkeypatch: pytest.MonkeyPatch, offline: list[tuple[str, list[str], list[tuple[str, str]]]]
    ) -> list[tuple[str, str]]:
        asked: list[tuple[str, str]] = []

        def connector(name: str) -> Callable[[str], Gap]:
            def fetch(handle: str) -> Gap:
                asked.append((name, handle))
                return Gap(source=name, reason=GapReason.UNREACHABLE, detail="offline")
            return fetch

        for name in ("codeforces", "leetcode"):
            monkeypatch.setattr(gather_module, f"gather_{name}", connector(name))
        return asked

    def test_a_typed_handle_is_fetched_when_the_cv_names_none(
        self, platforms: list[tuple[str, str]]
    ) -> None:
        graph = make_graph([], DOCUMENT)
        bundle = gather_module.gather(graph, typed=Handles(leetcode="asha_r"))
        assert platforms == [("leetcode", "asha_r")]
        assert typed_handles(graph, Handles(leetcode="asha_r")) == {"leetcode": "asha_r"}
        assert not any(g.reason is GapReason.NO_HANDLE_IN_CV and g.source == "leetcode"
                       for g in bundle.gaps)

    def test_the_cvs_own_handle_wins(self, platforms: list[tuple[str, str]]) -> None:
        doc = DOCUMENT + " Codeforces: ar009"
        cf = make_claim("Codeforces: ar009", doc, claim_id="ccf", kind=ClaimKind.PROFILE,
                        platform="codeforces", handle="ar009")
        graph = make_graph([cf], doc)
        typed = Handles(codeforces="someone_better")
        gather_module.gather(graph, typed=typed)
        assert platforms == [("codeforces", "ar009")]
        assert typed_handles(graph, typed) == {}

    def test_a_typed_github_username_settles_a_tie(
        self, offline: list[tuple[str, list[str], list[tuple[str, str]]]]
    ) -> None:
        graph = make_graph(
            [
                project(CF_RANK, "cproj01", "https://github.com/ar009/cf-connect"),
                project(CF_RATING, "cproj02", "https://github.com/apache/kafka"),
            ],
            DOCUMENT,
        )
        gather_module.gather(graph, typed=Handles(github="ar009"))
        assert offline == [("ar009", ["cf-connect"], [("apache", "kafka")])]

    def test_a_typed_github_username_never_replaces_the_cvs_account(
        self, offline: list[tuple[str, list[str], list[tuple[str, str]]]]
    ) -> None:
        graph = make_graph(
            [
                project(CF_RANK, "cproj01", "https://github.com/ar009/cf-connect"),
                project(CF_RATING, "cproj02", "https://github.com/ar009/atma"),
            ],
            DOCUMENT,
        )
        typed = Handles(github="someone_else")
        gather_module.gather(graph, typed=typed)
        assert [owner for owner, _, _ in offline] == ["ar009"]
        assert typed_handles(graph, typed) == {}

    def test_a_handle_that_is_not_a_username_is_refused(self) -> None:
        """Before it reaches a URL: `/` or `?` in a handle would change what is fetched."""
        with pytest.raises(ValueError):
            Handles(codeforces="ar009/../../admin")
