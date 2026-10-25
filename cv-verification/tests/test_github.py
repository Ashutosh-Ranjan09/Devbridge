"""The connector's pure functions — what counts as a file a person wrote.

No network. `_authored` decides G7's trigger, and G7 is decisive, so this is the
highest-consequence filename rule in the system: a file wrongly excluded pushes
`authored_files` toward zero, and zero contradicts an honest repository.
"""

from __future__ import annotations

import pytest

from cvv import github as github_module
from cvv.github import _authored, dependencies, gather_github, manifest_paths
from cvv.models import GitHubEvidence


class TestWhatCountsAsAuthored:
    @pytest.mark.parametrize(
        "path",
        [
            "chat.py",
            "src/app/api/user/login/route.js",
            "middleware.js",
            "package.json",  # a person chose these dependencies
            "requirements.txt",
            "Makefile",
            "docs/architecture.md",  # prose, but written
            "src/build/pipeline.py",  # "build" as a source directory, not output
            "vendor/parser.go",  # Go convention, and it is checked-in source
        ],
    )
    def test_written_by_a_person(self, path: str) -> None:
        assert _authored(path)

    @pytest.mark.parametrize(
        "path",
        [
            "README.md",
            "LICENSE",
            ".gitignore",
            ".github/workflows/ci.yml",
            "package-lock.json",
            "yarn.lock",
            "poetry.lock",
            "Cargo.lock",
            "go.sum",
            "node_modules/react/index.js",
            "app/__pycache__/views.cpython-312.pyc",
            "dist/bundle.min.js",
            "dist/bundle.min.js.map",
            "static/styles.min.css",
        ],
    )
    def test_generated_or_boilerplate(self, path: str) -> None:
        assert not _authored(path)

    def test_ambiguous_directories_stay_in(self) -> None:
        """The exclusion list is biased the OPPOSITE way to data/tech-releases.json.
        Over-excluding drives authored_files to zero and invents a decisive finding
        against an honest repository, so build/, out/, target/ and vendor/ — output
        directories in some ecosystems, source directories in others — are not
        excluded. The cost of that caution is a missed finding, which is the
        acceptable error."""
        for path in ("build/main.c", "out/report.tex", "target/notes.md"):
            assert _authored(path), path


class TestTheShapesG7Decides:
    """The four repository shapes, and what G7 concludes from each.

    Rows two and three passed before this rule learned what "generated" means: a
    lock file and a committed minified bundle both counted as substance.
    """

    @pytest.mark.parametrize(
        ("label", "tree", "empty"),
        [
            ("a README and nothing else", ["README.md", "LICENSE", ".gitignore"], True),
            ("a README and a lock file", ["README.md", "package.json", "package-lock.json"], False),
            ("a README and a built bundle", ["README.md", "dist/app.min.js"], True),
            ("a two-file Python program", ["chat.py", "rsa.py"], False),
            ("committed node_modules only", ["README.md", "node_modules/react/index.js"], True),
        ],
    )
    def test_is_readme_only(self, label: str, tree: list[str], empty: bool) -> None:
        assert (not any(_authored(p) for p in tree)) is empty, label

    def test_a_lock_file_is_not_a_project(self) -> None:
        """package-lock.json is fifteen thousand lines nobody wrote. A repository
        holding it and a README is presented as a project and contains none."""
        assert not any(_authored(p) for p in ["README.md", "package-lock.json"])

    def test_package_json_beside_it_is(self) -> None:
        """The manifest is authored — a person chose those dependencies — so a repo
        with a real package.json is never called empty on this rule."""
        assert any(_authored(p) for p in ["README.md", "package.json", "package-lock.json"])


