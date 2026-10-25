"""HTTP surface. `http.server` because there is no package manager here — the
handler is thin enough that swapping it for FastAPI is a routing table rewrite
and nothing else. Every decision lives in Ingestor; this file only translates.

    POST /evidence/batch     ingest one EvidenceEventBatch
    GET  /health             liveness plus the ontology version in force
    GET  /events             the log in fold order  (?subject=, ?skill=)
    GET  /quarantine         events held out of scoring, and why
    GET  /batches            what has been ingested
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .errors import IngestError
from .ingestor import Ingestor

MAX_BODY = 8 * 1024 * 1024  # a verification report projects to kilobytes, not megabytes


def _routes(ingestor: Ingestor) -> dict[tuple[str, str], Any]:
    log = ingestor.log

    def health(_query: dict, _body: Any) -> tuple[int, dict]:
        return 200, {"status": "ok", "events": log.count(),
                     "ontology_version": ingestor.ontology.ontology_version}

    def ingest(_query: dict, body: Any) -> tuple[int, dict]:
        return 202, ingestor.ingest(body).to_dict()

    def events(query: dict, _body: Any) -> tuple[int, dict]:
        if "skill" in query:
            found = log.events_for_skill(
                query["skill"][0], include_quarantined="all" in query)
        else:
            found = log.events(query.get("subject", [None])[0])
        return 200, {"count": len(found),
                     "events": [e.document for e in found]}

    def quarantine(_query: dict, _body: Any) -> tuple[int, dict]:
        held = log.quarantined()
        return 200, {"count": len(held), "quarantined": held,
                     "ontology_version": ingestor.ontology.ontology_version}

    def batches(_query: dict, _body: Any) -> tuple[int, dict]:
        return 200, {"count": len(log.batches()), "batches": log.batches()}

    return {("POST", "/evidence/batch"): ingest, ("GET", "/health"): health,
            ("GET", "/events"): events, ("GET", "/quarantine"): quarantine,
            ("GET", "/batches"): batches}


def make_handler(ingestor: Ingestor) -> type[BaseHTTPRequestHandler]:
    table = _routes(ingestor)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "m6-ingestor/1.0"

        def log_message(self, *args: Any) -> None:  # quiet under test
            pass

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle(self, method: str) -> None:
            url = urlparse(self.path)
            route = table.get((method, url.path.rstrip("/") or "/"))
            if route is None:
                self._send(404, {"error": "not_found", "detail": f"no route for {url.path}"})
                return
            try:
                body = self._read_body() if method == "POST" else None
            except ValueError as exc:
                self._send(400, {"error": "malformed_json", "detail": str(exc)})
                return
            try:
                status, payload = route(parse_qs(url.query), body)
            except IngestError as exc:
                # The error type IS the status code — see errors.py.
                self._send(exc.status, {"error": type(exc).__name__, "detail": str(exc)})
                return
            self._send(status, payload)

        def _read_body(self) -> Any:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError(f"body of {length} bytes exceeds the {MAX_BODY} byte limit")
            if not length:
                raise ValueError("empty body")
            try:
                return json.loads(self.rfile.read(length))
            except json.JSONDecodeError as exc:
                raise ValueError(str(exc)) from exc

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming
            self._handle("POST")

        def do_GET(self) -> None:  # noqa: N802
            self._handle("GET")

    return Handler


def serve(ingestor: Ingestor, host: str = "127.0.0.1", port: int = 8100) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(ingestor))
