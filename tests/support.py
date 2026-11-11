"""Imports the plugin as the `glance` package, the way Hermes loads it, from any working directory."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def load_glance():
    if "glance" not in sys.modules:
        spec = importlib.util.spec_from_file_location("glance", ROOT / "__init__.py",
                                                      submodule_search_locations=[str(ROOT)])
        module = importlib.util.module_from_spec(spec)
        sys.modules["glance"] = module
        spec.loader.exec_module(module)
    return sys.modules["glance"]


def fixture_cases() -> list[dict]:
    return json.loads((FIXTURES / "cases.json").read_text())
