# m6_ontology — 6.1 ontology service

Owns three answers every other submodule needs and none of them may decide for
itself.

| question | method | who asks |
|---|---|---|
| Does this skill exist? | `knows(skill_id)` | 6.2, to quarantine or accept |
| How fast does it decay? | `tier(skill_id)` | 6.3, to pick a half-life |
| What does it imply? | `relations()`, `neighbours(id)` | 6.3, to propagate one hop |
| What can be filtered on? | `skill_ids()`, `skills()` | 6.4, to build a UI |

```python
from m6_ontology import default_ontology
onto = default_ontology()
onto.knows("typescript")     # True
onto.tier("react")           # "framework"  → half-life 467 days
onto.neighbours("cpp")       # (Edge(cpp, algorithms, REQUIRES), Edge(cpp, c, RELATED_TO))
```

## The graph is the contract, not the code

Every skill, tier and edge is in `../schemas/skills/ontology.yaml`, shared with M5. Nothing here
defines one, so the graph can be reviewed by someone who does not read Python —
which matters, because a tier is a claim about how fast a skill goes stale and
that claim should be arguable by whoever knows the field, not by whoever last
edited the module.

## The port is two methods wide, deliberately

`SkillResolver` is `knows()` and `ontology_version`. That is the whole surface
6.2 gets. If the ingestor could reach the edges it would eventually traverse
them, and propagation would move from read time in 6.3 — where it can be turned
off and explained — to write time in 6.2, where it cannot.
`test_boundaries.py` runs the ingestor against a resolver that raises on any
other attribute, so widening the port fails a test rather than passing review.

`AcceptAll` resolves everything, for deployments that want the ontology to grow
from evidence rather than gate it. Its version reads `accept-all` rather than a
number: a receipt should admit plainly that nothing was checked.

## Validation

`load()` refuses a broken seed by default, because every way it can break is
silent in production:

| problem | what it would do unnoticed |
|---|---|
| edge to a skill that does not exist | propagation never fires; the target sits at the prior |
| skill with no tier | decays at the default rate rather than its own |
| tier not declared in the contract | same, with nothing to compare against |
| `skill_id` not `lower_snake_case` | `React` and `react` split one skill's evidence in two |
| duplicated edge | the target is updated twice from one source and lands over-confident |
| self edge | a skill updates itself from its own evidence, damped — an update from no new information |
| missing `ontology_version` | receipts record which graph judged a batch; a default makes that a lie |

`validate()` returns **every** problem, not the first. Fixing a contract file
one error per run is how a half-corrected ontology gets deployed.

A cycle is **not** a problem. Propagation runs one hop from direct-evidence
sources only, so a cycle cannot loop; flagging one would imply a constraint 6.3
does not have.

## Command line

```
python3 -m m6_ontology check          # exit 1 if the seed is broken — for CI
python3 -m m6_ontology skills --tier framework
python3 -m m6_ontology edges
python3 -m m6_ontology show cpp       # both directions of propagation
python3 -m m6_ontology dump           # the whole graph as JSON
```

## Tests — 77, every reachable line executed

| file | what it holds |
|---|---|
| `test_graph.py` | the accessors, and that `tier()` returns `None` rather than a default |
| `test_seed_validation.py` | every check, each provoked on purpose; and that a cycle passes |
| `test_seed.py` | the shipped contract, and its agreement with `m6-parameters.yaml` |
| `test_boundaries.py` | the dependency direction, the narrow port, substitutability |
| `test_integration.py` | that the answers are load-bearing — see below |
| `test_cli.py` | `check` fails a build; `show` gets propagation direction right |

### Why `test_integration.py` exists

Mutation testing: make 6.1 lie, run the whole suite, see who notices. A test
that passes under a broken ontology is not integrated with it, however many
times it says the word.

| the lie | suites that caught it |
|---|---|
| `knows()` always `False` | 12 |
| `relations()` always empty | 13 |
| `tier()` always `None` | **2** |

Two. And one of those was 6.1's own. Nothing asserted that the ontology's tier
is what decides how fast a score decays — 6.3 falls back to `m6-parameters`'
list and produces plausible numbers from the wrong half-life. `test_integration`
now folds identical evidence under two ontologies that differ only in `cpp`'s
tier and asserts the score, the variance and the interval width all move.

The same run found `relations()` and `Edge` used **nowhere outside 6.1**, while
this README claimed 6.3 read them: 6.3 was reading raw dicts off `.edges`.
`edges_from_ontology` now prefers the typed accessor, so the sentence and the
code agree.

## What is not here

No scores, no decay arithmetic, no propagation. 6.1 says what the graph *is*;
6.3 decides what follows from it. And no editing: the seed is a reviewed file
under version control, so growing the ontology is a pull request, not an API call.
