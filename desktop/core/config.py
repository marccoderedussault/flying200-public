"""
Flying 200 V2 - Configuration Management

Handles loading and saving of:
- Default track positions (y_m values)
- Power curves (seated/standing)
- Environment parameters (rho, C_rr, mass)
- Aero defaults (CdA seated/standing, bend factor)
- Simulation parameters (ds, v0)
- User preferences

All default values are stored in flying200_config.json.
No hidden hardcoded fallbacks - the Config tab shows ALL defaults.
"""

import json
import os
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict


# Default config file path
CONFIG_FILENAME = "flying200_config.json"

# =============================================================================
# Built-in Defaults (used when no config file exists)
# =============================================================================

BUILTIN_DEFAULTS = {
    # Default y_m positions: a flat ride 2.5m off the black line for 895m.
    # The first-run fallback so simulations never silently produce y_m=0
    # (which would put the rider on the black line and skew aero/banking).
    "default_positions": {
        "raw_positions": {
            "lap0": [[0.0, 2.5], [223.75, 2.5], [447.5, 2.5], [671.25, 2.5], [895.0, 2.5]],
        },
    },
    # Environment parameters
    "environment": {
        "rho_kg_m3": 1.1627,       # Air density (velodrome standard)
        "c_rr": 0.0020,            # Rolling resistance coefficient
        "drivetrain_eff": 0.98,    # Drivetrain efficiency
        "rider_mass_kg": 92.0,     # Total system mass (rider + bike)
    },
    # Aero defaults
    "aero": {
        "CdA_seated": 0.24,        # CdA in seated position [m²]
        "CdA_standing": 0.38,      # CdA in standing position [m²]
        "CdA_bend_factor": 0.97,   # CdA multiplier for bends vs straights
    },
    # Simulation parameters
    "simulation": {
        "ds_m": 0.25,              # Grid resolution [m]
        "v0_m_s": 5.0,             # Initial velocity [m/s]
        "s_total_m": 895.0,        # Total simulation distance [m]
    },
    # Default track
    "track": {
        "default": "Bromont",      # Default track selection
    },
    # Gear settings for cadence calculation
    "gear": {
        "chainring": 55,           # Front chainring teeth
        "cog": 14,                 # Rear cog teeth
        "wheel_circumference": 2.10,  # Wheel circumference [m]
    },
    # Default power curves {duration_s: power_W}
    # Intervals: 1-15s in 1s increments, then 20,25,30,40,45,50,60,70,80,90s
    "power_curves": {
        "seated": {
            # 1-15 seconds in 1s intervals
            1: 1200, 2: 1170, 3: 1145, 4: 1125, 5: 1100,
            6: 1080, 7: 1060, 8: 1045, 9: 1030, 10: 1015,
            11: 1000, 12: 990, 13: 975, 14: 965, 15: 950,
            # Extended durations
            20: 920, 25: 895, 30: 870, 40: 830, 45: 815,
            50: 800, 60: 775, 70: 755, 80: 735, 90: 720,
        },
        "standing": {
            # 1-15 seconds in 1s intervals
            1: 1400, 2: 1365, 3: 1335, 4: 1310, 5: 1285,
            6: 1260, 7: 1240, 8: 1220, 9: 1200, 10: 1180,
            11: 1165, 12: 1150, 13: 1135, 14: 1120, 15: 1105,
            # Extended durations
            20: 1050, 25: 1010, 30: 975, 40: 920, 45: 895,
            50: 870, 60: 830, 70: 800, 80: 775, 90: 750,
        },
    },
}


def get_config_path() -> Path:
    """Get the path to the config file."""
    # Check multiple locations in order:
    # 1. Current package directory
    # 2. User's home directory
    # 3. Original flying200_package location

    # Try package directory first
    package_dir = Path(__file__).parent.parent
    package_config = package_dir / CONFIG_FILENAME
    if package_config.exists():
        return package_config

    # Try original package location
    original_config = Path(__file__).parent.parent.parent / "flying200_package" / CONFIG_FILENAME
    if original_config.exists():
        return original_config

    # Default to package directory (will be created if needed)
    return package_config


def load_config() -> Optional[Dict]:
    """
    Load configuration from flying200_config.json.

    On first run (file missing) the BUILTIN_DEFAULTS are materialized to disk so
    the user gets a sane editable config rather than the codebase silently falling
    back to an empty profile (which historically produced y_m=0 sims).

    Returns:
        Config dictionary, or None only if the file exists but is corrupted JSON
        (corrupt config is surfaced — never silently masked).
    """
    config_path = get_config_path()
    if not config_path.exists():
        save_config(BUILTIN_DEFAULTS)
        return dict(BUILTIN_DEFAULTS)
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def save_config(config: Dict) -> None:
    """
    Save configuration to flying200_config.json.

    Args:
        config: Configuration dictionary to save
    """
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)


