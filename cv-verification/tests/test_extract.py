"""The deterministic half of extraction. No model, no network.

Everything here runs on the Python side of the model boundary: what the document
says, read back from the document. The model's own output is exercised by the live
spike, not by these.
"""

from __future__ import annotations

from cvv.extract import _one_year, group_handles, scope_technologies
from cvv.ingest import Document, normalise
from cvv.models import ClaimKind, IngestMethod
from tests.cvdata import make_claim

PROJECTS = (
    "PROJECTS\n"
    "Automatic Timetable Management Application [Mar '25 - Apr '25]\n"
    "GitHub Link: https://github.com/x/ATMA-Final\n"
    "• Developed ATMA, a full-stack React/Next.js application with MongoDB backend\n"
    "CF-Connect | Self Project [May '25 - Jun '25]\n"
    "• Built with Tailwind CSS and Recharts over the Codeforces API\n"
    "SKILLS AND EXPERTISE\n"
    "• Programming Languages : Rust | Haskell | Python (5 years)\n"
)


def document(raw: str) -> Document:
    text, imap = normalise(raw)
    return Document(
        document_id="doc_test",
        sha256="0" * 64,
        text=text,
        index_map=imap,
        raw=raw,
        pages=1,
        ingest_method=IngestMethod.PDF_TEXT,
    )


class TestScopeTechnologies:
    """Guardrail 7 for a project's stack.

    A project's technologies live in its bullets rather than in the title the model
    quoted, so the region that must contain them is the project BLOCK — this
    project's span up to the next one's. Without that boundary the skills section at
    the bottom of the CV corroborates a stack no project ever claimed.
    """

    def graph_claims(self, first: list[str], second: list[str]) -> list[object]:
        doc = document(PROJECTS)
        return [
            make_claim(
                "Automatic Timetable Management Application", doc.text,
                claim_id="cp1", kind=ClaimKind.PROJECT, skill_refs=first,
            ),
            make_claim(
                "CF-Connect", doc.text,
                claim_id="cp2", kind=ClaimKind.PROJECT, skill_refs=second,
            ),
        ]

    def test_keeps_what_the_project_block_actually_names(self) -> None:
        doc = document(PROJECTS)
        claims = self.graph_claims(["React", "Next.js", "MongoDB"], ["Tailwind CSS"])
        windows = {"cp1": (0, len(doc.text)), "cp2": (0, len(doc.text))}
        out = scope_technologies(claims, windows, doc)  # type: ignore[arg-type]
        assert out[0].skill_refs == ["React", "Next.js", "MongoDB"]
        assert out[1].skill_refs == ["Tailwind CSS"]

    def test_drops_a_technology_that_belongs_to_the_next_project(self) -> None:
        doc = document(PROJECTS)
        claims = self.graph_claims(["React", "Recharts"], ["Tailwind CSS"])
        windows = {"cp1": (0, len(doc.text)), "cp2": (0, len(doc.text))}
        out = scope_technologies(claims, windows, doc)  # type: ignore[arg-type]
        assert out[0].skill_refs == ["React"], "Recharts belongs to CF-Connect"

    def test_the_skills_section_never_corroborates_a_project(self) -> None:
        """The last project runs to the end of ITS SECTION, not the end of the
        document — otherwise the skills list below vouches for every project."""
        doc = document(PROJECTS)
        section_end = doc.text.index("SKILLS AND EXPERTISE")
        claims = self.graph_claims(["React"], ["Tailwind CSS", "Rust", "Haskell"])
        windows = {"cp1": (0, section_end), "cp2": (0, section_end)}
        out = scope_technologies(claims, windows, doc)  # type: ignore[arg-type]
        assert out[1].skill_refs == ["Tailwind CSS"]

    def test_a_document_with_no_projects_is_returned_unchanged(self) -> None:
        doc = document(PROJECTS)
        claims = [make_claim("CF-Connect", doc.text, claim_id="cs1", kind=ClaimKind.SKILL)]
        assert scope_technologies(claims, {}, doc) is claims  # type: ignore[arg-type]


class TestYearsPerLine:
    """The model answers per TECHNOLOGY; the claim is per LINE.

    This replaced a regex for `N years`, which matched that phrasing and no other —
    not "8 yrs", not "since 2016", not a line in any other language.
    """

    def test_one_figure_becomes_the_lines_tenure(self) -> None:
        assert _one_year({5.0}) == 5.0

    def test_the_same_figure_from_several_technologies_is_still_one_answer(self) -> None:
        assert _one_year({3.0}) == 3.0

    def test_two_figures_on_one_line_drop_the_field(self) -> None:
        """"Python (5 years) | Go (2 years)" offers two numbers with no way to assign
        them. G9 then abstains, which beats attaching 5 to the wrong language."""
        assert _one_year({5.0, 2.0}) is None

    def test_a_line_stating_nothing(self) -> None:
        assert _one_year(None) is None
        assert _one_year(set()) is None


HANDLE_DOC = (
    "AWARDS AND ACHIEVEMENTS\n"
    "\u2022 Achieved a peak Codeforces rating of 1495 (handle: AR009)\n"
    "\u2022 Reached a peak CodeChef rating of 1733 (handle: ar009)\n"
)


