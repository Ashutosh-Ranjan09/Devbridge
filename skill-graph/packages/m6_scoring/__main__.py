"""Score a subject, explain one skill, or run the recovery gate.

    python3 -m m6_scoring score   --db evidence.db --as-of 2026-08-24
    python3 -m m6_scoring explain --db evidence.db --skill typescript
    python3 -m m6_scoring recover
    python3 -m m6_scoring sweep
"""
from __future__ import annotations

import argparse
import json
from datetime import date

from .engine import ScoringEngine
from .params import default_parameters
from .propagation import Propagator, edges_from_ontology


def _load_events(db: str) -> list[dict]:
    from m6_ingestor import EventLog
    with EventLog(db) as log:
        return [e.document for e in log.events()]


def _ontology():
    from m6_ontology import default_ontology
    return default_ontology()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m6_scoring", description=__doc__)
    parser.add_argument("command", choices=("score", "explain", "recover", "sweep"))
    parser.add_argument("--db", default="evidence.db")
    parser.add_argument("--skill")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--no-propagate", action="store_true")
    parser.add_argument("--trials", type=int, default=300)
    args = parser.parse_args(argv)

    if args.command == "recover":
        from . import recovery
        report = recovery.run(trials=args.trials)
        print(report.render())
        print("\nrmse against evidence count — more evidence must mean less error")
        for n, rmse in recovery.convergence():
            print(f"  {n:3d} events   rmse {rmse:.4f}")
        return 0 if report.passed else 1

    if args.command == "sweep":
        params = default_parameters()
        print(f"parameter_version {params.parameter_version} — swept constants:")
        for s in params.sweepable():
            print(f"  {s.name:<44} value {s.value:<10g} sweep [{s.low:g}, {s.high:g}]")
        return 0

    as_of = date.fromisoformat(args.as_of)
    ontology = _ontology()
    engine = ScoringEngine(ontology=ontology)
    events = _load_events(args.db)
    if not events:
        print(f"no events in {args.db} — run `make ingest` first")
        return 1

    states = engine.fold_all(events, as_of)
    if not args.no_propagate:
        states = Propagator(engine).propagate(states, edges_from_ontology(ontology), as_of)

    if args.command == "explain":
        if not args.skill:
            parser.error("explain needs --skill")
        if args.skill not in states:
            print(f"no state for {args.skill!r}; known: {', '.join(sorted(states))}")
            return 1
        print(json.dumps(engine.explain(states[args.skill], as_of), indent=2))
        return 0

    ranked = sorted(states.values(), key=lambda s: s.state.score(engine.p.z), reverse=True)
    print(f"{'skill':<18}{'score':>7}{'mean':>7}{'band':>7}{'evid':>6}  source")
    for st in ranked:
        origin = "propagated from " + st.propagated["from_skill_id"] if st.propagated else (
            "prior only" if st.is_prior_only else f"{st.evidence_count} direct")
        print(f"  {st.skill_id:<16}{st.state.score(engine.p.z):>7.3f}{st.state.mean:>7.3f}"
              f"{st.state.band(engine.p.z):>7.3f}{st.evidence_count:>6}  {origin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
