# m6_integrity — integrity analytics

**Status: complete (v1.0.0).** M6 submodule 6.5 — the last of the layer.

Reads the evidence log and reports what a careful reader should notice about the
**shape** of the evidence. It writes nothing and changes no score.

```python
from m6_integrity import IntegrityAnalyser
report = IntegrityAnalyser(engine=engine).analyse(events, as_of, states=states)
```

## Why it is a separate submodule

The obvious design is a reliability adjustment inside 6.3 — detect something
suspicious, discount the evidence. That is exactly what this must not do. A
signal that silently moved a score would be an unexplainable penalty, and there
is no overall trust number here to absorb it. So 6.5 produces **findings**, and
`test_neutrality.py` asserts the guarantee directly: the graph is byte-identical
before and after the analyser runs.

Three properties are structural, not stylistic:

**It names its evidence.** Every finding carries the event ids or skills it is
about, so a reader can go and look.

**It states the innocent explanation.** Every pattern here has a mundane cause,
and the contract requires each check to carry it. A pattern presented without one
reads as an accusation — a burst of recent commits is a student finishing
coursework far more often than it is anything else.

**There is no "fail" severity.** Two values, `notice` and `attention`. Nothing
here is certain enough to condemn a candidate, and a third tier would invite
someone to threshold on it.

## The nine checks

| | |
|---|---|
| `EVIDENCE_BURST` | attention — most evidence created just before verification |
| `OWNERSHIP_UNPROVEN` | attention — how much of the graph rests on an unproven account |
| `CONTRADICTED` | attention — the same skill supported and contradicted |
| `SINGLE_SOURCE` | notice — nothing independently corroborates a skill |
| `CLAIM_ONLY` | notice — a skill resting wholly on self-report |
| `INFERRED_ONLY` | notice — no direct evidence; the score came from a neighbour |
| `WHOLLY_STALE` | notice — every event older than the skill's own half-life |
| `BREADTH_FROM_ONE_ARTEFACT` | notice — many skills rising and falling together |
| `QUARANTINED_EVIDENCE` | notice — evidence held out over unknown skills |

Every threshold lives in `contracts/integrity-rules.yaml`. Deleting a check from
the contract switches it off — asserted by a test, so no orphaned code keeps
firing.

`WHOLLY_STALE` reads each skill's own half-life rather than one global age
threshold: the same 20-month-old evidence is stale for a framework and perfectly
fresh for a fundamental.

## Tests — 38

`test_checks.py` gives every check a positive and a negative case, because a
detector that fires on everything is as useless as one that never fires.
`test_neutrality.py` covers the guarantee: no score moves, no event is mutated,
no finding carries anything shaped like a penalty, and every finding has an
innocent explanation of real length.
