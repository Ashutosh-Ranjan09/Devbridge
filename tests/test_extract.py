"""The deterministic half of extraction. No model, no network.

Everything here runs on the Python side of the model boundary: what the document
says, read back from the document. The model's own output is exercised by the live
spike, not by these.
"""

from __future__ import annotations

from cvv.extract import _years_on, scope_technologies
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


class TestYearsOnALine:
    """Stated experience is READ off the line, never asked for — one fewer field for
    a small model to invent, and it comes with its span for free."""

    def test_reads_a_single_figure(self) -> None:
        assert _years_on("Python (5 years) | Rust") == 5.0
        assert _years_on("8+ yrs of C++") == 8.0
        assert _years_on("Java - 2.5 years") == 2.5

    def test_two_figures_on_one_line_drop_the_field(self) -> None:
        """The claim is per LINE and the figures are per technology, so nothing here
        can assign them. G9 then abstains, which beats attaching 5 to the wrong one."""
        assert _years_on("Python (5 years) | Go (2 years)") is None

    def test_the_same_figure_twice_is_still_one_answer(self) -> None:
        assert _years_on("Python 3 years, Go 3 years") == 3.0

    def test_a_line_stating_nothing(self) -> None:
        assert _years_on("Proficient - C | C++ Intermediate - Python") is None
        assert _years_on("Graduated 2026, 4 sems") is None
