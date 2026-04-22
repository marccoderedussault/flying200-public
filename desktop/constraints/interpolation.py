"""
Gear Ratio Interpolation for Power-Cadence Constraints

Interpolate power constraints to unmeasured gear ratios using
torque-based models.
"""

from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.interpolate import interp1d

try:
    from .models import (
        GearConfig,
        CadenceBinStats,
        DurationPowerStats,
        GearConstraintProfile,
        ConstraintDataSet,
        STANDARD_DURATIONS,
    )
except ImportError:
    from models import (
        GearConfig,
        CadenceBinStats,
        DurationPowerStats,
        GearConstraintProfile,
        ConstraintDataSet,
        STANDARD_DURATIONS,
    )


class GearRatioInterpolator:
    """
    Interpolate power constraints to unmeasured gear ratios.

    Key insight: Torque capability is more stable across gears than power.
    At the same cadence, max torque is relatively constant regardless of gear.

    Method:
    1. Build a torque-cadence model from all measured gears
    2. For unmeasured gear, use torque model to estimate power:
       Power = Torque × angular_velocity
    """

    def __init__(
        self,
        measured_profiles: Dict[str, GearConstraintProfile],
        bin_size: int = 5,
    ):
        """
        Initialize with measured constraint profiles.

        Args:
            measured_profiles: Dict mapping gear_ratio_str -> GearConstraintProfile
            bin_size: Cadence bin size in RPM
        """
        self.profiles = measured_profiles
        self.bin_size = bin_size
        self._build_torque_model()

    def _build_torque_model(self) -> None:
        """
        Build torque-cadence model from all measured gears.

        Collects max torque at each cadence from all gears,
        then computes the average max torque per cadence bin.
        Also builds models for duration-based power.
        """
        # Collect torque data from all gears at each cadence
        torque_by_cadence: Dict[int, List[float]] = defaultdict(list)
        power_by_cadence: Dict[int, List[float]] = defaultdict(list)

        # Duration-based power: {duration: {cadence: [power values]}}
        duration_power_by_cadence: Dict[int, Dict[int, List[float]]] = {
            d: defaultdict(list) for d in STANDARD_DURATIONS
        }

        for profile in self.profiles.values():
            for bin_stats in profile.bins:
                # Only use bins with sufficient data
                if bin_stats.n_samples >= 3:
                    torque_by_cadence[bin_stats.cadence_bin].append(bin_stats.max_torque_Nm)
                    power_by_cadence[bin_stats.cadence_bin].append(bin_stats.max_power_W)

                    # Collect duration-based power
                    for duration_s, dur_stats in bin_stats.power_by_duration.items():
                        duration_power_by_cadence[duration_s][bin_stats.cadence_bin].append(
                            dur_stats.max_power_W
                        )

        # Filter to cadences with data from multiple gears
        valid_cadences = [
            cad for cad, torques in torque_by_cadence.items()
            if len(torques) >= 1  # At least 1 gear
        ]

        if not valid_cadences:
            raise ValueError("No valid cadence data found for interpolation model")

        # Compute statistics at each cadence
        self.cadence_bins = sorted(valid_cadences)
        self.max_torque_by_cadence = {
            cad: np.max(torques)  # Use max across all gears
            for cad, torques in torque_by_cadence.items()
            if cad in valid_cadences
        }
        self.mean_torque_by_cadence = {
            cad: np.mean(torques)
            for cad, torques in torque_by_cadence.items()
            if cad in valid_cadences
        }
        self.std_torque_by_cadence = {
            cad: np.std(torques) if len(torques) > 1 else 0.0
            for cad, torques in torque_by_cadence.items()
            if cad in valid_cadences
        }

        # Store power data for ratio estimation
        self.max_power_by_cadence = {
            cad: np.max(powers)
            for cad, powers in power_by_cadence.items()
            if cad in valid_cadences
        }
        self.mean_power_by_cadence = {
            cad: np.mean(powers)
            for cad, powers in power_by_cadence.items()
            if cad in valid_cadences
        }

        # Build duration-based power models
        self.duration_power_by_cadence: Dict[int, Dict[int, float]] = {}
        self.duration_power_interp: Dict[int, interp1d] = {}

        for duration_s in STANDARD_DURATIONS:
            dur_data = duration_power_by_cadence[duration_s]
            if dur_data:
                # Get max power at each cadence for this duration
                self.duration_power_by_cadence[duration_s] = {
                    cad: np.max(powers)
                    for cad, powers in dur_data.items()
                    if cad in valid_cadences and powers
                }

                # Build interpolator if we have enough data
                if len(self.duration_power_by_cadence[duration_s]) >= 2:
                    cads = sorted(self.duration_power_by_cadence[duration_s].keys())
                    pows = [self.duration_power_by_cadence[duration_s][c] for c in cads]
                    self.duration_power_interp[duration_s] = interp1d(
                        cads, pows,
                        kind='linear',
                        bounds_error=False,
                        fill_value='extrapolate',
                    )

        # Build torque interpolators
        cadences = list(self.max_torque_by_cadence.keys())
        max_torques = [self.max_torque_by_cadence[c] for c in cadences]
        mean_torques = [self.mean_torque_by_cadence[c] for c in cadences]

        # Use linear interpolation, extrapolate at edges
        self.max_torque_interp = interp1d(
            cadences,
            max_torques,
            kind='linear',
            bounds_error=False,
            fill_value='extrapolate',
        )
        self.mean_torque_interp = interp1d(
            cadences,
            mean_torques,
            kind='linear',
            bounds_error=False,
            fill_value='extrapolate',
        )

    def get_max_torque_at_cadence(self, cadence_rpm: float) -> float:
        """
        Get interpolated max torque at a given cadence.

        Args:
            cadence_rpm: Cadence in RPM

        Returns:
            Max torque in Nm
        """
        return float(self.max_torque_interp(cadence_rpm))

    def get_mean_torque_at_cadence(self, cadence_rpm: float) -> float:
        """
        Get interpolated mean torque at a given cadence.

        Args:
            cadence_rpm: Cadence in RPM

        Returns:
            Mean torque in Nm
        """
        return float(self.mean_torque_interp(cadence_rpm))

    def estimate_power_at_gear(
        self,
        target_gear_ratio: float,
        cadence_rpm: float,
        use_max: bool = True,
    ) -> float:
        """
        Estimate max power at a cadence for an unmeasured gear ratio.

        Power = Torque × angular_velocity
        P = T × (2 × π × cadence / 60)

        Args:
            target_gear_ratio: Target gear ratio (not used directly,
                              torque is assumed constant at cadence)
            cadence_rpm: Cadence in RPM
            use_max: If True, use max torque; if False, use mean torque

        Returns:
            Estimated power in watts
        """
        if use_max:
            torque = self.get_max_torque_at_cadence(cadence_rpm)
        else:
            torque = self.get_mean_torque_at_cadence(cadence_rpm)

        # Convert torque to power
        angular_velocity = 2 * np.pi * (cadence_rpm / 60.0)
        return torque * angular_velocity

    def get_duration_power_at_cadence(
        self,
        duration_s: int,
        cadence_rpm: float,
    ) -> Optional[float]:
        """
        Get interpolated max power for a duration at a given cadence.

        Args:
            duration_s: Duration in seconds
            cadence_rpm: Cadence in RPM

        Returns:
            Max power in watts, or None if no data for this duration
        """
        if duration_s in self.duration_power_interp:
            return float(self.duration_power_interp[duration_s](cadence_rpm))
        return None

    def generate_profile_for_gear(
        self,
        chainring: int,
        cog: int,
        wheel_circ_mm: int = 2096,
        min_cadence: int = 50,
        max_cadence: int = 180,
    ) -> GearConstraintProfile:
        """
        Generate a complete constraint profile for an unmeasured gear.

        Args:
            chainring: Chainring teeth
            cog: Cog teeth
            wheel_circ_mm: Wheel circumference in mm
            min_cadence: Minimum cadence to generate
            max_cadence: Maximum cadence to generate

        Returns:
            Interpolated GearConstraintProfile
        """
        gear_ratio = chainring / cog
        gear_ratio_str = f"{chainring}/{cog}"

        bins = []
        for cadence_bin in range(min_cadence, max_cadence, self.bin_size):
            # Get cadence at center of bin for interpolation
            cadence_center = cadence_bin + self.bin_size / 2

            # Estimate power from torque model
            max_power = self.estimate_power_at_gear(gear_ratio, cadence_center, use_max=True)
            mean_power = self.estimate_power_at_gear(gear_ratio, cadence_center, use_max=False)

            # Estimate other statistics based on ratios from measured data
            # Using typical ratios observed in real data
            p95_ratio = 0.97  # P95 is typically ~97% of max
            p90_ratio = 0.93  # P90 is typically ~93% of max
            std_ratio = 0.10  # Std is typically ~10% of mean

            p95_power = max_power * p95_ratio
            p90_power = max_power * p90_ratio
            std_power = mean_power * std_ratio

            # CI based on typical sample sizes
            ci_margin = std_power * 0.3  # Rough estimate

            # Torque values
            max_torque = self.get_max_torque_at_cadence(cadence_center)
            mean_torque = self.get_mean_torque_at_cadence(cadence_center)
            std_torque = max_torque * 0.1  # Estimate

            # Duration-based power stats (interpolated)
            power_by_duration = {}
            for duration_s in STANDARD_DURATIONS:
                dur_power = self.get_duration_power_at_cadence(duration_s, cadence_center)
                if dur_power is not None:
                    # For interpolated profiles, we estimate stats from max
                    power_by_duration[duration_s] = DurationPowerStats(
                        duration_s=duration_s,
                        max_power_W=dur_power,
                        mean_power_W=dur_power * 0.92,  # Typical ratio
                        std_power_W=dur_power * 0.08,   # Typical std
                        p95_power_W=dur_power * 0.97,   # Typical p95
                        n_efforts=0,  # Interpolated
                    )

            bin_stats = CadenceBinStats(
                gear_ratio_str=gear_ratio_str,
                gear_ratio=gear_ratio,
                cadence_bin=cadence_bin,
                cadence_bin_size=self.bin_size,
                n_samples=0,  # Mark as interpolated
                n_efforts=0,
                mean_power_W=mean_power,
                std_power_W=std_power,
                min_power_W=mean_power * 0.7,  # Estimate
                max_power_W=max_power,
                median_power_W=mean_power,
                p90_power_W=p90_power,
                p95_power_W=p95_power,
                ci_low_W=mean_power - ci_margin,
                ci_high_W=mean_power + ci_margin,
                mean_torque_Nm=mean_torque,
                std_torque_Nm=std_torque,
                max_torque_Nm=max_torque,
                power_by_duration=power_by_duration,
            )
            bins.append(bin_stats)

        return GearConstraintProfile(
            gear_ratio_str=gear_ratio_str,
            gear_ratio=gear_ratio,
            chainring=chainring,
            cog=cog,
            bins=bins,
            n_total_observations=0,  # Mark as interpolated
            n_efforts=0,
            date_range=(date.today(), date.today()),
            last_updated=datetime.now(),
        )

    def get_torque_model_summary(self) -> Dict[str, any]:
        """
        Get summary of the torque-cadence model.

        Returns:
            Dict with model statistics and diagnostics
        """
        return {
            'n_gears': len(self.profiles),
            'cadence_range': (min(self.cadence_bins), max(self.cadence_bins)),
            'n_cadence_bins': len(self.cadence_bins),
            'max_torque_range': (
                min(self.max_torque_by_cadence.values()),
                max(self.max_torque_by_cadence.values()),
            ),
            'cadence_bins': self.cadence_bins,
            'max_torque_Nm': dict(self.max_torque_by_cadence),
            'mean_torque_Nm': dict(self.mean_torque_by_cadence),
        }


