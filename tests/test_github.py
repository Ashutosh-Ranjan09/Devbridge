"""The connector's pure functions — what counts as a file a person wrote.

No network. `_authored` decides G7's trigger, and G7 is decisive, so this is the
highest-consequence filename rule in the system: a file wrongly excluded pushes
`authored_files` toward zero, and zero contradicts an honest repository.
"""

from __future__ import annotations

import pytest

from cvv.github import _authored


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