def get_default_positions() -> Dict[str, List[Tuple[float, float]]]:
    """
    Load default track positions (y_m values) from config.

    Returns:
        Dictionary mapping lap key to list of (s_m, y_m) tuples.
        Example: {"lap0": [(0.0, 2.5), (10.0, 2.5), ...], "lap1": [...], ...}
    """
    config = load_config()
    if config is None:
        return {}

    raw_positions = config.get("default_positions", {}).get("raw_positions", {})
    result = {}
    for lap_key, pos_list in raw_positions.items():
        result[lap_key] = [(float(s), float(y)) for s, y in pos_list]
    return result


def get_default_y_profile() -> Tuple[np.ndarray, np.ndarray]:
    """
    Get default y_m profile as numpy arrays suitable for simulation.

    Returns:
        (s_m array, y_m array) - sorted by distance
    """
    positions = get_default_positions()
    if not positions:
        # Last-resort fallback if config is corrupted: 2.5m off the black line for the
        # full 895m. Never return y_m=0 (which puts the rider on the line, breaking aero
        # and banking calculations and silently corrupting all downstream simulations).
        return np.array([0.0, 895.0]), np.array([2.5, 2.5])

    # Combine all laps into single sorted arrays
    all_points = []
    for lap_key, pos_list in positions.items():
        all_points.extend(pos_list)

    # Sort by s_m and remove duplicates (keep last value for each s_m)
    point_dict = {}
    for s, y in all_points:
        point_dict[s] = y

    s_sorted = sorted(point_dict.keys())
    s_m = np.array(s_sorted)
    y_m = np.array([point_dict[s] for s in s_sorted])

    return s_m, y_m


def interpolate_y_to_grid(s_grid: np.ndarray) -> np.ndarray:
    """
    Interpolate default y_m values to a given distance grid.

    Args:
        s_grid: Distance grid to interpolate onto

    Returns:
        y_m values interpolated to the grid
    """
    s_default, y_default = get_default_y_profile()
    return np.interp(s_grid, s_default, y_default)


def save_positions_to_config(positions: Dict[str, List[Tuple[float, float]]]) -> None:
    """
    Save track positions to config file.

    Args:
        positions: Dictionary mapping lap key to list of (s_m, y_m) tuples
    """
    config = load_config()
    if config is None:
        config = {"default_positions": {}}

    # Convert to JSON-serializable format
    raw_positions = {}
    for lap_key, pos_list in positions.items():
        raw_positions[lap_key] = [[float(s), float(y)] for s, y in pos_list]

    config["default_positions"] = {"raw_positions": raw_positions}
    save_config(config)


# =============================================================================
# Power Curves Configuration
# =============================================================================

def get_default_power_curves() -> Optional[Dict[str, Dict[int, float]]]:
    """
    Load default power curves from config.

    Returns:
        Dictionary with "seated" and "standing" keys, each mapping
        duration (seconds) to power (watts), or None if not configured.
    """
    config = load_config()
    if config is None:
        return None

    power_config = config.get("power_curves", {})
    if not power_config:
        return None

    return {
        "seated": power_config.get("seated", {}),
        "standing": power_config.get("standing", {}),
    }


def save_power_curves_to_config(
    seated: Dict[int, float],
    standing: Dict[int, float],
) -> None:
    """
    Save power curves to config file.

    Args:
        seated: {duration_s: power_W} for seated position
        standing: {duration_s: power_W} for standing position
    """
    config = load_config()
    if config is None:
        config = {}

    config["power_curves"] = {
        "seated": {int(k): float(v) for k, v in seated.items()},
        "standing": {int(k): float(v) for k, v in standing.items()},
    }
    save_config(config)


# =============================================================================
# Config Summary
# =============================================================================

def get_config_summary() -> str:
    """Get a human-readable summary of the current config."""
    config = load_config()
    if config is None:
        return "No config file found"

    lines = [f"Config file: {get_config_path()}"]

    # Track positions
    positions = config.get("default_positions", {}).get("raw_positions", {})
    if positions:
        total_points = sum(len(v) for v in positions.values())
        lines.append(f"Track positions: {total_points} points across {len(positions)} laps")
    else:
        lines.append("Track positions: (none)")

    # Power curves
    power = config.get("power_curves", {})
    if power:
        seated_count = len(power.get("seated", {}))
        standing_count = len(power.get("standing", {}))
        lines.append(f"Power curves: {seated_count} seated, {standing_count} standing points")
    else:
        lines.append("Power curves: (none)")

    return "\n".join(lines)


# =============================================================================
# Environment Parameters
# =============================================================================

def get_environment_defaults() -> Dict[str, float]:
    """Get default environment parameters.

    Returns:
        Dict with keys: rho_kg_m3, c_rr, drivetrain_eff, rider_mass_kg
    """
    config = load_config()
    if config is None:
        return BUILTIN_DEFAULTS["environment"].copy()

    return config.get("environment", BUILTIN_DEFAULTS["environment"].copy())