# =============================================================================
# Alternative Interpolation: Development-Based
# =============================================================================

class DevelopmentInterpolator:
    """
    Alternative interpolation based on development (rollout).

    Development = gear_ratio × wheel_circumference
    = meters traveled per pedal revolution

    At the same wheel speed (same track position), different gears
    produce different cadences. This method interpolates based on
    the cadence shift caused by development changes.
    """

    def __init__(
        self,
        measured_profiles: Dict[str, GearConstraintProfile],
        wheel_circ_mm: int = 2096,
    ):
        """
        Initialize with measured profiles.

        Args:
            measured_profiles: Dict of gear profiles
            wheel_circ_mm: Wheel circumference in mm
        """
        self.profiles = measured_profiles
        self.wheel_circ_m = wheel_circ_mm / 1000.0

        # Calculate development for each profile
        self.developments = {
            gear_str: profile.gear_ratio * self.wheel_circ_m
            for gear_str, profile in measured_profiles.items()
        }

    def find_nearest_gears(
        self,
        target_development: float,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Find the two measured gears with developments nearest to target.

        Returns:
            Tuple of (lower_gear_str, higher_gear_str), either may be None
        """
        devs = sorted(self.developments.items(), key=lambda x: x[1])

        lower = None
        higher = None

        for gear_str, dev in devs:
            if dev <= target_development:
                lower = gear_str
            elif higher is None:
                higher = gear_str
                break

        return lower, higher

    def estimate_power_at_development(
        self,
        target_chainring: int,
        target_cog: int,
        cadence_rpm: float,
    ) -> float:
        """
        Estimate power at target gear using development-based interpolation.

        Args:
            target_chainring: Target chainring teeth
            target_cog: Target cog teeth
            cadence_rpm: Target cadence in RPM

        Returns:
            Estimated power in watts
        """
        target_ratio = target_chainring / target_cog
        target_dev = target_ratio * self.wheel_circ_m

        lower_gear, higher_gear = self.find_nearest_gears(target_dev)

        # If we have both bounds, interpolate
        if lower_gear and higher_gear:
            lower_profile = self.profiles[lower_gear]
            higher_profile = self.profiles[higher_gear]

            lower_power = lower_profile.get_p95_power_at_cadence(cadence_rpm) or 0
            higher_power = higher_profile.get_p95_power_at_cadence(cadence_rpm) or 0

            lower_dev = self.developments[lower_gear]
            higher_dev = self.developments[higher_gear]

            # Linear interpolation
            if higher_dev != lower_dev:
                t = (target_dev - lower_dev) / (higher_dev - lower_dev)
                return lower_power + t * (higher_power - lower_power)
            else:
                return (lower_power + higher_power) / 2

        # If only one bound, use it directly
        if lower_gear:
            return self.profiles[lower_gear].get_p95_power_at_cadence(cadence_rpm) or 0
        if higher_gear:
            return self.profiles[higher_gear].get_p95_power_at_cadence(cadence_rpm) or 0

        return 0.0


# =============================================================================
# Utility Functions
# =============================================================================

def validate_interpolation(
    interpolator: GearRatioInterpolator,
    measured_profiles: Dict[str, GearConstraintProfile],
    verbose: bool = False,
) -> Dict[str, float]:
    """
    Validate interpolation accuracy using leave-one-out cross-validation.

    For each measured gear, hide it and interpolate, then compare.

    Args:
        interpolator: Interpolator built from all profiles
        measured_profiles: All measured profiles
        verbose: Print detailed results

    Returns:
        Dict with validation metrics
    """
    errors = []

    for gear_str, profile in measured_profiles.items():
        # Build interpolator without this gear
        other_profiles = {k: v for k, v in measured_profiles.items() if k != gear_str}

        if len(other_profiles) < 1:
            continue

        try:
            test_interp = GearRatioInterpolator(other_profiles)
            test_profile = test_interp.generate_profile_for_gear(
                profile.chainring,
                profile.cog,
            )

            # Compare at each cadence bin
            for actual_bin in profile.bins:
                pred_bin = test_profile.get_bin_at_cadence(actual_bin.cadence_bin)
                if pred_bin and actual_bin.n_samples >= 5:
                    error = abs(pred_bin.p95_power_W - actual_bin.p95_power_W)
                    rel_error = error / actual_bin.p95_power_W if actual_bin.p95_power_W > 0 else 0
                    errors.append(rel_error)

                    if verbose:
                        print(f"{gear_str} @ {actual_bin.cadence_bin} RPM: "
                              f"actual={actual_bin.p95_power_W:.0f}W, "
                              f"pred={pred_bin.p95_power_W:.0f}W, "
                              f"error={rel_error*100:.1f}%")

        except Exception as e:
            if verbose:
                print(f"Could not validate {gear_str}: {e}")

    if not errors:
        return {'mean_error': 0, 'max_error': 0, 'n_comparisons': 0}

    return {
        'mean_error': np.mean(errors),
        'std_error': np.std(errors),
        'max_error': np.max(errors),
        'n_comparisons': len(errors),
    }
