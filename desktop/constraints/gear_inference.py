"""
Gear Ratio Inference from Speed-Cadence Data

Infer gear ratios from the relationship between speed and cadence.
This helps validate gear assignments and detect mismatches.

Key relationship:
    speed_mps = (cadence_rpm / 60) * gear_ratio * wheel_circumference_m

Therefore:
    gear_ratio = speed_mps * 60 / (cadence_rpm * wheel_circumference_m)
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Optional, Tuple
import math

import numpy as np

try:
    from .models import GearConfig, GearCalendarEntry, EffortGearAssignment
except ImportError:
    from models import GearConfig, GearCalendarEntry, EffortGearAssignment


@dataclass
class InferredGear:
    """Result of gear inference for an effort."""
    inferred_ratio: float           # Calculated gear ratio
    inferred_chainring: int         # Best matching chainring
    inferred_cog: int               # Best matching cog
    confidence: float               # 0-1 confidence score
    n_samples: int                  # Number of data points used
    mean_speed_kph: float
    mean_cadence_rpm: float
    ratio_std: float                # Standard deviation of calculated ratios


@dataclass
class GearValidationResult:
    """Result of validating an effort's gear assignment."""
    effort_index: int
    effort_start_time: float
    effort_end_time: float
    assigned_gear: Optional[str]    # e.g., "55/12" or None if not assigned
    inferred_gear: InferredGear
    match: bool                     # Does assigned match inferred?
    ratio_difference: float         # Difference between assigned and inferred ratio
    row_id: Optional[str] = None


