"""
Power-Cadence Constraint Models

Data structures for collecting, storing, and analyzing power-cadence
constraint data across different gear ratios.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Dict, Optional, Tuple
import json
import math


# =============================================================================
# Gear Configuration
# =============================================================================

@dataclass
class GearConfig:
    """Gear configuration for a specific effort."""
    chainring: int          # Teeth on chainring (e.g., 55)
    cog: int                # Teeth on rear cog/sprocket (e.g., 12)
    wheel_circ_mm: int = 2096  # Wheel circumference in mm (700c x 23mm default)

    @property
    def gear_ratio(self) -> float:
        """Chainring / cog ratio."""
        return self.chainring / self.cog

    @property
    def gear_ratio_str(self) -> str:
        """String representation for grouping (e.g., '55/12')."""
        return f"{self.chainring}/{self.cog}"

    @property
    def development_m(self) -> float:
        """Distance traveled per pedal revolution [m]."""
        return self.gear_ratio * (self.wheel_circ_mm / 1000.0)

    def to_dict(self) -> dict:
        return {
            'chainring': self.chainring,
            'cog': self.cog,
            'wheel_circ_mm': self.wheel_circ_mm,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'GearConfig':
        return cls(
            chainring=d['chainring'],
            cog=d['cog'],
            wheel_circ_mm=d.get('wheel_circ_mm', d.get('wheelCircMm', 2096)),
        )


# =============================================================================
# Gear Calendar (Input) - Supports multiple efforts per date
# =============================================================================

@dataclass
class EffortGearAssignment:
    """
    Assignment of a gear ratio to a specific effort.

    Can match by:
    - effort_index: 0-based index of detected effort on that date
    - time_range: (start_s, end_s) time window in the activity
    - row_id: External reference ID for validation
    """
    gear: GearConfig
    effort_index: Optional[int] = None      # 0-based index of effort on this date
    time_range: Optional[Tuple[float, float]] = None  # (start_s, end_s) in activity
    row_id: Optional[str] = None            # External reference for validation
    effort_type: int = 200
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            'chainring': self.gear.chainring,
            'cog': self.gear.cog,
            'wheel_circ_mm': self.gear.wheel_circ_mm,
            'effort_type': self.effort_type,
        }
        if self.effort_index is not None:
            d['effort_index'] = self.effort_index
        if self.time_range is not None:
            d['time_range'] = list(self.time_range)
        if self.row_id is not None:
            d['row_id'] = self.row_id
        if self.notes:
            d['notes'] = self.notes
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'EffortGearAssignment':
        return cls(
            gear=GearConfig(
                chainring=d['chainring'],
                cog=d['cog'],
                wheel_circ_mm=d.get('wheel_circ_mm', d.get('wheelCircMm', 2096)),
            ),
            effort_index=d.get('effort_index'),
            time_range=tuple(d['time_range']) if d.get('time_range') else None,
            row_id=d.get('row_id'),
            effort_type=d.get('effort_type', 200),
            notes=d.get('notes'),
        )


@dataclass
class GearCalendarEntry:
    """
    A single date with one or more gear assignments.

    Supports multiple efforts per date, each potentially with different gears.
    """
    date: date
    assignments: List[EffortGearAssignment]  # Multiple efforts possible
    fit_file_path: Optional[str] = None
    strava_activity_id: Optional[int] = None

    @property
    def gear(self) -> GearConfig:
        """Legacy: return first gear (for backwards compatibility)."""
        return self.assignments[0].gear if self.assignments else None

    @property
    def effort_type(self) -> int:
        """Legacy: return first effort type."""
        return self.assignments[0].effort_type if self.assignments else 200

    def get_gear_for_effort(
        self,
        effort_index: int,
        effort_start_time: Optional[float] = None
    ) -> Optional[EffortGearAssignment]:
        """
        Get the gear assignment for a specific effort.

        Matching priority:
        1. Exact effort_index match
        2. Time range match (if effort_start_time provided)
        3. First assignment (fallback for single-effort dates)
        """
        # Try exact index match
        for assignment in self.assignments:
            if assignment.effort_index == effort_index:
                return assignment

        # Try time range match
        if effort_start_time is not None:
            for assignment in self.assignments:
                if assignment.time_range:
                    start, end = assignment.time_range
                    if start <= effort_start_time <= end:
                        return assignment

        # Fallback: if only one assignment, use it for any effort
        if len(self.assignments) == 1:
            return self.assignments[0]

        return None

    def to_dict(self) -> dict:
        return {
            'date': self.date.isoformat(),
            'efforts': [a.to_dict() for a in self.assignments],
            'fit_file_path': self.fit_file_path,
            'strava_activity_id': self.strava_activity_id,
        }


@dataclass
class GearCalendar:
    """Collection of dates with gear assignments."""
    entries: List[GearCalendarEntry] = field(default_factory=list)

    @classmethod
    def from_json(cls, filepath: str) -> 'GearCalendar':
        """
        Load from JSON file.

        Supports two formats:

        Format 1 (Simple - single effort per date):
        {
            "2025-03-02": {
                "chainring": 55,
                "cog": 12,
                "effort_type": 200
            }
        }

        Format 2 (Multiple efforts per date):
        {
            "2025-03-02": {
                "efforts": [
                    {"chainring": 55, "cog": 12, "effort_index": 0, "row_id": "abc123"},
                    {"chainring": 55, "cog": 14, "effort_index": 1, "row_id": "def456"}
                ],
                "strava_id": 12345678
            }
        }
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        entries = []
        for date_str, config in data.items():
            # Handle various date formats
            try:
                d = date.fromisoformat(date_str)
            except ValueError:
                # Try M/D/YYYY format
                parts = date_str.split('/')
                if len(parts) == 3:
                    d = date(int(parts[2]), int(parts[0]), int(parts[1]))
                else:
                    raise ValueError(f"Cannot parse date: {date_str}")

            # Check format
            if 'efforts' in config:
                # Format 2: Multiple efforts
                assignments = [
                    EffortGearAssignment.from_dict(e)
                    for e in config['efforts']
                ]
            else:
                # Format 1: Single effort (legacy)
                assignments = [EffortGearAssignment(
                    gear=GearConfig(
                        chainring=config['chainring'],
                        cog=config['cog'],
                        wheel_circ_mm=config.get('wheel_circ_mm', config.get('wheelCircMm', 2096)),
                    ),
                    effort_index=config.get('effort_index', 0),
                    row_id=config.get('row_id'),
                    effort_type=config.get('effort_type', 200),
                    notes=config.get('notes'),
                )]

            entries.append(GearCalendarEntry(
                date=d,
                assignments=assignments,
                fit_file_path=config.get('fit_file', config.get('fit_file_path')),
                strava_activity_id=config.get('strava_id', config.get('strava_activity_id')),
            ))

        # Sort by date
        entries.sort(key=lambda e: e.date)
        return cls(entries=entries)

    def to_json(self, filepath: str) -> None:
        """Save to JSON file (always uses Format 2 for clarity)."""
        data = {}
        for entry in self.entries:
            date_str = entry.date.isoformat()
            data[date_str] = {
                'efforts': [a.to_dict() for a in entry.assignments],
            }
            if entry.fit_file_path:
                data[date_str]['fit_file'] = entry.fit_file_path
            if entry.strava_activity_id:
                data[date_str]['strava_id'] = entry.strava_activity_id

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def get_entries_for_gear(self, gear_ratio_str: str) -> List[GearCalendarEntry]:
        """Get all entries containing a specific gear ratio."""
        return [
            e for e in self.entries
            if any(a.gear.gear_ratio_str == gear_ratio_str for a in e.assignments)
        ]

    def get_unique_gears(self) -> List[str]:
        """Get list of unique gear ratio strings."""
        gears = set()
        for entry in self.entries:
            for assignment in entry.assignments:
                gears.add(assignment.gear.gear_ratio_str)
        return sorted(gears)

    def get_entry_for_date(self, d: date) -> Optional[GearCalendarEntry]:
        """Get entry for a specific date."""
        for entry in self.entries:
            if entry.date == d:
                return entry
        return None


