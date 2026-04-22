"""
Flying 200 V2 - Track Cycling Simulation Package

A complete toolkit for Flying 200m time optimization with:
- Validated physics engine (10-30ms accuracy)
- Named track segments (no more "695m" confusion)
- Clear session management (always know what you're simulating)
- Auto-detect FIT file analysis
- Professional visualization

Quick Start:
    from flying200_v2 import Session, simulate_profile

    session = Session()
    session.load_profile("profile.csv")
    session.load_power_curves_from_csv("power_curves.csv")

    result = simulate_profile(session)
    print(f"200m time: {result.T_200:.3f}s")

Run GUI:
    python -m flying200_v2
"""

__version__ = "2.0.0"
__author__ = "Flying 200 Team"

# Core exports
from .core import (
    simulate_profile,
    SimulationResult,
    SimulationConfig,
    Session,
    BROMONT_250M,
    MILTON_250M,
    AVAILABLE_TRACKS,
    get_segment_name,
)

# FIT exports
from .fit import (
    parse_fit_file,
    FitFileData,
    FitRecord,
    detect_flying_efforts,
    DetectedEffort,
    convert_time_to_distance,
    GearConfig,
)

# Optimizer exports
from .optimizer import (
    EnergyBudgetOptimizer,
    OptimizationResult,
    PowerRedistributionOptimizer,
)

__all__ = [
    # Physics
    "simulate_profile",
    "SimulationResult",
    "SimulationConfig",
    # Session
    "Session",
    # Tracks
    "BROMONT_250M",
    "MILTON_250M",
    "AVAILABLE_TRACKS",
    "get_segment_name",
    # FIT
    "parse_fit_file",
    "FitFileData",
    "FitRecord",
    "detect_flying_efforts",
    "DetectedEffort",
    "convert_time_to_distance",
    "GearConfig",
    # Optimizer
    "EnergyBudgetOptimizer",
    "OptimizationResult",
    "PowerRedistributionOptimizer",
]