class GearInferenceEngine:
    """
    Infer gear ratios from speed-cadence data.

    Uses the physical relationship between speed, cadence, and gearing
    to determine what gear was used during an effort.
    """

    # Common track cycling gears (chainring/cog combinations)
    COMMON_GEARS = [
        (54, 14), (54, 15), (54, 16),
        (55, 12), (55, 13), (55, 14), (55, 15), (55, 16),
        (56, 14), (56, 15),
        (57, 14), (57, 15),
        (49, 14), (49, 15), (50, 14), (50, 15),  # Smaller gears
        (51, 14), (51, 15), (52, 14), (52, 15),
        (53, 14), (53, 15),
    ]

    def __init__(
        self,
        wheel_circ_mm: int = 2096,
        min_cadence: float = 60.0,
        min_speed_kph: float = 30.0,
        custom_gears: Optional[List[Tuple[int, int]]] = None,
    ):
        """
        Initialize the inference engine.

        Args:
            wheel_circ_mm: Wheel circumference in mm
            min_cadence: Minimum cadence to use for inference (filter noise)
            min_speed_kph: Minimum speed to use for inference
            custom_gears: Optional list of (chainring, cog) tuples to consider
        """
        self.wheel_circ_m = wheel_circ_mm / 1000.0
        self.min_cadence = min_cadence
        self.min_speed_kph = min_speed_kph
        self.known_gears = custom_gears or self.COMMON_GEARS

        # Pre-compute gear ratios
        self.gear_ratios = {
            f"{cr}/{cog}": cr / cog
            for cr, cog in self.known_gears
        }

    def calculate_gear_ratio(
        self,
        speed_kph: float,
        cadence_rpm: float,
    ) -> float:
        """
        Calculate gear ratio from speed and cadence.

        gear_ratio = speed_mps * 60 / (cadence_rpm * wheel_circumference_m)
        """
        if cadence_rpm <= 0:
            return 0.0
        speed_mps = speed_kph / 3.6
        return speed_mps * 60.0 / (cadence_rpm * self.wheel_circ_m)

    def infer_gear_from_records(
        self,
        records: List[dict],  # List of {speed_kph, cadence_rpm, ...}
    ) -> InferredGear:
        """
        Infer gear ratio from a list of records.

        Uses median of individual calculations to be robust to outliers.

        Args:
            records: List of record dicts with speed_kph and cadence_rpm

        Returns:
            InferredGear with best matching gear
        """
        # Filter valid records
        valid_records = [
            r for r in records
            if r.get('cadence_rpm', 0) >= self.min_cadence
            and r.get('speed_kph', 0) >= self.min_speed_kph
        ]

        if not valid_records:
            return InferredGear(
                inferred_ratio=0.0,
                inferred_chainring=0,
                inferred_cog=0,
                confidence=0.0,
                n_samples=0,
                mean_speed_kph=0.0,
                mean_cadence_rpm=0.0,
                ratio_std=0.0,
            )

        # Calculate ratio for each record
        ratios = []
        speeds = []
        cadences = []

        for r in valid_records:
            ratio = self.calculate_gear_ratio(r['speed_kph'], r['cadence_rpm'])
            if 2.0 <= ratio <= 6.0:  # Reasonable track cycling range
                ratios.append(ratio)
                speeds.append(r['speed_kph'])
                cadences.append(r['cadence_rpm'])

        if not ratios:
            return InferredGear(
                inferred_ratio=0.0,
                inferred_chainring=0,
                inferred_cog=0,
                confidence=0.0,
                n_samples=0,
                mean_speed_kph=np.mean([r['speed_kph'] for r in valid_records]),
                mean_cadence_rpm=np.mean([r['cadence_rpm'] for r in valid_records]),
                ratio_std=0.0,
            )

        # Use median for robustness
        median_ratio = np.median(ratios)
        ratio_std = np.std(ratios)

        # Find best matching known gear
        best_gear = self._find_best_matching_gear(median_ratio)

        # Calculate confidence based on consistency and match quality
        consistency = 1.0 - min(ratio_std / 0.5, 1.0)  # Lower std = higher confidence
        match_quality = 1.0 - min(abs(median_ratio - best_gear[0]/best_gear[1]) / 0.1, 1.0)
        confidence = (consistency * 0.5 + match_quality * 0.5)

        return InferredGear(
            inferred_ratio=median_ratio,
            inferred_chainring=best_gear[0],
            inferred_cog=best_gear[1],
            confidence=confidence,
            n_samples=len(ratios),
            mean_speed_kph=np.mean(speeds),
            mean_cadence_rpm=np.mean(cadences),
            ratio_std=ratio_std,
        )

    def _find_best_matching_gear(
        self,
        target_ratio: float,
    ) -> Tuple[int, int]:
        """Find the known gear closest to the target ratio."""
        best_match = (55, 12)  # Default
        best_diff = float('inf')

        for chainring, cog in self.known_gears:
            ratio = chainring / cog
            diff = abs(ratio - target_ratio)
            if diff < best_diff:
                best_diff = diff
                best_match = (chainring, cog)

        return best_match

    def validate_effort_gear(
        self,
        records: List[dict],
        assigned_gear: Optional[GearConfig],
        effort_index: int = 0,
        effort_start_time: float = 0.0,
        effort_end_time: float = 0.0,
        row_id: Optional[str] = None,
    ) -> GearValidationResult:
        """
        Validate that the assigned gear matches the inferred gear.

        Args:
            records: Sprint phase records for the effort
            assigned_gear: The gear that was assigned in the calendar
            effort_index: Index of the effort
            effort_start_time: Start time in activity
            effort_end_time: End time in activity
            row_id: External reference ID

        Returns:
            GearValidationResult with match status
        """
        # Infer gear from data
        inferred = self.infer_gear_from_records([
            {'speed_kph': r.speed_kph, 'cadence_rpm': r.cadence_rpm}
            for r in records
            if hasattr(r, 'speed_kph') and hasattr(r, 'cadence_rpm')
        ])

        # Check match
        if assigned_gear:
            assigned_ratio = assigned_gear.gear_ratio
            ratio_diff = abs(inferred.inferred_ratio - assigned_ratio)
            # Match if within 0.1 of ratio (roughly same gear)
            match = ratio_diff < 0.1 and inferred.confidence > 0.5
            assigned_str = assigned_gear.gear_ratio_str
        else:
            ratio_diff = 0.0
            match = False
            assigned_str = None

        return GearValidationResult(
            effort_index=effort_index,
            effort_start_time=effort_start_time,
            effort_end_time=effort_end_time,
            assigned_gear=assigned_str,
            inferred_gear=inferred,
            match=match,
            ratio_difference=ratio_diff,
            row_id=row_id,
        )


