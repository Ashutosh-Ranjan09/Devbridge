"""One HTTP surface for the whole layer.

6.2 and 6.4 each serve their own; in a deployment they are separate services on
separate ports, because writing and reading scale differently. This composes
them for the demo and for anyone who wants module 6 as one process.

    POST /evidence/report            an M5 verification report; projects and ingests
    POST /evidence/batch             an already-projected batch
    GET  /health
    GET  /versions                   every contract version behind an answer
    GET  /quarantine                 skills named in evidence that the ontology does not know
    GET  /skills                     the ontology
    GET  /developers/{ref}/skills
    GET  /developers/{ref}/skills/{skill}/explain
    GET  /developers/{ref}/integrity
    GET  /developers/{ref}/profile
    GET  /search?skill=...
    POST /shortlist[?subject=…]      a confirmed job's requirements → who qualifies;
                                     `subject` (repeatable) answers for those people only
    GET  /developers/{ref}/score     400, on purpose: no overall score exists
"""
from __future__ import annotations

import json
import re
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from m6_ingestor.errors import IngestError
from m6_projection.errors import ProjectionError
from m6_query.api import _as_of, _flag, build_routes as query_routes
from m6_query.errors import QueryError

MAX_BODY = 8 * 1024 * 1024


def build_routes(m6) -> list[tuple[re.Pattern[str], str, Any]]:
    """(pattern, method, handler). Query routes are reused verbatim rather than
    reimplemented, so the two surfaces cannot drift apart."""
    routes: list[tuple[re.Pattern[str], str, Any]] = [
        (p, "GET", h) for p, h in query_routes(m6.query)]

    def versions(_m, _q, _b):
        return 200, m6.versions()

    def quarantine(_m, _q, _b):
        # The ingestor's own server has this; the combined one did not, so an operator
        # of the one-process deployment could not see what the ontology is missing.
        held = m6.log.quarantined()
        return 200, {"count": len(held), "quarantined": held,
                     "ontology_version": m6.ontology.ontology_version}

    def ingest_report(_m, _q, body):
        return 202, m6.ingest_report(body).to_dict()

    def ingest_batch(_m, _q, body):
        return 202, m6.ingest_batch(body).to_dict()

    def integrity(m, q, _b):
        return 200, m6.integrity(unquote(m.group("ref")), _as_of(q)).to_dict()

    def profile(m, q, _b):
        return 200, m6.profile(unquote(m.group("ref")), _as_of(q))

    def shortlist(_m, q, body):
        return 200, m6.query.shortlist(body, _as_of(q), definite=_flag(q, "definite", True),
                                       subjects=q.get("subject"))

    routes = [
        (re.compile(r"^/versions$"), "GET", versions),
        (re.compile(r"^/quarantine$"), "GET", quarantine),
        (re.compile(r"^/evidence/report$"), "POST", ingest_report),
        (re.compile(r"^/evidence/batch$"), "POST", ingest_batch),
        (re.compile(r"^/developers/(?P<ref>[^/]+)/integrity$"), "GET", integrity),
        (re.compile(r"^/developers/(?P<ref>[^/]+)/profile$"), "GET", profile),
        (re.compile(r"^/shortlist$"), "POST", shortlist),
    ] + routes
    return routes


def make_handler(m6) -> type[BaseHTTPRequestHandler]:
    routes = build_routes(m6)
    # Query handlers take (match, query); this module's own take (match, query, body).
    # Read from each handler, not from its position: counting the first N routes broke
    # silently the first time a route was added.
    arity3 = {h for _p, _m, h in routes if h.__code__.co_argcount == 3}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "m6/1.0"

        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> Any:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError(f"body of {length} bytes exceeds {MAX_BODY}")
            if not length:
                raise ValueError("empty body")
            return json.loads(self.rfile.read(length))

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            path = url.path.rstrip("/") or "/health"
            query = parse_qs(url.query)
            body = None
            if method == "POST":
                try:
                    body = self._body()
                except ValueError as exc:
                    self._send(400, {"error": "malformed_json", "detail": str(exc)})
                    return
                except json.JSONDecodeError as exc:
                    self._send(400, {"error": "malformed_json", "detail": str(exc)})
                    return
            for pattern, verb, handler in routes:
                if verb != method:
                    continue
                match = pattern.match(path)
                if not match:
                    continue
                try:
                    args = (match, query, body) if handler in arity3 else (match, query)
                    status, payload = handler(*args)
                except (QueryError, IngestError) as exc:
                    self._send(exc.status, {"error": type(exc).__name__,
                                            "detail": str(exc)})
                except ProjectionError as exc:
                    # /evidence/report runs 6.0 before 6.2, so a report that is
                    # malformed rather than merely invalid fails here. Without
                    # this the projection's errors escape as a crashed
                    # connection instead of a status the caller can act on.
                    self._send(400, {"error": type(exc).__name__, "detail": str(exc)})
                except ValueError as exc:
                    self._send(400, {"error": "BadParameter", "detail": str(exc)})
                else:
                    self._send(status, payload)
                return
            self._send(404, {"error": "not_found", "detail": f"no route for {url.path}"})

        def do_GET(self) -> None:   # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

    return Handler


def serve(m6, host: str = "127.0.0.1", port: int = 8300) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(m6))
