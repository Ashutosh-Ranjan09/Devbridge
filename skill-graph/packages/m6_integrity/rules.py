"""Loader for contracts/integrity-rules.yaml.

Same discipline as every other submodule: no threshold is written in Python, so
tuning a check is a contract edit and shows up in a diff of the contract.
"""
from __future__ import annotations

import functools
import pathlib
from typing import Any

import yaml

DEFAULT_RULES = (pathlib.Path(__file__).resolve().parents[2]
                 / "contracts" / "integrity-rules.yaml")


class IntegrityRules:
    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw
        self._checks = {c["id"]: c for c in raw["checks"]}

    @classmethod
    def load(cls, path: pathlib.Path | str | None = None) -> "IntegrityRules":
        return cls(yaml.safe_load(pathlib.Path(path or DEFAULT_RULES).read_text()))

    @property
    def contract_version(self) -> str:
        return str(self._raw["contract_version"])

    @property
    def check_ids(self) -> list[str]:
        return list(self._checks)

    def enabled(self, check_id: str) -> bool:
        """A check absent from the contract is off. Removing a check from the
        YAML must switch it off rather than leaving orphaned code running."""
        return check_id in self._checks

    def check(self, check_id: str) -> dict[str, Any]:
        return self._checks[check_id]

    def param(self, check_id: str, name: str, default: Any = None) -> Any:
        return self._checks.get(check_id, {}).get(name, default)

    def severity(self, check_id: str) -> str:
        return str(self._checks[check_id].get("severity", "notice"))

    def innocent_explanation(self, check_id: str) -> str:
        return " ".join(str(self._checks[check_id].get("innocent_explanation", "")).split())

    def what(self, check_id: str) -> str:
        return " ".join(str(self._checks[check_id].get("what", "")).split())

    @property
    def max_findings(self) -> int:
        return int((self._raw.get("reporting") or {}).get("max_findings", 40))

    @property
    def report_clean(self) -> bool:
        return bool((self._raw.get("reporting") or {}).get("always_report_clean", True))


@functools.lru_cache(maxsize=2)
def default_rules() -> IntegrityRules:
    return IntegrityRules.load()
