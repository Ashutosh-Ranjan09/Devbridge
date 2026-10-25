"""Project a report from the command line.

    python3 -m m6_projection docs/docs/examples/report-full.json
    python3 -m m6_projection report.json --out batch.json --module-version 0.4.1
"""
from __future__ import annotations

import argparse
import json
import sys

from .projector import project


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="m6_projection", description=__doc__)
    ap.add_argument("report", help="path to an M5 VerificationReport")
    ap.add_argument("--out", help="write the batch here (default: stdout)")
    ap.add_argument("--module-version", default="0.0.0")
    ap.add_argument("--quiet", action="store_true", help="suppress the summary on stderr")
    args = ap.parse_args(argv)

    with open(args.report) as fh:
        batch = project(json.load(fh), module_version=args.module_version)

    payload = json.dumps(batch.to_dict(), indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(payload + "\n")
    else:
        print(payload)

    if not args.quiet:
        print(f"{len(batch.events)} events, {len(batch.not_emitted)} suppressed, "
              f"{len(batch.quarantined)} quarantined", file=sys.stderr)
        for s in batch.not_emitted:
            print(f"  not_emitted[{s.reason}] {s.what}", file=sys.stderr)
        for q in batch.quarantined:
            print(f"  quarantined: {q}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
