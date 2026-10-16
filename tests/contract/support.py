"""Shared helpers of the contract tests: fixtures and repository scripts, no external service needed."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
ORBIT_DIR = FIXTURES / "orbit"  # copy of ORBIT contracts/orbit
FAP_REQUEST_DIR = FIXTURES / "fap_request"  # copy of FORGE contracts/fap_request
FAP_RESPONSE_DIR = ROOT / "contracts" / "fap_response"  # source: what NOVA answers, written by test_fap_response_fixtures.py


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load(directory: Path, name: str) -> dict[str, Any]:
    return json.loads((directory / name).read_text(encoding="utf-8"))
