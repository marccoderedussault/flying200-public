"""
Regression tests for PowerRedistributionOptimizer fixes:

  A1. Effective power ceiling is max(power_curve(1s), 1.05 * baseline_peak) so
      single-grid-point baseline spikes don't auto-reject every sample.
  A2. generate_zero_sum_adjustments() absorbs discretization residual into one
      segment so validate_adjustments() no longer trips the zero-sum check.

Also asserts the end-to-end "random search" path finds at least one valid
sample on a realistic baseline that used to reject 100%.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

# Make `optimizer`, `core`, `tracks` importable regardless of where pytest runs.
DESKTOP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DESKTOP))

from optimizer.power_redistribution import PowerRedistributionOptimizer  # noqa: E402
from core.physics import (  # noqa: E402
    simulate_profile,
    SimulationConfig,
    create_simulation_grid,
    theta_track_blackline,
    S_OFFSET,
)
from core.track import DEFAULT_TRACK  # noqa: E402


def _theta_grid(s_grid):
    return np.array([theta_track_blackline(s + S_OFFSET) for s in s_grid])


# -----------------------------------------------------------------------------
# Shared fixture: a baseline that mimics a FIT-imported sprint profile, with
# one 1400W spike above the 1s power-curve ceiling (1200W). This is what
# caused the PR optimizer to reject 100% of samples in the user's flow.
# -----------------------------------------------------------------------------

@pytest.fixture
def spiky_baseline():
    s_grid = create_simulation_grid(ds=0.25)

    # Approach: ~250W with oscillation. Sprint: ramps to ~1100W, with one
    # isolated 1400W spike deep in the sprint (index chosen post hoc).
    P = np.where(
        s_grid < 695,
        250.0 + 50.0 * np.sin(s_grid / 30.0),
        1000.0 + 100.0 * np.sin(s_grid / 20.0),
    )
    spike_idx = int(np.argmin(np.abs(s_grid - 545.0)))
    P[spike_idx] = 1400.0

    y_grid = np.where(s_grid < 500, 7.5, 2.5)
    CdA_grid = np.full_like(s_grid, 0.24)
    track = DEFAULT_TRACK
    theta_grid = _theta_grid(s_grid)

    cfg = SimulationConfig(
        mass_kg=92.0, rho_kg_m3=1.1627, c_rr=0.002,
        v0_m_s=5.0, ds_m=0.25, drivetrain_efficiency=0.98,
    )

    def sim_func(y, CdA, P_arr, params, s, theta, label):
        r = simulate_profile(s, y, CdA, P_arr, cfg, track_geometry=track)
        return {
            "T_200": float(r.T_200),
            "v": r.v,
            "s": r.s_grid,
            "y": y,
            "P": P_arr,
        }

    # Constant power curve: 1s => 1200W (the old hard ceiling).
    power_curve = lambda t: 1200.0  # noqa: E731

    return dict(
        s_grid=s_grid, y_grid=y_grid, CdA_grid=CdA_grid, P_grid=P,
        theta_grid=theta_grid, track=track, sim_func=sim_func,
        power_curve=power_curve,
    )


# -----------------------------------------------------------------------------
# A1. Ceiling fix
# -----------------------------------------------------------------------------

def test_effective_ceiling_accounts_for_baseline_peak(spiky_baseline):
    """A1: ceiling must float above baseline peak so spikes don't auto-reject."""
    opt = PowerRedistributionOptimizer(
        simulate_func=spiky_baseline["sim_func"],
        params={},
        s_grid=spiky_baseline["s_grid"],
        theta_grid=spiky_baseline["theta_grid"],
        y_grid=spiky_baseline["y_grid"],
        CdA_grid=spiky_baseline["CdA_grid"],
        P_baseline=spiky_baseline["P_grid"],
        power_curve_func=spiky_baseline["power_curve"],
        track_geometry=spiky_baseline["track"],
    )

    baseline_peak = float(np.max(spiky_baseline["P_grid"]))
    curve_ceiling = spiky_baseline["power_curve"](1.0)

    # Baseline peak (1400W) > curve ceiling (1200W): effective ceiling must
    # lift to at least 1.05 * peak.
    assert opt.effective_ceiling_W >= baseline_peak * 1.05 - 1e-6
    assert opt.effective_ceiling_W >= curve_ceiling