# =============================================================================
# Raw Observations
# =============================================================================

@dataclass
class PowerCadenceObservation:
    """A single power-cadence measurement from an effort."""
    timestamp_s: float       # Elapsed time within effort [s]
    power_W: float           # Instantaneous power [W]
    cadence_rpm: float       # Instantaneous cadence [RPM]
    speed_kph: float         # Speed [km/h] (for validation)
    gear_ratio: float        # Gear ratio at time of recording
    gear_ratio_str: str      # e.g., "55/12"
    effort_id: str           # Unique effort identifier
    source_date: date        # Date of the activity
    phase: str = "sprint"    # "ramp" or "sprint"

    @property
    def torque_Nm(self) -> float:
        """
        Calculate torque: T = P / (2*pi*cadence/60) = P * 60 / (2*pi*cadence)
        Simplified: T = P * 9.5493 / cadence
        """
        if self.cadence_rpm <= 0:
            return 0.0
        return self.power_W * 60.0 / (2.0 * math.pi * self.cadence_rpm)

    def to_dict(self) -> dict:
        return {
            'timestamp_s': self.timestamp_s,
            'power_W': self.power_W,
            'cadence_rpm': self.cadence_rpm,
            'speed_kph': self.speed_kph,
            'gear_ratio': self.gear_ratio,
            'gear_ratio_str': self.gear_ratio_str,
            'effort_id': self.effort_id,
            'source_date': self.source_date.isoformat(),
            'phase': self.phase,
            'torque_Nm': self.torque_Nm,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'PowerCadenceObservation':
        return cls(
            timestamp_s=d['timestamp_s'],
            power_W=d['power_W'],
            cadence_rpm=d['cadence_rpm'],
            speed_kph=d.get('speed_kph', 0.0),
            gear_ratio=d['gear_ratio'],
            gear_ratio_str=d['gear_ratio_str'],
            effort_id=d['effort_id'],
            source_date=date.fromisoformat(d['source_date']),
            phase=d.get('phase', 'sprint'),
        )


@dataclass
class EffortObservations:
    """All observations from a single detected effort."""
    effort_id: str
    source_date: date
    gear: GearConfig
    effort_type: int
    observations: List[PowerCadenceObservation]

    # Effort metadata from detector
    start_time_s: float
    end_time_s: float
    sprint_start_s: float
    max_power_W: float
    confidence: int

    @property
    def duration_s(self) -> float:
        return self.end_time_s - self.start_time_s

    @property
    def sprint_duration_s(self) -> float:
        return self.end_time_s - self.sprint_start_s

    @property
    def n_observations(self) -> int:
        return len(self.observations)


# =============================================================================
# Statistical Results
# =============================================================================

# Standard durations for power curve analysis
STANDARD_DURATIONS = [1, 2, 3, 5, 10, 15, 20, 30]


@dataclass
class DurationPowerStats:
    """Power statistics for a specific duration at a cadence bin."""
    duration_s: int          # Duration in seconds (1, 2, 3, 5, 10, 15, 20, 30)
    max_power_W: float       # Maximum mean power for this duration
    mean_power_W: float      # Average of max powers across efforts
    std_power_W: float       # Std dev of max powers
    p95_power_W: float       # 95th percentile
    n_efforts: int           # Number of efforts with data for this duration

    def to_dict(self) -> dict:
        return {
            'duration_s': self.duration_s,
            'max_power_W': round(self.max_power_W, 1),
            'mean_power_W': round(self.mean_power_W, 1),
            'std_power_W': round(self.std_power_W, 1),
            'p95_power_W': round(self.p95_power_W, 1),
            'n_efforts': self.n_efforts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'DurationPowerStats':
        return cls(
            duration_s=d['duration_s'],
            max_power_W=d['max_power_W'],
            mean_power_W=d['mean_power_W'],
            std_power_W=d['std_power_W'],
            p95_power_W=d['p95_power_W'],
            n_efforts=d['n_efforts'],
        )


@dataclass
class CadenceBinStats:
    """Statistics for a single cadence bin at a specific gear ratio."""
    gear_ratio_str: str      # e.g., "55/12"
    gear_ratio: float        # numeric ratio
    cadence_bin: int         # bin start (e.g., 100 for 100-104 RPM)
    cadence_bin_size: int    # bin width (e.g., 5)

    # Sample counts
    n_samples: int
    n_efforts: int           # unique efforts contributing

    # Instantaneous power statistics (legacy, kept for compatibility)
    mean_power_W: float
    std_power_W: float
    min_power_W: float
    max_power_W: float
    median_power_W: float
    p90_power_W: float       # 90th percentile
    p95_power_W: float       # 95th percentile

    # Confidence intervals (95%)
    ci_low_W: float
    ci_high_W: float

    # Torque statistics (for cross-gear analysis)
    mean_torque_Nm: float
    std_torque_Nm: float
    max_torque_Nm: float

    # Duration-based power statistics (1s, 2s, 3s, 5s, 10s, 15s, 20s, 30s)
    power_by_duration: Dict[int, DurationPowerStats] = field(default_factory=dict)

    @property
    def cadence_range(self) -> str:
        """Human-readable cadence range string."""
        return f"{self.cadence_bin}-{self.cadence_bin + self.cadence_bin_size - 1}"

    @property
    def is_interpolated(self) -> bool:
        """Whether this bin was interpolated (not measured)."""
        return self.n_samples == 0

    def get_power_for_duration(self, duration_s: int, metric: str = 'p95_power_W') -> Optional[float]:
        """
        Get power value for a specific duration.

        Args:
            duration_s: Duration in seconds
            metric: 'max_power_W', 'mean_power_W', or 'p95_power_W'

        Returns:
            Power value or None if not available
        """
        if duration_s in self.power_by_duration:
            return getattr(self.power_by_duration[duration_s], metric, None)
        return None

    def to_dict(self) -> dict:
        d = {
            'gear_ratio_str': self.gear_ratio_str,
            'gear_ratio': self.gear_ratio,
            'cadence_bin': self.cadence_bin,
            'cadence_bin_size': self.cadence_bin_size,
            'cadence_range': self.cadence_range,
            'n_samples': self.n_samples,
            'n_efforts': self.n_efforts,
            'mean_power_W': round(self.mean_power_W, 1),
            'std_power_W': round(self.std_power_W, 1),
            'min_power_W': round(self.min_power_W, 1),
            'max_power_W': round(self.max_power_W, 1),
            'median_power_W': round(self.median_power_W, 1),
            'p90_power_W': round(self.p90_power_W, 1),
            'p95_power_W': round(self.p95_power_W, 1),
            'ci_low_W': round(self.ci_low_W, 1),
            'ci_high_W': round(self.ci_high_W, 1),
            'mean_torque_Nm': round(self.mean_torque_Nm, 2),
            'std_torque_Nm': round(self.std_torque_Nm, 2),
            'max_torque_Nm': round(self.max_torque_Nm, 2),
            'power_by_duration': {
                str(k): v.to_dict() for k, v in self.power_by_duration.items()
            },
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'CadenceBinStats':
        # Parse power_by_duration if present
        power_by_duration = {}
        if 'power_by_duration' in d:
            for k, v in d['power_by_duration'].items():
                duration_s = int(k)
                power_by_duration[duration_s] = DurationPowerStats.from_dict(v)

        return cls(
            gear_ratio_str=d['gear_ratio_str'],
            gear_ratio=d['gear_ratio'],
            cadence_bin=d['cadence_bin'],
            cadence_bin_size=d['cadence_bin_size'],
            n_samples=d['n_samples'],
            n_efforts=d['n_efforts'],
            mean_power_W=d['mean_power_W'],
            std_power_W=d['std_power_W'],
            min_power_W=d['min_power_W'],
            max_power_W=d['max_power_W'],
            median_power_W=d['median_power_W'],
            p90_power_W=d['p90_power_W'],
            p95_power_W=d['p95_power_W'],
            ci_low_W=d['ci_low_W'],
            ci_high_W=d['ci_high_W'],
            mean_torque_Nm=d['mean_torque_Nm'],
            std_torque_Nm=d['std_torque_Nm'],
            max_torque_Nm=d['max_torque_Nm'],
            power_by_duration=power_by_duration,
        )


@dataclass
class GearConstraintProfile:
    """Complete power-cadence constraint profile for one gear ratio."""
    gear_ratio_str: str
    gear_ratio: float
    chainring: int
    cog: int

    # Cadence bin statistics
    bins: List[CadenceBinStats]

    # Metadata
    n_total_observations: int
    n_efforts: int
    date_range: Tuple[date, date]
    last_updated: datetime

    def get_bin_at_cadence(self, cadence_rpm: float) -> Optional[CadenceBinStats]:
        """Get the bin containing the given cadence."""
        for bin_stats in self.bins:
            bin_end = bin_stats.cadence_bin + bin_stats.cadence_bin_size
            if bin_stats.cadence_bin <= cadence_rpm < bin_end:
                return bin_stats
        return None

    def get_max_power_at_cadence(self, cadence_rpm: float) -> Optional[float]:
        """Get maximum power available at a given cadence."""
        bin_stats = self.get_bin_at_cadence(cadence_rpm)
        return bin_stats.max_power_W if bin_stats else None

    def get_p95_power_at_cadence(self, cadence_rpm: float) -> Optional[float]:
        """Get 95th percentile power at a given cadence (recommended ceiling)."""
        bin_stats = self.get_bin_at_cadence(cadence_rpm)
        return bin_stats.p95_power_W if bin_stats else None

    def get_mean_power_at_cadence(self, cadence_rpm: float) -> Optional[float]:
        """Get mean power at a given cadence."""
        bin_stats = self.get_bin_at_cadence(cadence_rpm)
        return bin_stats.mean_power_W if bin_stats else None

    @property
    def cadence_range(self) -> Tuple[int, int]:
        """Get min and max cadence bins."""
        if not self.bins:
            return (0, 0)
        bins_sorted = sorted(self.bins, key=lambda b: b.cadence_bin)
        return (
            bins_sorted[0].cadence_bin,
            bins_sorted[-1].cadence_bin + bins_sorted[-1].cadence_bin_size - 1
        )

    @property
    def is_interpolated(self) -> bool:
        """Whether this entire profile is interpolated."""
        return self.n_total_observations == 0

    def to_dict(self) -> dict:
        return {
            'gear_ratio_str': self.gear_ratio_str,
            'gear_ratio': self.gear_ratio,
            'chainring': self.chainring,
            'cog': self.cog,
            'bins': [b.to_dict() for b in self.bins],
            'n_total_observations': self.n_total_observations,
            'n_efforts': self.n_efforts,
            'date_range': [self.date_range[0].isoformat(), self.date_range[1].isoformat()],
            'last_updated': self.last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'GearConstraintProfile':
        return cls(
            gear_ratio_str=d['gear_ratio_str'],
            gear_ratio=d['gear_ratio'],
            chainring=d['chainring'],
            cog=d['cog'],
            bins=[CadenceBinStats.from_dict(b) for b in d['bins']],
            n_total_observations=d['n_total_observations'],
            n_efforts=d['n_efforts'],
            date_range=(
                date.fromisoformat(d['date_range'][0]),
                date.fromisoformat(d['date_range'][1]),
            ),
            last_updated=datetime.fromisoformat(d['last_updated']),
        )


# =============================================================================
# Constraint Data Store (Collection of Profiles)
# =============================================================================

@dataclass
class ConstraintDataSet:
    """Complete set of constraint profiles for multiple gears."""
    profiles: Dict[str, GearConstraintProfile] = field(default_factory=dict)

    def get_profile(self, gear_ratio_str: str) -> Optional[GearConstraintProfile]:
        """Get profile for a specific gear ratio."""
        return self.profiles.get(gear_ratio_str)

    def add_profile(self, profile: GearConstraintProfile) -> None:
        """Add or update a profile."""
        self.profiles[profile.gear_ratio_str] = profile

    def get_available_gears(self) -> List[str]:
        """Get list of gear ratios with profiles."""
        return sorted(self.profiles.keys())

    def get_max_power_at_cadence_and_gear(
        self,
        gear_ratio_str: str,
        cadence_rpm: float
    ) -> Optional[float]:
        """Get max power for a specific gear and cadence."""
        profile = self.get_profile(gear_ratio_str)
        if profile:
            return profile.get_max_power_at_cadence(cadence_rpm)
        return None

    def to_dict(self) -> dict:
        return {
            gear_str: profile.to_dict()
            for gear_str, profile in self.profiles.items()
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'ConstraintDataSet':
        return cls(
            profiles={
                gear_str: GearConstraintProfile.from_dict(profile_dict)
                for gear_str, profile_dict in d.items()
            }
        )
