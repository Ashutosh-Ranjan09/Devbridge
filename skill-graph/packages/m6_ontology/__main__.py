"""Inspect or check the ontology from the command line.

    python3 -m m6_ontology check                  # exit 1 if the seed is broken
    python3 -m m6_ontology skills [--tier framework]
    python3 -m m6_ontology edges
    python3 -m m6_ontology show cpp
    python3 -m m6_ontology dump                   # the whole graph as JSON
"""
from __future__ import annotations

import argparse
import json
import sys

from .errors import InvalidOntology, UnknownSkill
from .graph import SEED, SeedOntology


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m6_ontology", description=__doc__)
    parser.add_argument("command", choices=("check", "skills", "edges", "show", "dump"))
    parser.add_argument("skill", nargs="?", help="skill_id, for `show`")
    parser.add_argument("--seed", default=str(SEED))
    parser.add_argument("--tier", help="filter `skills` to one volatility tier")
    args = parser.parse_args(argv)

    try:
        # Loaded unchecked so `check` can report the problems rather than die of
        # them, then validated explicitly below.
        onto = SeedOntology.load(args.seed, strict=False)
    except OSError as exc:
        print(f"cannot read the seed: {exc}", file=sys.stderr)
        return 1

    problems = onto.validate()
    if args.command == "check":
        if problems:
            print(InvalidOntology(problems, args.seed), file=sys.stderr)
            return 1
        print(f"ontology {onto.ontology_version}: {len(onto)} skills, "
              f"{len(onto.relations())} edges, no problems")
        return 0
    if problems:
        print(f"warning: {len(problems)} problem(s) — run `check`", file=sys.stderr)

    if args.command == "skills":
        for skill in onto.skills():
            if args.tier and skill.tier != args.tier:
                continue
            print(f"  {skill.skill_id:<18} {skill.tier:<12} {skill.label}")
    elif args.command == "edges":
        for edge in onto.relations():
            print(f"  {edge.source:<14} --{edge.type:<16}-> {edge.target}")
    elif args.command == "show":
        if not args.skill:
            parser.error("show needs a skill_id")
        try:
            skill = onto.skill(args.skill)
        except UnknownSkill as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"  {skill.skill_id}  ({skill.label})")
        print(f"  tier: {skill.tier} — {onto.tiers.get(skill.tier, '').strip()}")
        out = onto.neighbours(skill.skill_id)
        into = [e for e in onto.relations() if e.target == skill.skill_id]
        print(f"  evidence here propagates to: "
              f"{', '.join(f'{e.target} ({e.type})' for e in out) or 'nothing'}")
        print(f"  evidence propagating in from: "
              f"{', '.join(f'{e.source} ({e.type})' for e in into) or 'nothing'}")
    else:
        print(json.dumps(onto.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