def save_environment_defaults(params: Dict[str, float]) -> None:
    """Save environment parameters to config.

    Args:
        params: Dict with rho_kg_m3, c_rr, drivetrain_eff, rider_mass_kg
    """
    config = load_config() or {}
    config["environment"] = {
        "rho_kg_m3": float(params.get("rho_kg_m3", BUILTIN_DEFAULTS["environment"]["rho_kg_m3"])),
        "c_rr": float(params.get("c_rr", BUILTIN_DEFAULTS["environment"]["c_rr"])),
        "drivetrain_eff": float(params.get("drivetrain_eff", BUILTIN_DEFAULTS["environment"]["drivetrain_eff"])),
        "rider_mass_kg": float(params.get("rider_mass_kg", BUILTIN_DEFAULTS["environment"]["rider_mass_kg"])),
    }
    save_config(config)


# =============================================================================
# Aero Defaults
# =============================================================================

def get_aero_defaults() -> Dict[str, float]:
    """Get default aero parameters.

    Returns:
        Dict with keys: CdA_seated, CdA_standing, CdA_bend_factor
    """
    config = load_config()
    if config is None:
        return BUILTIN_DEFAULTS["aero"].copy()

    return config.get("aero", BUILTIN_DEFAULTS["aero"].copy())


def save_aero_defaults(params: Dict[str, float]) -> None:
    """Save aero parameters to config.

    Args:
        params: Dict with CdA_seated, CdA_standing, CdA_bend_factor
    """
    config = load_config() or {}
    config["aero"] = {
        "CdA_seated": float(params.get("CdA_seated", BUILTIN_DEFAULTS["aero"]["CdA_seated"])),
        "CdA_standing": float(params.get("CdA_standing", BUILTIN_DEFAULTS["aero"]["CdA_standing"])),
        "CdA_bend_factor": float(params.get("CdA_bend_factor", BUILTIN_DEFAULTS["aero"]["CdA_bend_factor"])),
    }
    save_config(config)


# =============================================================================
# Simulation Parameters
# =============================================================================

def get_simulation_defaults() -> Dict[str, float]:
    """Get default simulation parameters.

    Returns:
        Dict with keys: ds_m, v0_m_s, s_total_m
    """
    config = load_config()
    if config is None:
        return BUILTIN_DEFAULTS["simulation"].copy()

    return config.get("simulation", BUILTIN_DEFAULTS["simulation"].copy())


def save_simulation_defaults(params: Dict[str, float]) -> None:
    """Save simulation parameters to config.

    Args:
        params: Dict with ds_m, v0_m_s, s_total_m
    """
    config = load_config() or {}
    config["simulation"] = {
        "ds_m": float(params.get("ds_m", BUILTIN_DEFAULTS["simulation"]["ds_m"])),
        "v0_m_s": float(params.get("v0_m_s", BUILTIN_DEFAULTS["simulation"]["v0_m_s"])),
        "s_total_m": float(params.get("s_total_m", BUILTIN_DEFAULTS["simulation"]["s_total_m"])),
    }
    save_config(config)


# =============================================================================
# Track Defaults
# =============================================================================

def get_default_track() -> str:
    """Get default track name.

    Returns:
        Track name string (e.g., "Bromont", "Milton", "Konya")
    """
    config = load_config()
    if config is None:
        return BUILTIN_DEFAULTS["track"]["default"]

    return config.get("track", {}).get("default", BUILTIN_DEFAULTS["track"]["default"])


def save_default_track(track_name: str) -> None:
    """Save default track to config.

    Args:
        track_name: Track name string
    """
    config = load_config() or {}
    if "track" not in config:
        config["track"] = {}
    config["track"]["default"] = track_name
    save_config(config)


# =============================================================================
# Combined Defaults for GUI
# =============================================================================

def get_all_defaults() -> Dict[str, Any]:
    """Get all default values in a single dict.

    Returns:
        Dict with all configuration categories
    """
    return {
        "environment": get_environment_defaults(),
        "aero": get_aero_defaults(),
        "simulation": get_simulation_defaults(),
        "track": get_default_track(),
        "power_curves": get_default_power_curves() or BUILTIN_DEFAULTS["power_curves"],
    }


def reset_to_builtin_defaults() -> None:
    """Reset all configuration to built-in defaults."""
    config = load_config() or {}
    config["environment"] = BUILTIN_DEFAULTS["environment"].copy()
    config["aero"] = BUILTIN_DEFAULTS["aero"].copy()
    config["simulation"] = BUILTIN_DEFAULTS["simulation"].copy()
    config["track"] = BUILTIN_DEFAULTS["track"].copy()
    config["power_curves"] = BUILTIN_DEFAULTS["power_curves"].copy()
    config["gear"] = BUILTIN_DEFAULTS["gear"].copy()
    save_config(config)
