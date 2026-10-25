"""
Regression test: the resolved model must reproduce the worked example's ordering.

Folds the eight events from ../schemas/examples/evidence-events.json and checks the
per-skill scores against the table in docs/m6-decisions.html. Run this after
any change to m6-parameters.yaml — a change that moves the ORDERING is a finding,
not a detail.

    python3 contracts/reference/verify_worked_example.py
"""
import sys, pathlib
from datetime import date
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import m6_model as M

TIER = {"algorithms": "fundamental", "problem_solving": "fundamental", "cpp": "fundamental",
        "c": "fundamental", "cryptography": "fundamental", "networking": "ecosystem",
        "python": "ecosystem", "typescript": "ecosystem", "javascript": "ecosystem",
        "nextjs": "framework", "react": "framework", "mongodb": "framework",
        "numpy": "framework", "pandas": "framework", "deployment": "framework"}

# (id, occurred_at, strength, reliability, observed, {skill: relevance})
# observed values follow contracts/m6-parameters.yaml → observed_value
RAW = [
    ("e1", date(2025, 1, 14), 0.80, 0.90, 0.74, {"algorithms": .95, "problem_solving": .90, "cpp": .70}),
    ("e2", date(2025, 4, 27), 0.60, 0.42, 0.66, {"typescript": .90, "nextjs": .80, "mongodb": .60}),
    ("e3", date(2025, 6, 19), 0.55, 0.42, 0.62, {"typescript": .90, "nextjs": .80}),
    ("e4", date(2024, 6, 28), 0.50, 0.42, 0.50, {"python": .90, "cryptography": .50, "networking": .45}),
    ("e5", date(2025, 6, 19), 0.70, 0.48, 0.68, {"typescript": 1.0}),
    ("e6", date(2026, 8, 24), 0.40, 0.51, 0.58, {"nextjs": .60, "deployment": .70}),
    ("e7", date(2026, 8, 24), 0.30, 0.20, 0.60, {"cpp": 1.0}),
    ("e8", date(2026, 8, 24), 0.30, 0.20, 0.45, {"numpy": 1.0, "pandas": 1.0}),
]
EDGES = [("typescript", "javascript", "PREREQUISITE_OF"), ("nextjs", "react", "REQUIRES"),
         ("react", "javascript", "REQUIRES"), ("cpp", "c", "RELATED_TO")]
AS_OF = date(2026, 8, 24)

EXPECTED = {"algorithms": 0.533, "cpp": 0.514, "typescript": 0.381, "nextjs": 0.316,
            "javascript": 0.305, "python": 0.187, "numpy": 0.173}
# From cv-to-skill-graph.html §05. Illustrative, not ground truth: match the ORDER.
ILLUSTRATION = {"algorithms": 0.61, "cpp": 0.56, "typescript": 0.48, "nextjs": 0.45,
                "javascript": 0.31, "python": 0.29, "numpy": 0.12}


def build():
    events = [{"event_id": i, "occurred_at": d, "strength": s, "reliability": r, "observed": o,
               "skill_refs": [{"skill_id": k, "relevance": v} for k, v in sk.items()]}
              for i, d, s, r, o, sk in RAW]
    skills = sorted({r["skill_id"] for e in events for r in e["skill_refs"]})
    direct = {s: M.fold(events, s, TIER.get(s, "ecosystem"), AS_OF) for s in skills}
    return M.propagate(direct, EDGES, TIER, AS_OF)


def spearman(a, b):
    rk = lambda xs: [sorted(xs).index(x) for x in xs]
    ra, rb, n = rk(a), rk(b), len(a)
    return 1 - 6 * sum((x - y) ** 2 for x, y in zip(ra, rb)) / (n * (n * n - 1))


def main() -> int:
    final, failures = build(), []
    print(f"{'skill':13}{'mean':>8}{'score':>8}{'expected':>10}{'illus.':>8}")
    for sk, exp in EXPECTED.items():
        ex = M.explain(final[sk], sk)
        flag = "" if abs(ex["score"] - exp) <= 0.002 else "  <-- CHANGED"
        if flag:
            failures.append(sk)
        print(f"{sk:13}{ex['mean']:8.3f}{ex['score']:8.3f}{exp:10.3f}{ILLUSTRATION[sk]:8.2f}{flag}")

    ks = list(EXPECTED)
    rho = spearman([M.explain(final[k], k)["score"] for k in ks], [ILLUSTRATION[k] for k in ks])
    print(f"\nSpearman vs illustration: {rho:.3f}   (must stay 1.000 — ordering is the contract)")
    if failures:
        print(f"FAIL — scores moved for: {', '.join(failures)}")
        return 1
    if rho < 0.999:
        print("FAIL — parameter change reordered the skills. That is a finding, not a detail.")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
