"""
Effort Extractor for Power-Cadence Constraint Collection

Extract sprint phase data from detected flying 200 efforts.
Uses the existing flying 200 detection algorithm.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

# Import from existing FIT module
try:
    from ..fit import detect_flying_efforts, DetectedEffort, FitRecord
    HAS_DETECTOR = True
except ImportError:
    try:
        # Try absolute import for direct execution
        import sys
        parent_dir = str(Path(__file__).parent.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from fit import detect_flying_efforts, DetectedEffort, FitRecord
        HAS_DETECTOR = True
    except ImportError:
        HAS_DETECTOR = False
        # Placeholders for type annotations
        detect_flying_efforts = None
        DetectedEffort = None
        FitRecord = None

try:
    from .models import (
        GearConfig,
        PowerCadenceObservation,
        EffortObservations,
    )
except ImportError:
    from models import (
        GearConfig,
        PowerCadenceObservation,
        EffortObservations,
    )


class SprintPhaseExtractor:
    """
    Extract power-cadence observations from sprint phases of flying efforts.

    Uses the existing flying 200 detection algorithm to find efforts,
    then extracts the sprint phase (high-power portion) for analysis.
    """

    def __init__(
        self,
        min_power_threshold: float = 600.0,
        min_cadence: float = 50.0,
        max_cadence: float = 180.0,
        include_ramp: bool = False,
        sensitivity: str = 'medium',
    ):
        """
        Initialize the extractor with filtering parameters.

        Args:
            min_power_threshold: Minimum power to include in observations (W)
            min_cadence: Minimum cadence to include (RPM)
            max_cadence: Maximum cadence to include (RPM)
            include_ramp: If True, include ramp phase; if False, sprint only
            sensitivity: Detection sensitivity ('low', 'medium', 'high')
        """
        self.min_power_threshold = min_power_threshold
        self.min_cadence = min_cadence
        self.max_cadence = max_cadence
        self.include_ramp = include_ramp
        self.sensitivity = sensitivity

    def detect_efforts(
        self,
        records: List['FitRecord'],
        effort_type: int = 200,
    ) -> List['DetectedEffort']:
        """
        Detect flying efforts in the activity records.

        Args:
            records: List of FitRecords from the activity
            effort_type: Type of effort to detect (200, 150, 100, 50)

        Returns:
            List of detected efforts
        """
        if not HAS_DETECTOR:
            raise ImportError(
                "Flying effort detector not available. "
                "Ensure fit/detector.py is in the path."
            )

        return detect_flying_efforts(
            records,
            effort_type=effort_type,
            verbose=False,
        )

    def extract_sprint_records(
        self,
        records: List['FitRecord'],
        effort: 'DetectedEffort',
    ) -> List['FitRecord']:
        """
        Extract records from the sprint phase of an effort.

        The sprint phase starts at effort.sprint_start_s and ends at effort.end_time.
        Records are filtered by power and cadence thresholds.

        Args:
            records: All records from the activity
            effort: Detected effort with timing info

        Returns:
            List of records from the sprint phase
        """
        sprint_records = []

        # Get time boundaries
        if self.include_ramp:
            phase_start = effort.start_time_s
        else:
            phase_start = effort.sprint_start_s

        phase_end = effort.end_time_s

        for rec in records:
            # Check time range
            if rec.elapsed_s < phase_start or rec.elapsed_s > phase_end:
                continue

            # Check power threshold
            if rec.power_W < self.min_power_threshold:
                continue

            # Check cadence range
            if rec.cadence_rpm < self.min_cadence:
                continue
            if rec.cadence_rpm > self.max_cadence:
                continue

            sprint_records.append(rec)

        return sprint_records

    def records_to_observations(
        self,
        records: List['FitRecord'],
        gear: GearConfig,
        effort_id: str,
        source_date: date,
        phase: str = "sprint",
    ) -> List[PowerCadenceObservation]:
        """
        Convert FitRecords to PowerCadenceObservations.

        Adds gear ratio and effort metadata to each observation.

        Args:
            records: Sprint phase records
            gear: Gear configuration for this effort
            effort_id: Unique identifier for this effort
            source_date: Date of the activity
            phase: Phase label ("sprint" or "ramp")

        Returns:
            List of observations with full metadata
        """
        observations = []

        for rec in records:
            obs = PowerCadenceObservation(
                timestamp_s=rec.elapsed_s,
                power_W=rec.power_W,
                cadence_rpm=rec.cadence_rpm,
                speed_kph=rec.speed_kph,
                gear_ratio=gear.gear_ratio,
                gear_ratio_str=gear.gear_ratio_str,
                effort_id=effort_id,
                source_date=source_date,
                phase=phase,
            )
            observations.append(obs)

        return observations

    def extract_effort_observations(
        self,
        records: List['FitRecord'],
        effort: 'DetectedEffort',
        gear: GearConfig,
        source_date: date,
        effort_index: int = 0,
    ) -> EffortObservations:
        """
        Extract all observations from a single detected effort.

        This is the main entry point for processing a detected effort.

        Args:
            records: All records from the activity
            effort: Detected effort
            gear: Gear configuration
            source_date: Date of the activity
            effort_index: Index of this effort (for ID generation)

        Returns:
            EffortObservations with all extracted data
        """
        effort_id = f"{source_date.isoformat()}_{effort_index}"

        # Extract sprint phase records
        sprint_records = self.extract_sprint_records(records, effort)

        # Convert to observations
        observations = self.records_to_observations(
            sprint_records,
            gear,
            effort_id,
            source_date,
            phase="sprint",
        )

        # Optionally add ramp phase
        if self.include_ramp:
            ramp_records = self._extract_ramp_records(records, effort)
            ramp_observations = self.records_to_observations(
                ramp_records,
                gear,
                effort_id,
                source_date,
                phase="ramp",
            )
            observations = ramp_observations + observations

        return EffortObservations(
            effort_id=effort_id,
            source_date=source_date,
            gear=gear,
            effort_type=effort.effort_type,
            observations=observations,
            start_time_s=effort.start_time_s,
            end_time_s=effort.end_time_s,
            sprint_start_s=effort.sprint_start_s,
            max_power_W=effort.max_power_W,
            confidence=effort.confidence,
        )

    def _extract_ramp_records(
        self,
        records: List['FitRecord'],
        effort: 'DetectedEffort',
    ) -> List['FitRecord']:
        """Extract records from the ramp phase (before sprint)."""
        ramp_records = []

        for rec in records:
            # Ramp phase: start_time to sprint_start
            if rec.elapsed_s < effort.start_time_s:
                continue
            if rec.elapsed_s >= effort.sprint_start_s:
                continue

            # Less strict filtering for ramp phase
            if rec.cadence_rpm < self.min_cadence:
                continue
            if rec.cadence_rpm > self.max_cadence:
                continue

            ramp_records.append(rec)

        return ramp_records

    def process_activity(
        self,
        records: List['FitRecord'],
        gear: GearConfig,
        source_date: date,
        effort_type: int = 200,
    ) -> Tuple[List[EffortObservations], List['DetectedEffort']]:
        """
        Process an entire activity and extract all efforts.

        Args:
            records: All records from the activity
            gear: Gear configuration for this activity
            source_date: Date of the activity
            effort_type: Type of effort to detect

        Returns:
            Tuple of (list of EffortObservations, list of DetectedEfforts)
        """
        # Detect all efforts
        detected_efforts = self.detect_efforts(records, effort_type)

        # Extract observations from each effort
        effort_observations = []
        for i, effort in enumerate(detected_efforts):
            obs = self.extract_effort_observations(
                records,
                effort,
                gear,
                source_date,
                effort_index=i,
            )
            effort_observations.append(obs)

        return effort_observations, detected_efforts


# =============================================================================
# Utility Functions
# =============================================================================

def get_observations_summary(observations: List[PowerCadenceObservation]) -> dict:
    """
    Get summary statistics for a list of observations.

    Args:
        observations: List of observations

    Returns:
        Dict with summary statistics
    """
    if not observations:
        return {
            'n_observations': 0,
            'n_efforts': 0,
            'gear_ratios': [],
            'power_range': (0, 0),
            'cadence_range': (0, 0),
        }

    powers = [o.power_W for o in observations]
    cadences = [o.cadence_rpm for o in observations]
    effort_ids = set(o.effort_id for o in observations)
    gear_ratios = set(o.gear_ratio_str for o in observations)

    return {
        'n_observations': len(observations),
        'n_efforts': len(effort_ids),
        'gear_ratios': sorted(gear_ratios),
        'power_range': (min(powers), max(powers)),
        'cadence_range': (min(cadences), max(cadences)),
    }


def filter_observations_by_gear(
    observations: List[PowerCadenceObservation],
    gear_ratio_str: str,
) -> List[PowerCadenceObservation]:
    """Filter observations to a specific gear ratio."""
    return [o for o in observations if o.gear_ratio_str == gear_ratio_str]


def filter_observations_by_cadence_range(
    observations: List[PowerCadenceObservation],
    min_cadence: float,
    max_cadence: float,
) -> List[PowerCadenceObservation]:
    """Filter observations to a cadence range."""
    return [
        o for o in observations
        if min_cadence <= o.cadence_rpm <= max_cadence
    ]
