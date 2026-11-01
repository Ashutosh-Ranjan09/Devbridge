"""HTTP surface for 6.4.

    GET /health
    GET /skills                                    the ontology, for filter UIs
    GET /developers/{ref}/skills                   the graph
    GET /developers/{ref}/skills/{skill}/explain   the demo
    GET /search?skill=…&min=…&definite=…           tiers, never a ranking
    GET /developers/{ref}/score                    400, on purpose: no overall score exists

Every endpoint accepts `as_of=YYYY-MM-DD`. Decisions live in QueryService; this
file only routes and translates.
"""
from __future__ import annotations

import json
import re
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from .errors import AggregateRefused, QueryError
from .service import QueryService

Route = tuple[re.Pattern[str], Callable[..., tuple[int, dict]]]


def _flag(query: dict, name: str, default: bool) -> bool:
    if name not in query:
        return default
    return query[name][0].lower() not in ("0", "false", "no")


def _as_of(query: dict) -> date:
    raw = query.get("as_of", [None])[0]
    if raw is None:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise QueryError(f"as_of must be YYYY-MM-DD, got {raw!r}") from exc


def build_routes(service: QueryService) -> list[Route]:
    def health(_m, _q) -> tuple[int, dict]:
        return 200, {"status": "ok", "subjects": len(service.subjects()),
                     "parameter_version": service.engine.p.parameter_version}

    def skills_catalogue(_m, _q) -> tuple[int, dict]:
        rows = service.known_skills()
        # The ontology's edges as written (from, to, type): what links one skill to
        # another. Read only by people looking at a graph; nothing here weighs them.
        edges = list(getattr(service.ontology, "edges", None) or [])
        return 200, {"count": len(rows), "skills": rows, "edges": edges}

    def developer_skills(m, q) -> tuple[int, dict]:
        as_of = _as_of(q)
        views = service.skills(
            unquote(m.group("ref")), as_of,
            propagate=_flag(q, "propagate", True),
            include_inferred=_flag(q, "include_inferred", True),
            min_evidence=int(q.get("min_evidence", ["0"])[0]))
        return 200, {
            "subject_ref": unquote(m.group("ref")),
            "as_of": as_of.isoformat(),
            "count": len(views),
            # Named so nobody mistakes the list for a summary of the person.
            "skills": [v.to_dict() for v in views],
            "note": "Per-skill intervals. This system publishes no overall score.",
        }

    def explain(m, q) -> tuple[int, dict]:
        return 200, service.explain(
            unquote(m.group("ref")), unquote(m.group("skill")), _as_of(q),
            propagate=_flag(q, "propagate", True))

    def search(_m, q) -> tuple[int, dict]:
        if "skill" not in q:
            raise QueryError("search needs ?skill=")
        as_of = _as_of(q)
        definite = _flag(q, "definite", True)
        found = service.search(
            q["skill"][0], as_of,
            minimum=float(q.get("min", ["0"])[0]), definite=definite,
            include_inferred=_flag(q, "include_inferred", False))
        return 200, {
            "skill_id": q["skill"][0], "as_of": as_of.isoformat(),
            "threshold": float(q.get("min", ["0"])[0]),
            "match": "whole interval clears the threshold" if definite
                     else "interval reaches the threshold",
            "tier_count": len(found),
            "tiers": [t.to_dict() for t in found],
            "note": ("Tiers, not a ranking. Candidates inside a tier are not "
                     "distinguishable on the available evidence."),
        }

    def refuse_aggregate(m, _q) -> tuple[int, dict]:
        raise AggregateRefused(
            f"there is no overall score for {unquote(m.group('ref'))}. Ask for "
            "/skills, or /skills/{skill}/explain for one skill at a time.")

    return [
        (re.compile(r"^/health$"), health),
        (re.compile(r"^/skills$"), skills_catalogue),
        (re.compile(r"^/developers/(?P<ref>[^/]+)/skills$"), developer_skills),
        (re.compile(r"^/developers/(?P<ref>[^/]+)/skills/(?P<skill>[^/]+)/explain$"), explain),
        (re.compile(r"^/search$"), search),
        (re.compile(r"^/developers/(?P<ref>[^/]+)/(score|rating|trust|overall)$"),
         refuse_aggregate),
    ]


def make_handler(service: QueryService) -> type[BaseHTTPRequestHandler]:
    routes = build_routes(service)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "m6-query/1.0"

        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming
            url = urlparse(self.path)
            path = url.path.rstrip("/") or "/health"
            query = parse_qs(url.query)
            for pattern, handler in routes:
                match = pattern.match(path)
                if not match:
                    continue
                try:
                    status, payload = handler(match, query)
                except QueryError as exc:
                    self._send(exc.status, {"error": type(exc).__name__, "detail": str(exc)})
                except ValueError as exc:
                    self._send(400, {"error": "BadParameter", "detail": str(exc)})
                else:
                    self._send(status, payload)
                return
            self._send(404, {"error": "not_found", "detail": f"no route for {url.path}"})

    return Handler


def serve(service: QueryService, host: str = "127.0.0.1",
          port: int = 8200) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(service))
