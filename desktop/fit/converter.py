"""
Flying 200 V2 - Time to Distance Converter

Convert time-based FIT data to distance-based profiles for simulation.
Uses cadence + gear ratio to calculate actual distance traveled.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .parser import FitRecord


# =============================================================================
# Gear Configuration
# =============================================================================

@dataclass
class GearConfig:
    """Gear configuration for distance calculation."""
    chainring: int = 55       # Teeth on chainring
    cog: int = 14             # Teeth on rear cog
    wheel_circumference_mm: int = 2096  # 700c x 23mm typical

    @property
    def gear_ratio(self) -> float:
        """Chainring/cog ratio."""
        return self.chainring / self.cog

    @property
    def wheel_circumference_m(self) -> float:
        """Wheel circumference in meters."""
        return self.wheel_circumference_mm / 1000.0

    @property
    def gear_inches(self) -> float:
        """Gear inches (for reference)."""
        return self.gear_ratio * 27  # Approximate for 700c

    def speed_from_cadence(self, cadence_rpm: float) -> float:
        """
        Calculate speed (m/s) from cadence.

        Speed = (cadence_rpm / 60) * gear_ratio * wheel_circumference
        """
        if cadence_rpm <= 0:
            return 0.0
        revs_per_second = cadence_rpm / 60.0
        return revs_per_second * self.gear_ratio * self.wheel_circumference_m


# Default configurations for common setups
GEAR_55_14 = GearConfig(55, 14, 2096)  # ~105.9 gear inches
GEAR_54_14 = GearConfig(54, 14, 2096)  # ~103.9 gear inches
GEAR_55_15 = GearConfig(55, 15, 2096)  # ~99.0 gear inches


# =============================================================================
# Distance Conversion Functions
# =============================================================================

@dataclass
class DistanceProfile:
    """Distance-based profile ready for simulation."""
    s_m: np.ndarray           # Distance along black line [m]
    elapsed_s: np.ndarray     # Time at each distance point [s]
    power_W: np.ndarray       # Power at each distance [W]
    cadence_rpm: np.ndarray   # Cadence at each distance [RPM]
    speed_mps: np.ndarray     # Speed at each distance [m/s]
    total_distance_m: float   # Total distance covered
    total_time_s: float       # Total time

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to pandas DataFrame."""
        return pd.DataFrame({
            's_m': self.s_m,
            'elapsed_s': self.elapsed_s,
            'P_W': self.power_W,
            'cadence_rpm': self.cadence_rpm,
            'speed_mps': self.speed_mps,
        })


def convert_time_to_distance(
    records: List[FitRecord],
    gear: GearConfig,
    use_fit_speed: bool = False,
    ds: float = 0.25,
    max_distance: Optional[float] = None,
) -> DistanceProfile:
    """
    Convert time-based FIT records to distance-based profile.

    Uses cadence + gear ratio to calculate speed, then integrates to get distance.

    Args:
        records: List of FIT records (time-ordered)
        gear: Gear configuration
        use_fit_speed: If True, use speed from FIT file instead of calculating
        ds: Distance step for output grid [m]
        max_distance: Maximum distance to output (None = all data)

    Returns:
        DistanceProfile with regular distance spacing
    """
    if not records:
        return DistanceProfile(
            s_m=np.array([]),
            elapsed_s=np.array([]),
            power_W=np.array([]),
            cadence_rpm=np.array([]),
            speed_mps=np.array([]),
            total_distance_m=0,
            total_time_s=0,
        )

    # Calculate speed and cumulative distance for each record
    speeds = []
    distances = []
    cumulative_dist = 0.0

    for i, rec in enumerate(records):
        # Calculate speed from cadence
        calc_speed = gear.speed_from_cadence(rec.cadence_rpm)

        # Use FIT speed if requested, or as fallback when cadence gives 0
        if use_fit_speed and rec.speed_kph > 0:
            speed = rec.speed_kph / 3.6  # Convert to m/s
        elif calc_speed > 0:
            speed = calc_speed
        elif rec.speed_kph > 0:
            speed = rec.speed_kph / 3.6  # Fallback to FIT speed when cadence is 0
        else:
            speed = 0.0

        speeds.append(speed)

        # Integrate to get distance
        if i > 0:
            dt = rec.elapsed_s - records[i-1].elapsed_s
            cumulative_dist += speed * dt

        distances.append(cumulative_dist)

    # Convert to numpy arrays
    time_arr = np.array([r.elapsed_s for r in records])
    power_arr = np.array([r.power_W for r in records])
    cadence_arr = np.array([r.cadence_rpm for r in records])
    speed_arr = np.array(speeds)
    dist_arr = np.array(distances)

    # Create regular distance grid
    total_distance = dist_arr[-1]
    if max_distance is not None:
        total_distance = min(total_distance, max_distance)

    s_grid = np.arange(0, total_distance + ds, ds)

    # Interpolate all quantities onto distance grid
    elapsed_interp = np.interp(s_grid, dist_arr, time_arr)
    power_interp = np.interp(s_grid, dist_arr, power_arr)
    cadence_interp = np.interp(s_grid, dist_arr, cadence_arr)
    speed_interp = np.interp(s_grid, dist_arr, speed_arr)

    return DistanceProfile(
        s_m=s_grid,
        elapsed_s=elapsed_interp,
        power_W=power_interp,
        cadence_rpm=cadence_interp,
        speed_mps=speed_interp,
        total_distance_m=total_distance,
        total_time_s=time_arr[-1] - time_arr[0],
    )