def generate_validation_report(
    validation_results: List[GearValidationResult],
    source_date: date,
) -> str:
    """
    Generate a human-readable validation report.

    Args:
        validation_results: List of validation results
        source_date: Date of the activity

    Returns:
        Formatted report string
    """
    lines = [
        f"Gear Validation Report - {source_date}",
        "=" * 60,
        "",
    ]

    for result in validation_results:
        status = "✓ MATCH" if result.match else "✗ MISMATCH"
        inferred = result.inferred_gear

        lines.append(f"Effort #{result.effort_index + 1}")
        lines.append(f"  Time: {result.effort_start_time:.0f}s - {result.effort_end_time:.0f}s")
        if result.row_id:
            lines.append(f"  Row ID: {result.row_id}")
        lines.append(f"  Assigned gear: {result.assigned_gear or 'NOT ASSIGNED'}")
        lines.append(f"  Inferred gear: {inferred.inferred_chainring}/{inferred.inferred_cog} "
                    f"(ratio: {inferred.inferred_ratio:.3f})")
        lines.append(f"  Confidence: {inferred.confidence:.0%}")
        lines.append(f"  Samples: {inferred.n_samples}")
        lines.append(f"  Avg speed: {inferred.mean_speed_kph:.1f} km/h, "
                    f"Avg cadence: {inferred.mean_cadence_rpm:.0f} rpm")
        lines.append(f"  Status: {status}")
        if not result.match and result.assigned_gear:
            lines.append(f"  Ratio difference: {result.ratio_difference:.3f}")
        lines.append("")

    # Summary
    n_total = len(validation_results)
    n_matched = sum(1 for r in validation_results if r.match)
    n_unassigned = sum(1 for r in validation_results if r.assigned_gear is None)

    lines.append("-" * 60)
    lines.append(f"Summary: {n_matched}/{n_total} matched")
    if n_unassigned:
        lines.append(f"         {n_unassigned} efforts without gear assignment")

    return "\n".join(lines)


def suggest_gear_assignments(
    validation_results: List[GearValidationResult],
    source_date: date,
) -> List[Dict]:
    """
    Suggest gear assignments based on inference results.

    Returns a list of suggested assignments that can be added to the calendar.
    """
    suggestions = []

    for result in validation_results:
        if result.inferred_gear.confidence < 0.5:
            continue  # Skip low-confidence inferences

        inferred = result.inferred_gear
        suggestions.append({
            'effort_index': result.effort_index,
            'chainring': inferred.inferred_chainring,
            'cog': inferred.inferred_cog,
            'row_id': result.row_id,
            'confidence': inferred.confidence,
            'inferred_ratio': inferred.inferred_ratio,
            'time_range': [result.effort_start_time, result.effort_end_time],
        })

    return suggestions


def create_calendar_from_inference(
    dates_with_efforts: Dict[date, List[GearValidationResult]],
    output_path: str,
) -> None:
    """
    Create a gear calendar JSON file from inference results.

    Useful for bootstrapping the calendar from detected efforts.
    """
    import json

    calendar_data = {}

    for d, results in sorted(dates_with_efforts.items()):
        efforts = []
        for result in results:
            if result.inferred_gear.confidence < 0.3:
                continue

            inferred = result.inferred_gear
            effort_entry = {
                'chainring': inferred.inferred_chainring,
                'cog': inferred.inferred_cog,
                'effort_index': result.effort_index,
                'effort_type': 200,
                '_inferred': True,
                '_confidence': round(inferred.confidence, 2),
                '_ratio': round(inferred.inferred_ratio, 3),
            }
            if result.row_id:
                effort_entry['row_id'] = result.row_id
            efforts.append(effort_entry)

        if efforts:
            calendar_data[d.isoformat()] = {'efforts': efforts}

    with open(output_path, 'w') as f:
        json.dump(calendar_data, f, indent=2)
