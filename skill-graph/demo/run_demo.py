#!/usr/bin/env python3
"""Module 6, demonstrated end to end on one M5 verification report.

Not a test. This exists to be READ and run by hand: it walks an extensive M5
output through every submodule in order, prints what each one decided, and
writes the results to demo/output/.

    python3 demo/run_demo.py                 # the whole walkthrough
    python3 demo/run_demo.py --step 3        # just one step
    python3 demo/run_demo.py --http          # also exercise the HTTP API
    python3 demo/run_demo.py --input other.json --as-of 2027-01-01

Every number printed is computed live. Nothing here is hard-coded.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "packages"))

from m6 import M6                                    # noqa: E402
from m6_ingestor import ConsentRefused               # noqa: E402

DEFAULT_INPUT = HERE / "input" / "verification-report-extensive.json"
OUTPUT = HERE / "output"

# ── printing ────────────────────────────────────────────────────────────────
W = 78
BOLD, DIM, OFF = "\033[1m", "\033[2m", "\033[0m"


def head(n: int, title: str, subtitle: str = "") -> None:
    print(f"\n{BOLD}{'═' * W}{OFF}")
    print(f"{BOLD} STEP {n}  {title}{OFF}")
    if subtitle:
        print(f"{DIM} {subtitle}{OFF}")
    print(f"{BOLD}{'═' * W}{OFF}")


def note(text: str) -> None:
    print(f"{DIM}   {text}{OFF}")


def save(name: str, payload) -> pathlib.Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / name
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(f"{DIM}   -> {path.relative_to(ROOT)}{OFF}")
    return path


# ── the steps ───────────────────────────────────────────────────────────────
def step1_input(report: dict) -> None:
    head(1, "THE INPUT — an M5 verification report",
         "M6's only dependency is this one document. It imports nothing from M5.")
    graph, bundle = report["claim_graph"], report["evidence_bundle"]
    kinds: dict[str, int] = {}
    for c in graph["claims"]:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    print(f"   verification_id : {report['verification_id']}")
    print(f"   subject         : {report['subject']['subject_ref']}")
    print(f"   consent_ref     : {report['subject'].get('consent_ref')}")
    print(f"   CV written      : {report['document']['created_at'][:10]}")
    print(f"   verified        : {report['valid_as_of'][:10]}")
    print(f"\n   {len(graph['claims'])} claims: "
          + ", ".join(f"{k} x{v}" for k, v in sorted(kinds.items())))
    gh = bundle.get("github") or {}
    print(f"   github          : {gh.get('handle')} ({gh.get('ownership')}), "
          f"{len(gh.get('repos') or [])} repos")
    print(f"   platforms       : "
          + ", ".join(f"{p['platform']}({p.get('source_quality')})"
                      for p in bundle.get("platforms") or []))
    print(f"   deployments     : {len(bundle.get('deployments') or [])}"
          f"   credentials: {len(bundle.get('credentials') or [])}"
          f"   gaps: {len(bundle.get('gaps') or [])}")
    note("The CV is dated 6 weeks before verification. That matters in step 2.")


def step2_projection(m6: M6, report: dict) -> dict:
    head(2, "6.0  EVENT PROJECTION — what capability signal is here?",
         "Decides what each verified artefact SAYS. Never whether a claim is "
         "true (M5 did that), never what it is worth (6.3 does that).")
    batch = m6.project(report)
    print(f"   {len(batch['events'])} events, {len(batch['not_emitted'])} suppressions\n")
    print(f"   {'kind':<20}{'occurred':<12}{'str':>5}{'rel':>6}  skills")
    for e in batch["events"]:
        names = ", ".join(r["skill_id"] for r in e["skill_refs"])
        print(f"   {e['kind']:<20}{e['occurred_at'][:10]:<12}"
              f"{e['strength']:>5.2f}{e['reliability']:>6.2f}  {names[:34]}")

    print(f"\n   {BOLD}Suppressed — recorded, never silent:{OFF}")
    for s in batch["not_emitted"]:
        print(f"     [{s['reason']:<24}] {s['what'][:44]}")

    capped = [e for e in batch["events"] if e.get("reliability_factors")]
    if capped:
        print(f"\n   {BOLD}Reliability discounts, each one named:{OFF}")
        for e in capped:
            for f in e["reliability_factors"]:
                print(f"     {e['kind']:<20} x{f['value']} {f['factor']}")
    note("A CV claim is dated at the DOCUMENT, not at verification — the weakest "
         "evidence must not get the freshest date.")
    save("01-projected-batch.json", batch)
    return batch


def step3_ingest(m6: M6, report: dict) -> None:
    head(3, "6.2  EVIDENCE INGESTOR — may this enter the log?",
         "Validation, consent, idempotency, immutable storage, quarantine.")
    receipt = m6.ingest_report(report)
    print(f"   accepted   : {receipt.stored}")
    print(f"   duplicates : {len(receipt.duplicates)}")
    print(f"   quarantined: {len(receipt.quarantined)}")
    for event_id, skills in receipt.quarantined.items():
        print(f"     {event_id}  {', '.join(skills)} — not in the ontology")

    print(f"\n   {BOLD}Replaying the same report:{OFF}")
    again = m6.ingest_report(report)
    print(f"     replayed={again.replayed}, accepted={len(again.accepted)}, "
          f"log still holds {m6.log.count()} events")

    print(f"\n   {BOLD}Consent is checked here too, not only in 6.0:{OFF}")
    unconsented = json.loads(json.dumps(report))
    unconsented["subject"].pop("consent_ref", None)
    unconsented["verification_id"] += "_noconsent"
    try:
        m6.ingest_report(unconsented)
        print("     ERROR: an unconsented report was accepted")
    except ConsentRefused as exc:
        print(f"     refused: {exc}")

    print(f"\n   {BOLD}The log is append-only, enforced by the database:{OFF}")
    import sqlite3
    try:
        m6.log._db.execute("UPDATE evidence_event SET strength = 0.99")
        print("     ERROR: the log allowed an update")
    except sqlite3.IntegrityError as exc:
        print(f"     refused: {exc}")
    note("event_id is a hash of (verification_id, kind, discriminator), so "
         "at-least-once delivery is safe by construction.")
    save("02-ingest-receipt.json", receipt.to_dict())


def step4_scoring(m6: M6, subject: str, as_of: date) -> None:
    head(4, "6.3  SCORING ENGINE — what does the evidence add up to?",
         "Kalman update in logit space, decay as growing variance, one-hop "
         "propagation. No trained model, no optimiser, no labelled data.")
    views = m6.skills(subject, as_of)
    print(f"   {'skill':<17}{'interval':<17}{'mean':>7}{'evid':>6}  basis")
    for v in views:
        d = v.to_dict()
        basis = (f"inferred from {v.propagated['from_skill_id']}" if v.propagated
                 else f"{v.evidence_count} direct")
        print(f"   {d['skill_id']:<17}[{d['interval'][0]:.3f}, {d['interval'][1]:.3f}]"
              f"{d['mean']:>8.3f}{d['evidence_count']:>6}  {basis}")
    note("The published score is the LOWER BOUND, not the mean — a wide, "
         "uncertain estimate must not present as a confident one.")

    later = as_of.replace(year=as_of.year + 2)
    print(f"\n   {BOLD}The same graph two years on, with no new evidence:{OFF}")
    print(f"   {'skill':<17}{'now':<17}{as_of.year + 2}")
    for a, b in list(zip(views, m6.skills(subject, later)))[:5]:
        print(f"   {a.skill_id:<17}[{a.lower:.3f}, {a.upper:.3f}]    "
              f"[{b.lower:.3f}, {b.upper:.3f}]")
    note("Intervals widen and scores fall. The story is 'we know less now', "
         "not 'they got worse'.")
    save("03-skill-graph.json", [v.to_dict() for v in views])


def step5_explain(m6: M6, subject: str, as_of: date, skill: str) -> None:
    head(5, f"6.4  QUERY API — why is {skill} that number?",
         "The explain endpoint. Every score has to be arguable.")
    got = m6.explain(subject, skill, as_of)
    print(f"   score {got['score']}   interval {got['interval']}   "
          f"mean {got['mean']}   basis {got['basis']}")
    print(f"   tier {got['tier']} (half-life {got['half_life_days']}d), "
          f"newest evidence {got['days_since_newest_evidence']}d ago\n")
    print(f"   {BOLD}Contributing events, in fold order:{OFF}")
    print(f"     {'kind':<20}{'date':<12}{'obs':>6}{'relev':>7}{'weight':>8}{'-> mean':>9}")
    for c in got["contributions"]:
        print(f"     {c['kind']:<20}{c['occurred_at'][:10]:<12}{c['observed']:>6.2f}"
              f"{c['relevance']:>7.3f}{c['weight']:>8.3f}{c['moved_mean_to']:>9.3f}")
    print(f"\n   {BOLD}Considered and NOT counted:{OFF}")
    for r in got["not_counted"][:6]:
        print(f"     [{r['reason']:<24}] {r['what'][:42]}")
    note("The first event carries the most weight — against a wide prior, the "
         "first observation moves the estimate furthest.")
    save("04-explain.json", got)


def step6_search(m6: M6, as_of: date, skill: str) -> None:
    head(6, "6.4  SEARCH — who clears the bar?",
         "Tiers, never a ranking. Two candidates are ordered only when their "
         "intervals do not overlap.")
    for definite in (True, False):
        rule = "whole interval clears" if definite else "interval reaches"
        found = m6.search(skill, as_of, minimum=0.40, definite=definite)
        print(f"\n   {BOLD}{skill} >= 0.40 ({rule}):{OFF}")
        if not found:
            print("     nobody")
        for tier in found:
            label = "  <- indistinguishable" if len(tier.members) > 1 else ""
            print(f"     tier {tier.rank}{label}")
            for m in tier.members:
                print(f"       {m.subject_ref:<18}[{m.lower:.3f}, {m.upper:.3f}]"
                      f"  {m.evidence_count} evid")
    note("`definite` is the caller's risk decision: confident they are above "
         "the bar, or they might be. The API refuses to choose silently.")


def step7_integrity(m6: M6, subject: str, as_of: date) -> None:
    head(7, "6.5  INTEGRITY ANALYTICS — what should a reader notice?",
         "Reads the log and the states. Writes nothing, changes no score.")
    report_obj = m6.integrity(subject, as_of)
    d = report_obj.to_dict()
    print(f"   {d['events_examined']} events, {d['skills_examined']} skills examined")
    print(f"   {d['counts']['attention']} attention, {d['counts']['notice']} notice\n")
    for f in report_obj.findings:
        print(f"   [{f.severity:<9}] {f.check_id}")
        print(f"     {f.summary}")
        print(f"{DIM}     innocent explanation: {f.innocent_explanation[:76]}...{OFF}")
    note(d["note"])
    save("05-integrity.json", d)


def step8_guarantees(m6: M6, subject: str, as_of: date) -> None:
    head(8, "THE GUARANTEES — what this layer refuses to do",
         "Constraints agreed early, enforced in code rather than documented.")
    from m6_query import AggregateRefused
    from m6_query.api import build_routes
    print(f"   {BOLD}1. There is no overall score.{OFF}")
    for pattern, handler in build_routes(m6.query):
        match = pattern.match(f"/developers/{subject}/score")
        if match:
            try:
                handler(match, {})
            except AggregateRefused as exc:
                print(f"      GET /developers/{{ref}}/score -> 400")
                print(f"      {exc}")
            break

    print(f"\n   {BOLD}2. Integrity findings change nothing.{OFF}")
    before = [v.to_dict() for v in m6.skills(subject, as_of)]
    m6.integrity(subject, as_of)
    after = [v.to_dict() for v in m6.skills(subject, as_of)]
    print(f"      graph identical after running 6.5: {before == after}")

    print(f"\n   {BOLD}3. Every answer names the contracts behind it.{OFF}")
    for k, v in m6.versions().items():
        print(f"      {k:<20} {v}")


def step9_http(m6: M6, subject: str, as_of: date) -> None:
    head(9, "THE HTTP API — every endpoint, live",
         "Module 6 as one process on an ephemeral port.")
    import threading
    import urllib.error
    import urllib.request
    from m6 import serve

    httpd = serve(m6, "127.0.0.1", 0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def call(method, path, body=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    stamp = as_of.isoformat()
    calls = [
        ("GET", "/health", None, lambda b: f"{b['subjects']} subject(s) on record"),
        ("GET", "/versions", None, lambda b: f"m6 {b['m6']}, ontology {b['ontology']}"),
        ("GET", "/skills", None, lambda b: f"{b['count']} skills in the ontology"),
        ("GET", f"/developers/{subject}/skills?as_of={stamp}", None,
         lambda b: f"{b['count']} skills"),
        ("GET", f"/developers/{subject}/skills?as_of={stamp}&include_inferred=false",
         None, lambda b: f"{b['count']} skills with direct evidence"),
        ("GET", f"/developers/{subject}/skills/go/explain?as_of={stamp}", None,
         lambda b: f"go = {b['score']} from {b['evidence_count']} events"),
        ("GET", f"/search?skill=go&min=0.3&as_of={stamp}", None,
         lambda b: f"{b['tier_count']} tier(s)"),
        ("GET", f"/developers/{subject}/integrity?as_of={stamp}", None,
         lambda b: f"{len(b['findings'])} findings"),
        ("GET", f"/developers/{subject}/profile?as_of={stamp}", None,
         lambda b: f"{len(b['skills'])} skills + integrity"),
        ("GET", f"/developers/{subject}/score", None,
         lambda b: b["detail"][:52]),
        ("GET", "/nope", None, lambda b: b["error"]),
    ]
    print(f"   {'method':<7}{'path':<52}{'code':>5}  result")
    try:
        for method, path, body, describe in calls:
            status, payload = call(method, path, body)
            shown = path if len(path) < 50 else path[:47] + "..."
            print(f"   {method:<7}{shown:<52}{status:>5}  {describe(payload)}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    note("POST /evidence/report takes a raw M5 report; POST /evidence/batch "
         "takes an already-projected one.")


# ── entry point ─────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=pathlib.Path, default=DEFAULT_INPUT)
    parser.add_argument("--as-of", default=None,
                        help="default: the report's own valid_as_of")
    parser.add_argument("--skill", default="go", help="skill to explain (step 5)")
    parser.add_argument("--step", type=int, help="run only this step")
    parser.add_argument("--http", action="store_true", help="also run step 9")
    parser.add_argument("--db", default=":memory:")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"no such input: {args.input}", file=sys.stderr)
        return 1
    args.input = args.input.resolve()
    report = json.loads(args.input.read_text())
    subject = report["subject"]["subject_ref"]
    as_of = (date.fromisoformat(args.as_of) if args.as_of
             else date.fromisoformat(report["valid_as_of"][:10]))

    print(f"{BOLD}DevBridge Module 6 — end-to-end demonstration{OFF}")
    shown = (args.input.relative_to(ROOT)
             if args.input.is_relative_to(ROOT) else args.input)
    print(f"{DIM}input {shown} | subject {subject} | as of {as_of}{OFF}")

    with M6(args.db) as m6:
        steps = {
            1: lambda: step1_input(report),
            2: lambda: step2_projection(m6, report),
            3: lambda: step3_ingest(m6, report),
            4: lambda: step4_scoring(m6, subject, as_of),
            5: lambda: step5_explain(m6, subject, as_of, args.skill),
            6: lambda: step6_search(m6, as_of, args.skill),
            7: lambda: step7_integrity(m6, subject, as_of),
            8: lambda: step8_guarantees(m6, subject, as_of),
            9: lambda: step9_http(m6, subject, as_of),
        }
        if args.step:
            # Later steps need the log populated, so run ingestion quietly first.
            if args.step > 3:
                m6.ingest_report(report)
            steps[args.step]()
        else:
            for n in range(1, 9):
                steps[n]()
            if args.http:
                steps[9]()

    print(f"\n{BOLD}{'═' * W}{OFF}")
    print(f" Done. JSON written to {OUTPUT.relative_to(ROOT)}/")
    print(f"{BOLD}{'═' * W}{OFF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