def test_effective_ceiling_uses_curve_when_baseline_is_conservative():
    """When baseline is below the curve, the curve sets the ceiling."""
    s_grid = create_simulation_grid(ds=0.25)
    P = np.full_like(s_grid, 600.0)  # well below 1200W
    y_grid = np.full_like(s_grid, 5.0)
    CdA_grid = np.full_like(s_grid, 0.24)
    track = DEFAULT_TRACK
    theta_grid = _theta_grid(s_grid)

    def sim_func(*args, **kwargs):
        return {"T_200": 10.0}

    opt = PowerRedistributionOptimizer(
        simulate_func=sim_func, params={},
        s_grid=s_grid, theta_grid=theta_grid,
        y_grid=y_grid, CdA_grid=CdA_grid,
        P_baseline=P,
        power_curve_func=lambda t: 1200.0,
        track_geometry=track,
    )

    # 1.05 * 600 = 630 < 1200, so the curve wins.
    assert opt.effective_ceiling_W == pytest.approx(1200.0)


# -----------------------------------------------------------------------------
# A2. Zero-sum correction fix
# -----------------------------------------------------------------------------

def test_generate_zero_sum_adjustments_sum_to_zero(spiky_baseline):
    """Every accepted adjustment vector must sum to zero within float tolerance."""
    opt = PowerRedistributionOptimizer(
        simulate_func=spiky_baseline["sim_func"], params={},
        s_grid=spiky_baseline["s_grid"], theta_grid=spiky_baseline["theta_grid"],
        y_grid=spiky_baseline["y_grid"], CdA_grid=spiky_baseline["CdA_grid"],
        P_baseline=spiky_baseline["P_grid"],
        power_curve_func=spiky_baseline["power_curve"],
        track_geometry=spiky_baseline["track"],
        power_increment_W=10.0, max_adjustment_W=100.0,
    )

    rng = np.random.default_rng(0)
    np.random.seed(0)

    non_none = 0
    for _ in range(500):
        adj = opt.generate_zero_sum_adjustments()
        if adj is None:
            continue
        non_none += 1
        total = float(sum(adj))
        assert abs(total) < 0.5, f"adjustments sum to {total:.3f}W, expected ~0"

    # Sanity: we must be producing *some* non-None samples out of 500.
    assert non_none > 10, f"only {non_none}/500 samples survived bounds check"


def test_validate_adjustments_accepts_zero_sum_output(spiky_baseline):
    """Every non-None generate_*() output must pass validate_*()'s zero-sum gate."""
    opt = PowerRedistributionOptimizer(
        simulate_func=spiky_baseline["sim_func"], params={},
        s_grid=spiky_baseline["s_grid"], theta_grid=spiky_baseline["theta_grid"],
        y_grid=spiky_baseline["y_grid"], CdA_grid=spiky_baseline["CdA_grid"],
        P_baseline=spiky_baseline["P_grid"],
        power_curve_func=spiky_baseline["power_curve"],
        track_geometry=spiky_baseline["track"],
        power_increment_W=10.0, max_adjustment_W=100.0,
        min_power_fraction=0.1,  # relax the floor so we isolate the zero-sum gate
    )

    np.random.seed(1)
    sum_rejects = 0
    for _ in range(300):
        adj = opt.generate_zero_sum_adjustments()
        if adj is None:
            continue
        ok, err = opt.validate_adjustments(adj)
        if not ok and err and "not zero" in err:
            sum_rejects += 1

    assert sum_rejects == 0, f"{sum_rejects} samples failed the zero-sum check"


# -----------------------------------------------------------------------------
# End-to-end: the fixes should unblock the random search so at least one
# sample succeeds on a realistic spiky baseline.
# -----------------------------------------------------------------------------

def test_random_search_finds_valid_sample(spiky_baseline):
    """After both fixes, 100-sample random search must land >=1 valid sample."""
    np.random.seed(42)
    opt = PowerRedistributionOptimizer(
        simulate_func=spiky_baseline["sim_func"], params={},
        s_grid=spiky_baseline["s_grid"], theta_grid=spiky_baseline["theta_grid"],
        y_grid=spiky_baseline["y_grid"], CdA_grid=spiky_baseline["CdA_grid"],
        P_baseline=spiky_baseline["P_grid"],
        power_curve_func=spiky_baseline["power_curve"],
        track_geometry=spiky_baseline["track"],
        optimization_start_m=430.0,
        segment_length_m=15.0,
        min_power_fraction=0.5,
        max_adjustment_W=100.0,
    )
    result = opt.optimize_random(n_samples=100)

    assert result.valid_samples >= 1, (
        f"random search found no valid samples "
        f"(valid={result.valid_samples}, rejected={result.rejected_samples})"
    )
    assert result.success is True
    assert np.isfinite(result.best_time_s)
