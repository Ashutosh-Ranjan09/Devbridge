"""Every enumeration in the contract.

StrEnum throughout, so a value is never a bare string literal in logic and a typo is
an AttributeError rather than a silently-false comparison.
"""

from __future__ import annotations

from enum import StrEnum


class ClaimKind(StrEnum):
    EMPLOYMENT = "employment"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    PROJECT = "project"
    SKILL = "skill"
    PROFILE = "profile"  # carries the handle; 18 checks depend on it existing
    ACHIEVEMENT = "achievement"  # carries the directly checkable numeric
    IDENTIFIER = "identifier"  # the roll number -> D9
    DECLARATION_MARKER = "declaration_marker"  # the institution's own disclaimer


class Precision(StrEnum):
    """How much of a date the document actually committed to."""

    EXACT = "exact"
    MONTH = "month"
    YEAR = "year"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    INTERNSHIP = "internship"
    FREELANCE = "freelance"
    UNSTATED = "unstated"


class Proficiency(StrEnum):
    """Ordinal, not numeric. "Proficient" is not 0.7 of anything."""

    FAMILIAR = "familiar"
    INTERMEDIATE = "intermediate"
    PROFICIENT = "proficient"
    EXPERT = "expert"


class ArtefactType(StrEnum):
    REPO = "repo"
    DEPLOYMENT = "deployment"
    PACKAGE = "package"
    PAPER = "paper"
    OTHER = "other"


class Recovery(StrEnum):
    """How the span was located. EXACT means the verbatim was found character for
    character; FUZZY means it matched above threshold with every numeral verified."""

    EXACT = "exact"
    FUZZY = "fuzzy"


class AssertedBy(StrEnum):
    CANDIDATE = "candidate"
    INSTITUTION = "institution"


class DeclarationEffect(StrEnum):
    INHERIT_UNVERIFIED = "inherit_unverified"


class IngestMethod(StrEnum):
    PDF_TEXT = "pdf_text"
    DOCX = "docx"
    OCR = "ocr"


class Platform(StrEnum):
    CODEFORCES = "codeforces"
    LEETCODE = "leetcode"
    CODECHEF = "codechef"
    ATCODER = "atcoder"
    HACKERRANK = "hackerrank"


class SourceQuality(StrEnum):
    """A scraped number is a weaker fact than an API's, and the model records which."""

    OFFICIAL_API = "official_api"
    SCRAPE = "scrape"


class Ownership(StrEnum):
    """claimed_unverified caps evidence that would RAISE confidence, and never caps
    evidence that lowers it: nobody lists a handle that undermines them."""

    VERIFIED_OAUTH = "verified_oauth"
    VERIFIED_CHALLENGE = "verified_challenge"
    CLAIMED_UNVERIFIED = "claimed_unverified"
    NOT_FOUND = "not_found"


class GapReason(StrEnum):
    """Load-bearing. A check that cannot run abstains WITH one of these attached, and
    it flows into the not_evaluated bucket. Silence would read as a pass."""

    NO_HANDLE_IN_CV = "no_handle_in_cv"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    UNREACHABLE = "unreachable"
    OWNERSHIP_UNVERIFIED = "ownership_unverified"
    NO_CONSENT = "no_consent"
    NOT_SUPPLIED = "not_supplied"


class Tier(StrEnum):
    """Declared on the rule, never chosen per finding. The report bucket derives from
    this mechanically, so a judgement can never be presented as a fact."""

    DECISIVE = "decisive"  # authoritative source + deterministic comparison
    ATTENTION = "attention"  # reliable signal, innocent explanations exist
    EVIDENCE_ONLY = "evidence_only"  # material for a person, no machine conclusion


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RuleStatus(StrEnum):
    FIRED = "fired"
    CLEAN = "clean"
    ABSTAINED = "abstained"  # could not run — always carries a reason
    ERROR = "error"  # raised; isolated so the report still renders
    NOT_APPLICABLE = "not_applicable"  # "no employment claimed" is not an abstention


class Section(StrEnum):
    EMPLOYMENT = "employment"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    SKILLS = "skills"
    PROJECTS = "projects"
    ACHIEVEMENTS = "achievements"


class ReportStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_DEGRADED = "completed_degraded"  # usable but incomplete
    FAILED = "failed"
