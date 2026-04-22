"""
Regression tests for the serializer's no-Infinity / no-NaN guarantee.

Flask's json writer (and Python's stdlib json with allow_nan=True, which is
the default) emits Infinity / -Infinity / NaN as bare tokens. Those tokens
are *not* valid JSON per RFC 8259, and JSON.parse in the browser throws on
them. When that happens in the optimizer polling path, the poll catch block
swallows the error silently and the UI hangs forever.

The serializer layer (serializers.py) now walks the payload and replaces any
non-finite float with None. These tests lock that down.
"""

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
import pytest

DESKTOP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DESKTOP))
sys.path.insert(0, str(DESKTOP / "gui" / "web"))

from serializers import (  # noqa: E402
    serialize_optimization_result,
    _finite_or_none,
)


# -----------------------------------------------------------------------------
# Fake result objects mimicking RedistributionResult / OptimizationResult
# enough to exercise the serializer's non-finite handling.
# -----------------------------------------------------------------------------

@dataclass
class FakeResult:
    success: bool = False
    best_time_s: float = float("inf")
    baseline_time_s: float = float("inf")
    improvement_ms: float = 0.0
    iterations: int = 0
    valid_samples: int = 0
    rejected_samples: int = 100
    segment_summary: list = None
    simulation_result: dict = None
    adjustments_W: List[float] = None

    def __post_init__(self):
        if self.segment_summary is None:
            self.segment_summary = []
        if self.simulation_result is None:
            self.simulation_result = {}
        if self.adjustments_W is None:
            self.adjustments_W = []


def _assert_serializes_to_strict_json(payload):
    """json.dumps with allow_nan=False is RFC-strict — will raise on inf/nan."""
    json.dumps(payload, allow_nan=False)


# -----------------------------------------------------------------------------
# _finite_or_none unit tests
# -----------------------------------------------------------------------------

def test_finite_or_none_scalars():
    assert _finite_or_none(1.5) == 1.5
    assert _finite_or_none(0) == 0
    assert _finite_or_none(float("inf")) is None
    assert _finite_or_none(float("-inf")) is None
    assert _finite_or_none(float("nan")) is None


def test_finite_or_none_numpy_scalars():
    assert _finite_or_none(np.float64(2.5)) == 2.5
    assert _finite_or_none(np.float64("inf")) is None
    assert _finite_or_none(np.float64("nan")) is None


def test_finite_or_none_nested():
    payload = {
        "a": [1.0, float("inf"), {"b": float("nan")}],
        "c": (float("-inf"), 2.0),
        "d": "keep-me",
    }
    out = _finite_or_none(payload)
    assert out["a"][0] == 1.0
    assert out["a"][1] is None
    assert out["a"][2]["b"] is None
    assert out["c"][0] is None
    assert out["c"][1] == 2.0
    assert out["d"] == "keep-me"
    _assert_serializes_to_strict_json(out)


# -----------------------------------------------------------------------------
# serialize_optimization_result guarantees
# -----------------------------------------------------------------------------

def test_failed_optimizer_result_never_emits_infinity():
    """success=False results have best_time_s=inf — this must not leak."""
    r = FakeResult(
        success=False,
        best_time_s=float("inf"),
        baseline_time_s=float("inf"),
        improvement_ms=0.0,
    )
    out = serialize_optimization_result(r)
    assert out["best_time_s"] is None
    assert out["baseline_time_s"] is None
    _assert_serializes_to_strict_json(out)


def test_successful_optimizer_result_preserves_finite_values():
    r = FakeResult(
        success=True,
        best_time_s=9.876,
        baseline_time_s=10.123,
        improvement_ms=247.0,
        valid_samples=42,
        rejected_samples=3,
        segment_summary=[{"name": "S1", "base_power_W": 500.0, "adjustment_W": 10.0}],
    )
    out = serialize_optimization_result(r)
    assert out["best_time_s"] == pytest.approx(9.876)
    assert out["baseline_time_s"] == pytest.approx(10.123)
    assert out["improvement_ms"] == pytest.approx(247.0)
    assert out["valid_samples"] == 42
    _assert_serializes_to_strict_json(out)


def test_nan_in_improvement_scrubbed():
    r = FakeResult(
        success=True,
        best_time_s=9.5,
        baseline_time_s=float("nan"),
        improvement_ms=float("nan"),
    )
    out = serialize_optimization_result(r)
    assert out["baseline_time_s"] is None
    assert out["improvement_ms"] is None
    _assert_serializes_to_strict_json(out)


def test_nested_nan_in_segment_summary_scrubbed():
    r = FakeResult(
        success=True,
        best_time_s=9.5,
        baseline_time_s=10.0,
        improvement_ms=500.0,
        segment_summary=[
            {"name": "S1", "base_power_W": 500.0, "adjustment_W": float("inf")},
            {"name": "S2", "base_power_W": float("nan"), "adjustment_W": 0.0},
        ],
    )
    out = serialize_optimization_result(r)
    assert out["segment_summary"][0]["adjustment_W"] is None
    assert out["segment_summary"][1]["base_power_W"] is None
    _assert_serializes_to_strict_json(out)
