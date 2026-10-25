"""Structured logging, and the one rule that matters here: never log the CV.

Everything this system touches is somebody's personal data — their name, their roll
number, their handles, the text of their CV. A log line is the easiest place in a
codebase for that to escape: it gets written to disk, shipped to an aggregator,
tailed in a terminal someone is screen-sharing, and kept long after the verification
it described was deleted.

So the convention is that log events carry IDENTIFIERS AND COUNTS — a verification id,
a rule id, how many claims, how long — and never content. And because a convention is
not an enforcement mechanism, `scrub` drops the dangerous keys on the way out
whatever a caller passes.

Human-readable on a terminal, JSON when the output is a pipe. That is the standard
structlog arrangement and it needs no configuration to be right in both places.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

# Keys that carry CV content rather than a reference to it. Anything named like this
# is replaced, not truncated: a truncated name is still a name.
REDACT = frozenset(
    {
        "verbatim", "snippet", "text", "normalised_text", "raw", "document_text",
        "handle", "name", "email", "org", "title", "degree", "roll", "explanation",
        "summary", "prose", "claim_text", "url", "document_url",
    }
)
REDACTED = "[redacted]"


def scrub(
    _logger: Any, _method: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Drop CV content from an event, whatever the caller passed.

    Defence in depth rather than the mechanism — the convention is that callers log
    ids and counts. This is here because a convention holds until the one time
    somebody adds `verbatim=claim.provenance.verbatim` to a debug line and ships it.
    """
    for key in list(event):
        if key.lower() in REDACT:
            event[key] = REDACTED
    return event


class _Stderr:
    """Resolves `sys.stderr` at WRITE time, not at configure time.

    `PrintLoggerFactory(file=sys.stderr)` captures the stream object when logging is
    configured. Anything that later REPLACES `sys.stderr` — pytest's capture, a
    supervisor rebinding the handle — leaves the logger writing to a stream that has
    gone, and the failure surfaces somewhere unrelated: a store test three files away
    died on a closed file because a logging test had configured first.
    """

    def write(self, text: str) -> int:
        return sys.stderr.write(text)

    def flush(self) -> None:
        sys.stderr.flush()


def configure(level: str = "info", *, force_json: bool | None = None) -> None:
    """Call once, at the start of a process. Safe to call again."""
    as_json = not sys.stderr.isatty() if force_json is None else force_json

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            scrub,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
            if as_json
            else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=_Stderr()),  # type: ignore[arg-type]
        cache_logger_on_first_use=True,
    )


def get(name: str) -> Any:
    """A logger bound to a module name."""
    return structlog.get_logger(name)