def align_to_finish_line(
    profile: DistanceProfile,
    finish_line_m: float = 895.0,
) -> DistanceProfile:
    """
    Align distance profile so it ends at the finish line.

    Flying 200 efforts END at the finish line. This function transforms
    the distance coordinates so that the last point is at the finish.

    s_m = finish_line_m - (total_distance - original_distance)

    Args:
        profile: Distance profile to align
        finish_line_m: Finish line position (default 895m for Flying 200)

    Returns:
        New profile with aligned distances
    """
    if profile.total_distance_m == 0:
        return profile

    # Calculate aligned distances
    # At end of profile, s_m = finish_line_m
    # At start of profile, s_m = finish_line_m - total_distance
    s_aligned = finish_line_m - (profile.total_distance_m - profile.s_m)

    return DistanceProfile(
        s_m=s_aligned,
        elapsed_s=profile.elapsed_s,
        power_W=profile.power_W,
        cadence_rpm=profile.cadence_rpm,
        speed_mps=profile.speed_mps,
        total_distance_m=profile.total_distance_m,
        total_time_s=profile.total_time_s,
    )


def extract_effort_profile(
    records: List[FitRecord],
    start_index: int,
    end_index: int,
    gear: GearConfig,
    align_to_finish: bool = True,
    finish_line_m: float = 895.0,
    ds: float = 0.25,
) -> DistanceProfile:
    """
    Extract and convert a specific effort to a distance profile.

    Convenience function combining segment extraction, conversion, and alignment.

    Args:
        records: Full list of FIT records
        start_index: Start index of effort
        end_index: End index of effort
        gear: Gear configuration
        align_to_finish: Align to finish line coordinates
        finish_line_m: Finish line position
        ds: Distance step

    Returns:
        Distance profile ready for simulation
    """
    # Extract effort records (copy to avoid mutating originals)
    import copy
    effort_records = [copy.copy(r) for r in records[start_index:end_index + 1]]

    # Reset elapsed time to start from 0
    if effort_records:
        start_time = effort_records[0].elapsed_s
        for rec in effort_records:
            rec.elapsed_s -= start_time

    # Convert to distance
    profile = convert_time_to_distance(effort_records, gear, ds=ds)

    # Align to finish line if requested
    if align_to_finish:
        profile = align_to_finish_line(profile, finish_line_m)

    return profile


def profile_to_simulation_input(
    profile: DistanceProfile,
    default_y_m: float = 0.0,
    default_CdA_m2: float = 0.22,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Convert distance profile to simulation input arrays.

    Adds default values for lateral position (y_m) and drag area (CdA)
    since FIT files don't contain this information.

    Args:
        profile: Distance profile from FIT conversion
        default_y_m: Default lateral position [m] (0 = black line)
        default_CdA_m2: Default drag area [m^2]

    Returns:
        Tuple of (s_grid, y_grid, CdA_grid, P_grid) ready for simulate_profile()
    """
    n = len(profile.s_m)

    return (
        profile.s_m,
        np.full(n, default_y_m),
        np.full(n, default_CdA_m2),
        profile.power_W,
    )
