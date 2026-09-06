"""The one rule about logging here: never log the CV.

A log line is the easiest place in a codebase for personal data to escape. It is
written to disk, shipped to an aggregator, tailed in a terminal someone is
screen-sharing, and kept long after the verification it described was deleted. The
convention is that events carry identifiers and counts; `scrub` is what holds when
the convention does not.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

from cvv.logs import REDACT, REDACTED, configure, get, scrub


def scrubbed(**event: Any) -> dict[str, Any]:
    return dict(scrub(None, "info", dict(event)))


class TestScrub:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("verbatim", "Achieved a peak Codeforces rating of 1495 (Specialist)"),
            ("handle", "AR009"),
            ("name", "Ashutosh Ranjan"),
            ("email", "someone@example.edu"),
            ("org", "IIT Kharagpur"),
            ("snippet", "23CS10004 B.Tech.(Hons.) in COMPUTER SCIENCE"),
            ("normalised_text", "the whole CV"),
            ("url", "https://github.com/Ashutosh-Ranjan09/ATMA-Final"),
            ("explanation", "The CV claims rank 1106 in Codeforces Round 998"),
        ],
    )
    def test_cv_content_never_survives(self, key: str, value: str) -> None:
        assert scrubbed(**{key: value})[key] == REDACTED

    def test_replaced_not_truncated(self) -> None:
        """A truncated name is still a name."""
        assert REDACTED not in "Ashutosh"
        assert scrubbed(name="Ashutosh Ranjan")["name"] == REDACTED

    def test_case_does_not_get_a_field_past_it(self) -> None:
        assert scrubbed(Verbatim="x", HANDLE="y") == {
            "Verbatim": REDACTED,
            "HANDLE": REDACTED,
        }

    def test_identifiers_and_counts_are_what_survives(self) -> None:
        """The convention the scrubber backs up: log what points AT the data, and how
        much of it there was — never the data."""
        event = scrubbed(
            verification_id="vr_abc123",
            graph_id="cg_def456",
            rule_id="P1",
            claims=19,
            span_failures=2,
            seconds=21.3,
        )
        assert REDACTED not in event.values()
        assert event["verification_id"] == "vr_abc123"
        assert event["claims"] == 19

    def test_the_event_name_itself_is_untouched(self) -> None:
        assert scrubbed(event="verification.completed")["event"] == "verification.completed"

    def test_every_redacted_key_is_lowercase(self) -> None:
        """`scrub` lowercases the key before comparing, so an uppercase entry in the
        set would silently never match."""
        assert all(key == key.lower() for key in REDACT)


class TestConfiguration:
    def test_json_when_the_output_is_not_a_terminal(self, capsys: Any) -> None:
        configure("info", force_json=True)
        get("test").info("thing.happened", verification_id="vr_1", claims=3)
        line = capsys.readouterr().err.strip().splitlines()[-1]
        assert json.loads(line)["verification_id"] == "vr_1"

    def test_the_level_filters(self, capsys: Any) -> None:
        configure("warning", force_json=True)
        log = get("test")
        log.info("quiet")
        log.warning("loud")
        err = capsys.readouterr().err
        assert "quiet" not in err and "loud" in err

    def test_redaction_survives_the_real_pipeline(self, capsys: Any) -> None:
        """Not just the function — the configured processor chain."""
        configure("info", force_json=True)
        get("test").info("claim.dropped", verbatim="peak Codeforces rating of 1495")
        line = capsys.readouterr().err.strip().splitlines()[-1]
        assert "1495" not in line
        assert json.loads(line)["verbatim"] == REDACTED


def test_logs_go_to_stderr_so_json_output_stays_parseable() -> None:
    """`cvv verify --json > report.json` must produce a file that parses. A logger
    writing to stdout would interleave log lines into the report."""
    result = subprocess.run(
        [sys.executable, "-c",
         "from cvv.logs import configure, get; configure('info', force_json=True); "
         "get('t').info('noise'); print('{\"real\": \"output\"}')"],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == {"real": "output"}
    assert "noise" in result.stderr
