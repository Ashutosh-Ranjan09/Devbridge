#!/usr/bin/env python3
"""Zero-dependency test runner.

`pytest tests/` works on the same files once pytest is installed; this exists so
the suite is runnable today, and in CI before the environment is provisioned.

    python3 tests/run.py [substring-filter]
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import traceback

HERE = pathlib.Path(__file__).resolve().parent


def check_helper_names() -> None:
    """Two test packages must not both define a module of the same name.

    Test files import their siblings by bare name, so the first `helpers` to be
    imported wins for the whole run and the second package silently tests against
    the wrong fixtures. Failing loudly here beats debugging that later.
    """
    seen: dict[str, pathlib.Path] = {}
    for path in sorted(HERE.rglob("*.py")):
        if path.name in ("run.py", "__init__.py") or path.stem.startswith("test_"):
            continue
        if path.stem in seen:
            raise SystemExit(
                f"helper name collision: {path} and {seen[path.stem]} are both "
                f"imported as `{path.stem}`. Give one of them a unique name.")
        seen[path.stem] = path


def load(path: pathlib.Path):
    # test modules import their sibling helper module, which also bootstraps
    # packages/ onto sys.path
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str]) -> int:
    keep = argv[1] if len(argv) > 1 else ""
    check_helper_names()
    passed = failed = 0
    failures: list[tuple[str, str]] = []
    for path in sorted(HERE.rglob("test_*.py")):
        mod = load(path)
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            if keep and keep not in f"{path.stem}::{name}":
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn()
                passed += 1
                print(f"  \033[32m✓\033[0m {path.stem}::{name}")
            except Exception:
                failed += 1
                failures.append((f"{path.stem}::{name}", traceback.format_exc()))
                print(f"  \033[31m✗\033[0m {path.stem}::{name}")
    for name, tb in failures:
        print(f"\n\033[31m─── {name} ───\033[0m\n{tb}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
