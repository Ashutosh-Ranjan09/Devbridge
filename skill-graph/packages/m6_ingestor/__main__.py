"""Run the ingestor, or push a batch into it from the command line.

    python3 -m m6_ingestor serve --db evidence.db --port 8100
    python3 -m m6_ingestor ingest batch.json --db evidence.db
"""
from __future__ import annotations

import argparse
import json
import sys

from m6_ontology import AcceptAll, default_ontology

from .errors import IngestError
from .ingestor import Ingestor
from .store import EventLog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m6_ingestor", description=__doc__)
    parser.add_argument("command", choices=("serve", "ingest"))
    parser.add_argument("batch", nargs="?", help="EvidenceEventBatch JSON, for `ingest`")
    parser.add_argument("--db", default=":memory:", help="SQLite path (default: in memory)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--accept-unknown-skills", action="store_true",
                        help="skip ontology resolution; nothing is quarantined")
    args = parser.parse_args(argv)

    ontology = AcceptAll() if args.accept_unknown_skills else default_ontology()
    with EventLog(args.db) as log:
        ingestor = Ingestor(log, ontology=ontology)

        if args.command == "ingest":
            if not args.batch:
                parser.error("ingest needs a batch file")
            with open(args.batch) as handle:
                try:
                    receipt = ingestor.ingest(json.load(handle))
                except IngestError as exc:
                    print(f"refused ({type(exc).__name__}): {exc}", file=sys.stderr)
                    return 1
            print(f"{receipt.stored} accepted, {len(receipt.duplicates)} duplicate, "
                  f"{len(receipt.quarantined)} quarantined"
                  + (" — replay, nothing written" if receipt.replayed else ""))
            for event_id, skills in receipt.quarantined.items():
                print(f"  quarantined {event_id}: {', '.join(skills)} not in the ontology")
            print(f"log now holds {log.count()} events")
            return 0

        from .api import serve
        httpd = serve(ingestor, args.host, args.port)
        print(f"ingestor on http://{args.host}:{args.port}  db={args.db}  "
              f"ontology={ontology.ontology_version}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
