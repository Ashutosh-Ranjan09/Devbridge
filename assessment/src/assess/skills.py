"""The shared skill list — schemas/skills/, the one cvv resolves against and M6 scores by.

A pattern's `skill`, and every skill extracted from a job description, must be an id
on this list. That is what lets "rate limiting" mean the same thing in a JD, in an
assessment result, and in a candidate's skill graph.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from assess.config import settings


@dataclass(frozen=True)
class SkillList:
    version: str
    labels: dict[str, str]          # id -> label
    aliases: dict[str, str]         # lower-cased other name -> id

    def knows(self, skill_id: str) -> bool:
        return skill_id in self.labels

    def resolve(self, name: str) -> str | None:
        """An id for a name, by rule only: the id, its label, or an alias."""
        key = name.strip().lower()
        for candidate in (key, key.replace(" ", "_"), key.replace("-", "_")):
            if candidate in self.labels:
                return candidate
        by_label = {label.lower(): sid for sid, label in self.labels.items()}
        return by_label.get(key) or (
            self.aliases[key] if self.aliases.get(key) in self.labels else None
        )

    def names(self) -> dict[str, str]:
        """Every name a JD might use for a skill -> its id: ids, labels, aliases."""
        out = {sid.replace("_", " "): sid for sid in self.labels}
        out.update({label.lower(): sid for sid, label in self.labels.items()})
        out.update({k: v for k, v in self.aliases.items() if v in self.labels})
        return out

    def find_in(self, text: str) -> list[tuple[str, str]]:
        """(id, the words matched) for every name found in a text as whole words.

        Whole words, because a substring test finds "go" in "good" and "c" in every
        sentence. Longest names first, so "next.js" is not also found as "next".
        """
        lowered = text.lower()
        found: dict[str, str] = {}
        taken: list[tuple[int, int]] = []
        for name in sorted(self.names(), key=len, reverse=True):
            if len(name) < 2:
                continue
            # A hyphen joins words: "go" in "go-getter" is not the language.
            for m in re.finditer(rf"(?<![\w+#.-]){re.escape(name)}(?![\w+#-])", lowered):
                span = (m.start(), m.end())
                if any(a < span[1] and span[0] < b for a, b in taken):
                    continue
                taken.append(span)
                found.setdefault(self.names()[name], text[span[0] : span[1]])
        return sorted(found.items())


@functools.cache
def skill_list(directory: Path | None = None) -> SkillList:
    d = directory or settings.skills_dir
    ontology = yaml.safe_load((d / "ontology.yaml").read_text()) or {}
    aliases = yaml.safe_load((d / "aliases.yaml").read_text()) or {}
    return SkillList(
        version=str(ontology.get("ontology_version", "0")),
        labels={
            str(sid): str((spec or {}).get("label") or sid)
            for sid, spec in (ontology.get("skills") or {}).items()
        },
        aliases={str(k).lower(): str(v) for k, v in (aliases.get("aliases") or {}).items()},
    )