class TestHandlesAreLocatedNotQuoted:
    """The handles pass returns no `verbatim`, for the reason the skills pass returns
    none: asked for both, the model COMPOSES one. It returned "Codeforces: AR009"
    for a document that says "(handle: AR009)" — a phrase not in the CV — and
    grounding dropped it along with ten other proposals.
    """

    def proposed(self, platform: str, handle: str) -> object:
        from cvv.extract import ProposedClaim
        from cvv.models import ClaimKind

        return ProposedClaim(kind=ClaimKind.PROFILE, platform=platform, handle=handle)

    def test_the_documents_casing_wins(self) -> None:
        """Guardrail 1. A model normalises tokens — it returns `ar-009` for `AR009`,
        the API 404s, and the report says a real account does not exist."""
        doc = document(HANDLE_DOC)
        out = group_handles([self.proposed("codeforces", "ar009")], doc, (0, len(doc.text)))
        assert out[0].handle == "AR009"

    def test_the_handle_is_found_on_a_line_naming_its_own_platform(self) -> None:
        """Guardrail 7 at the token level. This CV carries `AR009` on its Codeforces
        line and `ar009` on its CodeChef line. A window-wide search takes the first
        textual match, so the moment the model miscased one, BOTH claims got the
        Codeforces line — the pairing silently wrong while every field was real."""
        doc = document(HANDLE_DOC)
        out = group_handles(
            [self.proposed("codeforces", "ar009"), self.proposed("codechef", "AR009")],
            doc,
            (0, len(doc.text)),
        )
        by_platform = {p.platform: (p.handle, p.verbatim) for p in out}
        assert by_platform["codeforces"][0] == "AR009"
        assert "Codeforces" in by_platform["codeforces"][1]
        assert by_platform["codechef"][0] == "ar009"
        assert "CodeChef" in by_platform["codechef"][1]

    def test_a_handle_on_no_line_naming_its_platform_is_dropped(self) -> None:
        """Rather than guessing which account it belongs to."""
        doc = document(HANDLE_DOC)
        assert group_handles(
            [self.proposed("leetcode", "AR009")], doc, (0, len(doc.text))
        ) == []

    def test_the_line_becomes_the_provenance(self) -> None:
        doc = document(HANDLE_DOC)
        out = group_handles([self.proposed("codeforces", "AR009")], doc, (0, len(doc.text)))
        assert "peak Codeforces rating of 1495" in out[0].verbatim

    def test_a_handle_outside_the_window_is_dropped(self) -> None:
        """Guardrail 7, applied here: the pass's window is a boundary, not a hint."""
        doc = document(HANDLE_DOC)
        heading_only = (0, doc.text.index("Achieved"))
        assert group_handles([self.proposed("codeforces", "AR009")], doc, heading_only) == []

    def test_a_handle_the_document_does_not_contain_is_dropped(self) -> None:
        doc = document(HANDLE_DOC)
        assert group_handles([self.proposed("codeforces", "nobody")], doc, (0, len(doc.text))) == []

    def test_one_claim_per_platform_and_handle(self) -> None:
        doc = document(HANDLE_DOC)
        out = group_handles(
            [self.proposed("codeforces", "AR009")] * 3, doc, (0, len(doc.text))
        )
        assert len(out) == 1


ROUTED = (
    "PRIYA NARAYANAN\n"
    "EDUCATION\nB.Tech in Computer Science, 2021 - 2025\n"
    "PROJECTS\nLedgerline, a double-entry ledger\n"
    "COURSEWORK INFORMATION\nComputer Science, Mathematics, Others\n"
)


def section_list(raw: str) -> list:
    from cvv.ingest import sections

    return sections(document(raw))


class TestSectionRuns:
    """`sections=("ACHIEVEMENT", "AWARD")` is a hardcoded convention in exactly the
    way a regex is. A second CV headed its competitive-programming section
    "COMPETITIVE PROGRAMMING", matched nothing, and the achievements pass fell back
    to the whole document — losing two of three ratings and the only contest rank,
    silently, on a CV that had done nothing wrong.
    """

    def test_adjacent_sections_become_one_window(self) -> None:
        from cvv.extract import _runs
        from cvv.ingest import Section

        a = Section(heading="A", start=0, end=100)
        b = Section(heading="B", start=100, end=250)
        assert _runs([a, b]) == [(0, 250)]

    def test_separated_sections_stay_separate(self) -> None:
        """The real CV routes both "EDUCATION" and "COURSEWORK INFORMATION" to
        education, correctly, and they sit at opposite ends of the page. Spanning
        them turned a 180-character window into a 4,252-character one holding every
        project and skill on the CV — the wide-window failure, arrived at by being
        RIGHT about the headings."""
        from cvv.extract import _runs
        from cvv.ingest import Section

        a = Section(heading="EDUCATION", start=0, end=180)
        b = Section(heading="COURSEWORK", start=3800, end=4300)
        assert _runs([a, b]) == [(0, 180), (3800, 4300)]

    def test_choosing_between_them_was_the_next_wrong_answer(self) -> None:
        """Longest-first picked COURSEWORK over EDUCATION and would have lost every
        degree. There is no need to choose — the pass runs once per run."""
        from cvv.extract import _runs
        from cvv.ingest import Section

        small = Section(heading="EDUCATION", start=0, end=180)
        large = Section(heading="COURSEWORK", start=3800, end=4300)
        assert _runs([large, small])[0] == (0, 180), "document order, not size"

    def test_order_is_normalised(self) -> None:
        from cvv.extract import _runs
        from cvv.ingest import Section

        a = Section(heading="A", start=100, end=200)
        b = Section(heading="B", start=0, end=100)
        assert _runs([a, b]) == [(0, 200)]
