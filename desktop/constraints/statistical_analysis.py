"""
Statistical Analysis for Power-Cadence Constraints

Compute statistics for cadence bins including mean, std, percentiles,
and confidence intervals.
"""

from collections import defaultdict
from datetime import date, datetime
from typing import List, Dict, Optional, Tuple
import math

import numpy as np
from scipy import stats as scipy_stats

try:
    from .models import (
        PowerCadenceObservation,
        CadenceBinStats,
        DurationPowerStats,
        GearConstraintProfile,
        ConstraintDataSet,
        GearConfig,
        STANDARD_DURATIONS,
    )
except ImportError:
    from models import (
        PowerCadenceObservation,
        CadenceBinStats,
        DurationPowerStats,
        GearConstraintProfile,
        ConstraintDataSet,
        GearConfig,
        STANDARD_DURATIONS,
    )


class CadenceBinAnalyzer:
    """
    Analyze power-cadence data and compute statistics per cadence bin.

    Bins cadence values into groups (e.g., 5 RPM bins: 100-104, 105-109)
    and computes statistics for each bin.
    """

    def __init__(
        self,
        bin_size: int = 5,
        min_samples: int = 3,
        min_cadence: int = 50,
        max_cadence: int = 180,
    ):
        """
        Initialize the analyzer.

        Args:
            bin_size: Width of cadence bins in RPM (default 5)
            min_samples: Minimum samples required per bin (default 3)
            min_cadence: Minimum cadence to analyze (default 50)
            max_cadence: Maximum cadence to analyze (default 180)
        """
        self.bin_size = bin_size
        self.min_samples = min_samples
        self.min_cadence = min_cadence
        self.max_cadence = max_cadence

    def bin_cadence(self, cadence_rpm: float) -> int:
        """
        Assign cadence to a bin.

        E.g., with bin_size=5: 102 -> 100, 107 -> 105

        Args:
            cadence_rpm: Cadence value in RPM

        Returns:
            Bin start value
        """
        return int((cadence_rpm // self.bin_size) * self.bin_size)

    def compute_bin_stats(
        self,
        observations: List[PowerCadenceObservation],
        gear_ratio_str: str,
    ) -> List[CadenceBinStats]:
        """
        Compute statistics for each cadence bin.

        Args:
            observations: List of power-cadence observations
            gear_ratio_str: Gear ratio string to filter by

        Returns:
            List of CadenceBinStats, one per bin with sufficient data
        """
        # Filter to this gear ratio
        gear_obs = [o for o in observations if o.gear_ratio_str == gear_ratio_str]

        if not gear_obs:
            return []

        # Group observations by cadence bin
        bins: Dict[int, List[PowerCadenceObservation]] = defaultdict(list)
        for obs in gear_obs:
            if self.min_cadence <= obs.cadence_rpm <= self.max_cadence:
                bin_key = self.bin_cadence(obs.cadence_rpm)
                bins[bin_key].append(obs)

        # Compute statistics for each bin
        results = []
        gear_ratio = gear_obs[0].gear_ratio  # All same gear

        for bin_start in sorted(bins.keys()):
            bin_obs = bins[bin_start]

            if len(bin_obs) < self.min_samples:
                continue

            stats = self._compute_stats_for_bin(
                bin_obs,
                gear_ratio_str,
                gear_ratio,
                bin_start,
            )
            results.append(stats)

        return results

    def _compute_stats_for_bin(
        self,
        observations: List[PowerCadenceObservation],
        gear_ratio_str: str,
        gear_ratio: float,
        bin_start: int,
    ) -> CadenceBinStats:
        """Compute statistics for a single cadence bin."""
        powers = np.array([o.power_W for o in observations])
        torques = np.array([o.torque_Nm for o in observations])
        effort_ids = set(o.effort_id for o in observations)

        n = len(powers)

        # Basic statistics
        mean_power = float(np.mean(powers))
        std_power = float(np.std(powers, ddof=1)) if n > 1 else 0.0

        # Percentiles
        p90 = float(np.percentile(powers, 90))
        p95 = float(np.percentile(powers, 95))

        # 95% confidence interval on the mean
        if n > 1:
            sem = scipy_stats.sem(powers)
            t_crit = scipy_stats.t.ppf(0.975, n - 1)  # 97.5th percentile for 95% CI
            ci_margin = sem * t_crit
            ci_low = mean_power - ci_margin
            ci_high = mean_power + ci_margin
        else:
            ci_low = mean_power
            ci_high = mean_power

        # Torque statistics
        mean_torque = float(np.mean(torques))
        std_torque = float(np.std(torques, ddof=1)) if n > 1 else 0.0
        max_torque = float(np.max(torques))

        # Duration-based power statistics (MMP for 1s, 2s, 3s, 5s, 10s, 15s, 20s, 30s)
        power_by_duration = self._compute_duration_power_stats(
            observations, effort_ids, bin_start
        )

        return CadenceBinStats(
            gear_ratio_str=gear_ratio_str,
            gear_ratio=gear_ratio,
            cadence_bin=bin_start,
            cadence_bin_size=self.bin_size,
            n_samples=n,
            n_efforts=len(effort_ids),
            mean_power_W=mean_power,
            std_power_W=std_power,
            min_power_W=float(np.min(powers)),
            max_power_W=float(np.max(powers)),
            median_power_W=float(np.median(powers)),
            p90_power_W=p90,
            p95_power_W=p95,
            ci_low_W=ci_low,
            ci_high_W=ci_high,
            mean_torque_Nm=mean_torque,
            std_torque_Nm=std_torque,
            max_torque_Nm=max_torque,
            power_by_duration=power_by_duration,
        )

    def _compute_duration_power_stats(
        self,
        observations: List[PowerCadenceObservation],
        effort_ids: set,
        bin_start: int,
    ) -> Dict[int, DurationPowerStats]:
        """
        Compute duration-based power statistics (MMP) for the cadence bin.

        For each standard duration (1s, 2s, 3s, 5s, 10s, 15s, 20s, 30s),
        compute the maximum mean power achievable while cadence is in this bin.

        Args:
            observations: Observations in this cadence bin
            effort_ids: Set of effort IDs
            bin_start: Start of cadence bin

        Returns:
            Dict mapping duration_s -> DurationPowerStats
        """
        power_by_duration = {}
        bin_end = bin_start + self.bin_size

        for duration_s in STANDARD_DURATIONS:
            # Collect MMP values for this duration from each effort
            effort_mmp_values = []

            for effort_id in effort_ids:
                # Get observations for this effort, sorted by time
                effort_obs = sorted(
                    [o for o in observations if o.effort_id == effort_id],
                    key=lambda x: x.timestamp_s
                )

                if len(effort_obs) < duration_s:
                    # Not enough samples for this duration
                    continue

                # Find contiguous segments where cadence is in bin
                # and compute rolling MMP for each segment
                mmp = self._compute_mmp_for_effort_in_bin(
                    effort_obs, duration_s, bin_start, bin_end
                )

                if mmp is not None:
                    effort_mmp_values.append(mmp)

            # Aggregate across efforts
            if effort_mmp_values:
                values = np.array(effort_mmp_values)
                power_by_duration[duration_s] = DurationPowerStats(
                    duration_s=duration_s,
                    max_power_W=float(np.max(values)),
                    mean_power_W=float(np.mean(values)),
                    std_power_W=float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                    p95_power_W=float(np.percentile(values, 95)) if len(values) >= 2 else float(np.max(values)),
                    n_efforts=len(effort_mmp_values),
                )

        return power_by_duration

    def _compute_mmp_for_effort_in_bin(
        self,
        effort_obs: List[PowerCadenceObservation],
        duration_s: int,
        bin_start: int,
        bin_end: int,
    ) -> Optional[float]:
        """
        Compute MMP for a duration where cadence stays within the bin.

        Finds contiguous segments (allowing 1s gaps) where cadence is in range,
        then computes rolling MMP for valid segments.

        Args:
            effort_obs: Sorted observations for this effort
            duration_s: Target duration in seconds
            bin_start: Cadence bin start
            bin_end: Cadence bin end

        Returns:
            Maximum mean power for this duration, or None if insufficient data
        """
        if len(effort_obs) < duration_s:
            return None

        # Build time series with timestamps
        times = np.array([o.timestamp_s for o in effort_obs])
        powers = np.array([o.power_W for o in effort_obs])

        # Find segments where samples are roughly 1 second apart
        # (allowing for small gaps due to recording variations)
        segments = []
        seg_start = 0

        for i in range(1, len(times)):
            time_gap = times[i] - times[i-1]
            # If gap > 2 seconds, start new segment
            if time_gap > 2.0:
                if i - seg_start >= duration_s:
                    segments.append((seg_start, i))
                seg_start = i

        # Add final segment
        if len(times) - seg_start >= duration_s:
            segments.append((seg_start, len(times)))

        # Compute MMP for each segment
        max_mmp = None

        for seg_start, seg_end in segments:
            seg_powers = powers[seg_start:seg_end]

            if len(seg_powers) < duration_s:
                continue

            # Rolling mean with window = duration_s
            rolling_mean = np.convolve(
                seg_powers,
                np.ones(duration_s) / duration_s,
                mode='valid'
            )

            if len(rolling_mean) > 0:
                seg_mmp = float(np.max(rolling_mean))
                if max_mmp is None or seg_mmp > max_mmp:
                    max_mmp = seg_mmp

        return max_mmp

    def build_gear_profile(
        self,
        observations: List[PowerCadenceObservation],
        gear_ratio_str: str,
        gear_config: Optional[GearConfig] = None,
    ) -> GearConstraintProfile:
        """
        Build a complete constraint profile for a gear ratio.

        Args:
            observations: All observations (will be filtered to gear)
            gear_ratio_str: Gear ratio string (e.g., "55/12")
            gear_config: Optional GearConfig for chainring/cog info

        Returns:
            Complete GearConstraintProfile
        """
        # Filter observations to this gear
        gear_obs = [o for o in observations if o.gear_ratio_str == gear_ratio_str]

        if not gear_obs:
            raise ValueError(f"No observations for gear {gear_ratio_str}")

        # Compute bin statistics
        bins = self.compute_bin_stats(observations, gear_ratio_str)

        # Extract gear info
        gear_ratio = gear_obs[0].gear_ratio
        if gear_config:
            chainring = gear_config.chainring
            cog = gear_config.cog
        else:
            # Parse from string
            parts = gear_ratio_str.split('/')
            chainring = int(parts[0])
            cog = int(parts[1])

        # Get date range
        dates = [o.source_date for o in gear_obs]
        date_range = (min(dates), max(dates))

        # Count unique efforts
        effort_ids = set(o.effort_id for o in gear_obs)

        return GearConstraintProfile(
            gear_ratio_str=gear_ratio_str,
            gear_ratio=gear_ratio,
            chainring=chainring,
            cog=cog,
            bins=bins,
            n_total_observations=len(gear_obs),
            n_efforts=len(effort_ids),
            date_range=date_range,
            last_updated=datetime.now(),
        )

    def build_all_profiles(
        self,
        observations: List[PowerCadenceObservation],
    ) -> ConstraintDataSet:
        """
        Build constraint profiles for all gear ratios in the data.

        Args:
            observations: All collected observations

        Returns:
            ConstraintDataSet with profiles for each gear
        """
        # Get unique gear ratios
        gear_ratios = sorted(set(o.gear_ratio_str for o in observations))

        profiles = {}
        for gear_str in gear_ratios:
            try:
                profile = self.build_gear_profile(observations, gear_str)
                profiles[gear_str] = profile
            except ValueError as e:
                print(f"Warning: Could not build profile for {gear_str}: {e}")

        return ConstraintDataSet(profiles=profiles)


# =============================================================================
# Analysis Utilities
# =============================================================================

def calculate_torque(power_W: float, cadence_rpm: float) -> float:
    """
    Calculate torque from power and cadence.

    Torque (Nm) = Power (W) * 60 / (2 * pi * Cadence (RPM))
    Simplified: Torque = Power * 9.5493 / Cadence

    Args:
        power_W: Power in watts
        cadence_rpm: Cadence in RPM

    Returns:
        Torque in Nm
    """
    if cadence_rpm <= 0:
        return 0.0
    return power_W * 60.0 / (2.0 * math.pi * cadence_rpm)


def calculate_power_from_torque(torque_Nm: float, cadence_rpm: float) -> float:
    """
    Calculate power from torque and cadence.

    Power (W) = Torque (Nm) * 2 * pi * Cadence / 60

    Args:
        torque_Nm: Torque in Nm
        cadence_rpm: Cadence in RPM

    Returns:
        Power in watts
    """
    if cadence_rpm <= 0:
        return 0.0
    return torque_Nm * 2.0 * math.pi * cadence_rpm / 60.0


def analyze_torque_cadence_relationship(
    observations: List[PowerCadenceObservation],
    bin_size: int = 5,
) -> Dict[int, Dict[str, float]]:
    """
    Analyze the torque-cadence relationship across all gears.

    This helps validate the assumption that max torque is relatively
    constant across gears at the same cadence.

    Args:
        observations: All observations across all gears
        bin_size: Cadence bin size in RPM

    Returns:
        Dict mapping cadence_bin -> {mean_torque, std_torque, max_torque, n_gears}
    """
    # Group by cadence bin (across all gears)
    bins: Dict[int, List[float]] = defaultdict(list)
    gear_counts: Dict[int, set] = defaultdict(set)

    for obs in observations:
        bin_key = int((obs.cadence_rpm // bin_size) * bin_size)
        bins[bin_key].append(obs.torque_Nm)
        gear_counts[bin_key].add(obs.gear_ratio_str)

    # Compute statistics
    results = {}
    for bin_start in sorted(bins.keys()):
        torques = np.array(bins[bin_start])
        results[bin_start] = {
            'mean_torque_Nm': float(np.mean(torques)),
            'std_torque_Nm': float(np.std(torques, ddof=1)) if len(torques) > 1 else 0.0,
            'max_torque_Nm': float(np.max(torques)),
            'min_torque_Nm': float(np.min(torques)),
            'n_samples': len(torques),
            'n_gears': len(gear_counts[bin_start]),
        }

    return results


def get_power_at_cadence_summary(
    profiles: ConstraintDataSet,
    cadence_rpm: float,
) -> Dict[str, Dict[str, float]]:
    """
    Get power summary at a specific cadence across all gears.

    Useful for comparing gears at the same cadence.

    Args:
        profiles: All gear constraint profiles
        cadence_rpm: Target cadence in RPM

    Returns:
        Dict mapping gear_ratio_str -> {mean, max, p95, ...}
    """
    results = {}

    for gear_str, profile in profiles.profiles.items():
        bin_stats = profile.get_bin_at_cadence(cadence_rpm)
        if bin_stats:
            results[gear_str] = {
                'mean_power_W': bin_stats.mean_power_W,
                'max_power_W': bin_stats.max_power_W,
                'p95_power_W': bin_stats.p95_power_W,
                'std_power_W': bin_stats.std_power_W,
                'n_samples': bin_stats.n_samples,
                'n_efforts': bin_stats.n_efforts,
            }

    return results


def find_optimal_cadence(
    profile: GearConstraintProfile,
    metric: str = 'p95_power_W',
    min_samples: int = 5,
) -> Tuple[int, float]:
    """
    Find the cadence bin with highest power for a gear.

    Args:
        profile: Gear constraint profile
        metric: Which metric to optimize ('mean_power_W', 'max_power_W', 'p95_power_W')
        min_samples: Minimum samples required in bin

    Returns:
        Tuple of (optimal_cadence_bin, power_value)
    """
    best_cadence = 0
    best_power = 0.0

    for bin_stats in profile.bins:
        if bin_stats.n_samples < min_samples:
            continue

        power = getattr(bin_stats, metric, 0.0)
        if power > best_power:
            best_power = power
            best_cadence = bin_stats.cadence_bin

    return best_cadence, best_power


# =============================================================================
# Auto-Interpolation for Intermediate Gears
# =============================================================================

def generate_intermediate_gear_profiles(
    data_set: ConstraintDataSet,
    chainring_range: Optional[Tuple[int, int]] = None,
    cog_range: Optional[Tuple[int, int]] = None,
    verbose: bool = False,
) -> ConstraintDataSet:
    """
    Automatically generate interpolated profiles for all intermediate gear combos.

    Given measured profiles (e.g., 55/12, 55/14, 57/13), generates interpolated
    profiles for all intermediate combinations within the measured range.

    Args:
        data_set: ConstraintDataSet with measured profiles
        chainring_range: Optional (min, max) chainring teeth. If None, uses measured range.
        cog_range: Optional (min, max) cog teeth. If None, uses measured range.
        verbose: Print progress info

    Returns:
        Updated ConstraintDataSet with interpolated profiles added
    """
    from .interpolation import GearRatioInterpolator

    if not data_set.profiles:
        return data_set

    # Extract measured gear info
    measured_gears = set()
    chainrings = set()
    cogs = set()

    for gear_str, profile in data_set.profiles.items():
        measured_gears.add(gear_str)
        chainrings.add(profile.chainring)
        cogs.add(profile.cog)

    # Determine range
    if chainring_range:
        min_cr, max_cr = chainring_range
    else:
        min_cr, max_cr = min(chainrings), max(chainrings)

    if cog_range:
        min_cog, max_cog = cog_range
    else:
        min_cog, max_cog = min(cogs), max(cogs)

    if verbose:
        print(f"Measured gears: {sorted(measured_gears)}")
        print(f"Chainring range: {min_cr}-{max_cr}")
        print(f"Cog range: {min_cog}-{max_cog}")

    # Build interpolator from measured data only
    measured_profiles = {k: v for k, v in data_set.profiles.items() if not v.is_interpolated}

    if len(measured_profiles) < 1:
        if verbose:
            print("Not enough measured profiles for interpolation")
        return data_set

    try:
        interpolator = GearRatioInterpolator(measured_profiles)
    except Exception as e:
        if verbose:
            print(f"Could not build interpolator: {e}")
        return data_set

    # Generate all intermediate combinations
    new_profiles = {}
    for cr in range(min_cr, max_cr + 1):
        for cog in range(min_cog, max_cog + 1):
            gear_str = f"{cr}/{cog}"

            # Skip if already measured
            if gear_str in measured_gears:
                continue

            # Skip unrealistic ratios (too high or too low)
            ratio = cr / cog
            if ratio < 3.0 or ratio > 6.0:  # Typical track range
                continue

            try:
                profile = interpolator.generate_profile_for_gear(cr, cog)
                new_profiles[gear_str] = profile
                if verbose:
                    print(f"  Generated: {gear_str} (ratio: {ratio:.2f})")
            except Exception as e:
                if verbose:
                    print(f"  Failed {gear_str}: {e}")

    # Add to data set
    for gear_str, profile in new_profiles.items():
        data_set.add_profile(profile)

    if verbose:
        print(f"Generated {len(new_profiles)} interpolated profiles")

    return data_set


def get_all_gear_combos_in_range(
    min_chainring: int = 54,
    max_chainring: int = 58,
    min_cog: int = 12,
    max_cog: int = 15,
    min_ratio: float = 3.5,
    max_ratio: float = 5.0,
) -> List[Tuple[int, int]]:
    """
    Get all gear combinations within specified ranges.

    Args:
        min_chainring: Minimum chainring teeth
        max_chainring: Maximum chainring teeth
        min_cog: Minimum cog teeth
        max_cog: Maximum cog teeth
        min_ratio: Minimum gear ratio to include
        max_ratio: Maximum gear ratio to include

    Returns:
        List of (chainring, cog) tuples sorted by gear ratio
    """
    combos = []
    for cr in range(min_chainring, max_chainring + 1):
        for cog in range(min_cog, max_cog + 1):
            ratio = cr / cog
            if min_ratio <= ratio <= max_ratio:
                combos.append((cr, cog))

    # Sort by ratio
    combos.sort(key=lambda x: x[0] / x[1])
    return combos
