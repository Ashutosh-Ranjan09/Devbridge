"""Run the query API, or ask it something from the command line.

    python3 -m m6_query serve   --db evidence.db --port 8200
    python3 -m m6_query skills  --db evidence.db --subject subj_7a3f9e21
    python3 -m m6_query explain --db evidence.db --subject subj_7a3f9e21 --skill typescript
    python3 -m m6_query search  --db evidence.db --skill typescript --min 0.3
"""
from __future__ import annotations

import argparse
import json
from datetime import date

from m6_ingestor import EventLog
from m6_ontology import default_ontology
from m6_scoring import ScoringEngine

from .errors import QueryError
from .service import QueryService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m6_query", description=__doc__)
    parser.add_argument("command", choices=("serve", "skills", "explain", "search"))
    parser.add_argument("--db", default="evidence.db")
    parser.add_argument("--subject")
    parser.add_argument("--skill")
    parser.add_argument("--min", type=float, default=0.0)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--maybe", action="store_true",
                        help="match intervals that REACH the threshold, not only clear it")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8200)
    args = parser.parse_args(argv)

    as_of = date.fromisoformat(args.as_of)
    ontology = default_ontology()
    with EventLog(args.db) as log:
        service = QueryService(log, ScoringEngine(ontology=ontology), ontology=ontology)

        if args.command == "serve":
            from .api import serve
            httpd = serve(service, args.host, args.port)
            print(f"query api on http://{args.host}:{args.port}  db={args.db}")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nstopped")
            return 0

        subject = args.subject or (service.subjects() or [None])[0]
        if subject is None:
            print(f"no evidence in {args.db} — run `make ingest` first")
            return 1

        try:
            if args.command == "skills":
                views = service.skills(subject, as_of)
                print(f"{subject}  as of {as_of}\n")
                print(f"  {'skill':<18}{'interval':>16}{'mean':>7}{'evid':>6}  basis")
                for v in views:
                    basis = (f"inferred from {v.propagated['from_skill_id']}"
                             if v.propagated else f"{v.evidence_count} direct")
                    print(f"  {v.skill_id:<18}[{v.lower:.3f}, {v.upper:.3f}]"
                          f"{v.mean:>7.3f}{v.evidence_count:>6}  {basis}")
                print("\n  No overall score is published; these are per-skill intervals.")
                return 0

            if args.command == "explain":
                if not args.skill:
                    parser.error("explain needs --skill")
                print(json.dumps(service.explain(subject, args.skill, as_of), indent=2))
                return 0

            if not args.skill:
                parser.error("search needs --skill")
            found = service.search(args.skill, as_of, minimum=args.min,
                                   definite=not args.maybe)
            rule = "reaching" if args.maybe else "clearing"
            print(f"{args.skill} — intervals {rule} {args.min:.2f}, as of {as_of}\n")
            for tier in found:
                label = " (indistinguishable)" if len(tier.members) > 1 else ""
                print(f"  tier {tier.rank}{label}")
                for c in tier.members:
                    note = f"  inferred from {c.propagated_from}" if c.propagated_from else ""
                    print(f"    {c.subject_ref:<20}[{c.lower:.3f}, {c.upper:.3f}]"
                          f"  {c.evidence_count} evid{note}")
            if not found:
                print("  nobody clears that threshold")
            return 0
        except QueryError as exc:
            print(f"{type(exc).__name__}: {exc}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
