"""Tests for the Spotprognos integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> dict[str, Any]:
    """Return a fresh copy of a fixture file, safe to modify in a test."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