class TestDependencyManifests:
    """What G6 is allowed to compare a claimed stack against.

    Version 1 listed five manifest formats and parsed two, at the repository root
    only. A Django project declaring itself in pyproject.toml, or a MERN app split
    into client/ and server/, then looked like a repository built on nothing — and
    G6 is decisive.
    """

    @pytest.mark.parametrize(
        ("name", "text", "expected"),
        [
            ("package.json", '{"dependencies": {"React": "^18"}, "devDependencies": {"vite": "5"}}',
             {"react", "vite"}),
            ("requirements.txt", "Django==5.0\n# a comment\npsycopg[binary]>=3\n",
             {"django", "psycopg"}),
            ("pyproject.toml",
             '[project]\ndependencies = ["fastapi>=0.110", "uvicorn[standard]"]\n'
             '[project.optional-dependencies]\ndev = ["pytest"]\n',
             {"fastapi", "uvicorn", "pytest"}),
            ("pyproject.toml",
             '[tool.poetry.dependencies]\npython = "^3.12"\nDjango = "^5"\n'
             '[tool.poetry.group.dev.dependencies]\nblack = "*"\n',
             {"django", "black"}),
            ("go.mod",
             "module github.com/me/app\n\ngo 1.22\n\nrequire (\n"
             "\tgithub.com/gin-gonic/gin v1.9.1\n\tgithub.com/redis/go-redis/v9 v9.5.1\n)\n",
             {"github.com/gin-gonic/gin", "gin", "github.com/redis/go-redis/v9", "go-redis"}),
            ("Cargo.toml", '[dependencies]\ntokio = { version = "1" }\n[dev-dependencies]\nproptest = "1"\n',
             {"tokio", "proptest"}),
        ],
        ids=["package.json", "requirements", "pep621", "poetry", "go.mod", "cargo"],
    )
    def test_each_format_declares_its_dependencies(
        self, name: str, text: str, expected: set[str]
    ) -> None:
        assert dependencies(name, text) == expected

    @pytest.mark.parametrize("name", ["package.json", "pyproject.toml", "Cargo.toml"])
    def test_a_malformed_manifest_declares_nothing_and_never_raises(self, name: str) -> None:
        assert dependencies(name, "{{ this is not a manifest") == set()

    def test_manifests_are_found_wherever_they_sit(self) -> None:
        tree = [
            {"type": "blob", "path": "server/package.json"},
            {"type": "blob", "path": "client/package.json"},
            {"type": "blob", "path": "client/node_modules/react/package.json"},
            {"type": "blob", "path": "README.md"},
            {"type": "tree", "path": "client"},
        ]
        assert manifest_paths(tree) == ["client/package.json", "server/package.json"]

    def test_the_root_comes_first_and_the_count_is_capped(self) -> None:
        tree = [{"type": "blob", "path": f"pkg{i}/package.json"} for i in range(9)]
        tree.append({"type": "blob", "path": "pyproject.toml"})
        found = manifest_paths(tree)
        assert found[0] == "pyproject.toml"
        assert len(found) == 4


class TestRepositoriesUnderAnotherOwner:
    """apache/kafka on a CV is a claim to have contributed. The connector asks whether
    the named account has commits there, and keeps the repository out of everything
    that describes the account itself."""

    @pytest.fixture
    def api(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
        responses: dict[str, object] = {
            "/users/ar009": {"login": "ar009", "created_at": "2024-06-29T00:00:00Z",
                             "public_repos": 1},
            "/users/ar009/repos?per_page=100&type=owner&sort=created": [
                {"name": "cf-connect", "fork": False, "created_at": "2025-05-01T00:00:00Z",
                 "language": "TypeScript"},
            ],
            "/users/ar009/orgs": [],
            "/repos/apache/kafka": {"name": "kafka", "fork": False, "owner": {"login": "apache"},
                                    "created_at": "2011-08-15T00:00:00Z", "language": "Java"},
            "/repos/apache/kafka/commits?author=ar009&per_page=100": [{"sha": "a"}, {"sha": "b"}],
            "/repos/apache/flink": {"name": "flink", "fork": False, "owner": {"login": "apache"},
                                    "created_at": "2014-06-01T00:00:00Z", "language": "Java"},
            "/repos/apache/flink/commits?author=ar009&per_page=100": [],
        }
        monkeypatch.setattr(github_module, "_get", lambda client, path: responses.get(path))
        monkeypatch.setattr(github_module, "_contributions", lambda *a, **k: [])
        return responses

    def evidence(self) -> GitHubEvidence:
        gh = gather_github("ar009", [], elsewhere=[("apache", "kafka"), ("apache", "flink")])
        assert isinstance(gh, GitHubEvidence)
        return gh

    def test_the_named_accounts_commits_are_counted(self, api: dict[str, object]) -> None:
        repos = {r.name: r for r in self.evidence().repos}
        assert repos["apache/kafka"].commit_count == 2
        assert repos["apache/kafka"].owner_matches is False
        assert repos["apache/flink"].commit_count == 0, "asked and answered none, not unknown"

    def test_someone_elses_repository_never_dates_the_account(self, api: dict[str, object]) -> None:
        """kafka is Java from 2011. Counting it would say this account has written
        Java since 2011, which is the misattribution this design exists to stop."""
        assert "Java" not in self.evidence().first_commit_by_language
