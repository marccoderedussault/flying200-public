"""
Flying 200 V2 - FIT File Parser

Parse FIT files into a clean data structure for analysis.
Ported from flying200_package/fit_analyzer.py with improved interface.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

try:
    from fitparse import FitFile
    HAS_FITPARSE = True
except ImportError:
    HAS_FITPARSE = False


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class FitRecord:
    """A single record from a FIT file."""
    timestamp: datetime
    elapsed_s: float          # elapsed time from file start [s]
    power_W: float            # power [W]
    cadence_rpm: float        # cadence [RPM]
    speed_kph: float          # speed [km/h] (from device if available)
    heart_rate_bpm: float     # heart rate [BPM] (if available)
    distance_m: float         # cumulative distance [m] (from device)


@dataclass
class LapMarker:
    """A lap marker from the FIT file."""
    index: int
    start_time: datetime
    total_time_s: float
    total_distance_m: float


@dataclass
class FitFileData:
    """Complete data from a parsed FIT file."""
    filename: str
    records: List[FitRecord]
    lap_markers: List[LapMarker]
    total_duration_s: float
    max_power_W: float
    avg_power_W: float
    max_cadence_rpm: float
    avg_cadence_rpm: float

    def to_dataframe(self) -> pd.DataFrame:
        """Convert records to pandas DataFrame."""
        return pd.DataFrame([
            {
                'timestamp': r.timestamp,
                'elapsed_s': r.elapsed_s,
                'power_W': r.power_W,
                'cadence_rpm': r.cadence_rpm,
                'speed_kph': r.speed_kph,
                'heart_rate_bpm': r.heart_rate_bpm,
                'distance_m': r.distance_m,
            }
            for r in self.records
        ])

    def get_time_range(self, start_s: float, end_s: float) -> List[FitRecord]:
        """Get records within a time range."""
        return [r for r in self.records if start_s <= r.elapsed_s <= end_s]


# =============================================================================
# Parser Functions
# =============================================================================

def parse_fit_file(fit_path: str) -> FitFileData:
    """
    Parse a FIT file and extract all record data.

    Args:
        fit_path: Path to the FIT file

    Returns:
        FitFileData containing all records and lap markers

    Raises:
        ImportError: If fitparse library is not installed
        FileNotFoundError: If file doesn't exist
        Exception: If parsing fails
    """
    if not HAS_FITPARSE:
        raise ImportError(
            "fitparse library not installed. "
            "Install with: pip install fitparse"
        )

    fit_path = Path(fit_path)
    if not fit_path.exists():
        raise FileNotFoundError(f"FIT file not found: {fit_path}")

    try:
        fitfile = FitFile(str(fit_path))
    except Exception as e:
        raise Exception(f"Error opening FIT file: {e}")

    records: List[FitRecord] = []
    lap_markers: List[LapMarker] = []

    # Extract lap markers
    for i, lap in enumerate(fitfile.get_messages('lap')):
        lap_data = {field.name: field.value for field in lap}
        lap_markers.append(LapMarker(
            index=i,
            start_time=lap_data.get('start_time') or lap_data.get('timestamp'),
            total_time_s=lap_data.get('total_elapsed_time', 0) or 0,
            total_distance_m=lap_data.get('total_distance', 0) or 0,
        ))

    # Extract record data
    file_start_time = None
    for record in fitfile.get_messages('record'):
        record_data = {field.name: field.value for field in record}

        timestamp = record_data.get('timestamp')
        if timestamp is None:
            continue

        if file_start_time is None:
            file_start_time = timestamp

        # Calculate elapsed time
        if hasattr(timestamp, 'total_seconds'):
            # Already a timedelta
            elapsed_s = timestamp.total_seconds()
        else:
            # Datetime - calculate from start
            elapsed_s = (timestamp - file_start_time).total_seconds()

        # Extract fields with defaults
        power_W = record_data.get('power', 0) or 0
        cadence_rpm = record_data.get('cadence', 0) or 0
        heart_rate_bpm = record_data.get('heart_rate', 0) or 0
        distance_m = record_data.get('distance', 0) or 0

        # Speed: convert from m/s to km/h if present
        speed_raw = record_data.get('speed', 0) or 0
        speed_kph = speed_raw * 3.6 if speed_raw < 100 else speed_raw  # Handle if already in kph

        records.append(FitRecord(
            timestamp=timestamp,
            elapsed_s=elapsed_s,
            power_W=power_W,
            cadence_rpm=cadence_rpm,
            speed_kph=speed_kph,
            heart_rate_bpm=heart_rate_bpm,
            distance_m=distance_m,
        ))

    if not records:
        raise Exception("No records found in FIT file")

    # Calculate summary statistics
    powers = [r.power_W for r in records if r.power_W > 0]
    cadences = [r.cadence_rpm for r in records if r.cadence_rpm > 0]

    return FitFileData(
        filename=fit_path.name,
        records=records,
        lap_markers=lap_markers,
        total_duration_s=records[-1].elapsed_s if records else 0,
        max_power_W=max(powers) if powers else 0,
        avg_power_W=np.mean(powers) if powers else 0,
        max_cadence_rpm=max(cadences) if cadences else 0,
        avg_cadence_rpm=np.mean(cadences) if cadences else 0,
    )


def extract_segment_by_time(
    fit_data: FitFileData,
    start_s: float,
    end_s: float,
) -> List[FitRecord]:
    """
    Extract records between two time points.

    Args:
        fit_data: Parsed FIT file data
        start_s: Start time in seconds from file start
        end_s: End time in seconds from file start

    Returns:
        List of records in the time range
    """
    return [r for r in fit_data.records if start_s <= r.elapsed_s <= end_s]


def extract_segment_by_markers(
    fit_data: FitFileData,
    start_marker_idx: int = 0,
    end_marker_idx: Optional[int] = None,
) -> List[FitRecord]:
    """
    Extract records between lap markers.

    Args:
        fit_data: Parsed FIT file data
        start_marker_idx: Index of starting lap marker (0-based)
        end_marker_idx: Index of ending lap marker (None = end of file)

    Returns:
        List of records between markers
    """
    if not fit_data.lap_markers:
        return fit_data.records

    if start_marker_idx >= len(fit_data.lap_markers):
        raise ValueError(f"start_marker_idx {start_marker_idx} >= markers {len(fit_data.lap_markers)}")

    start_time = fit_data.lap_markers[start_marker_idx].start_time

    if end_marker_idx is not None and end_marker_idx < len(fit_data.lap_markers):
        end_time = fit_data.lap_markers[end_marker_idx].start_time
    else:
        end_time = fit_data.records[-1].timestamp

    return [r for r in fit_data.records if start_time <= r.timestamp <= end_time]


def list_lap_markers(fit_path: str) -> List[LapMarker]:
    """
    List all lap markers in a FIT file.

    Useful for user to select which segment to analyze.
    """
    fit_data = parse_fit_file(fit_path)

    print(f"\nLap markers in {fit_data.filename}:")
    print("-" * 60)
    for marker in fit_data.lap_markers:
        print(f"  [{marker.index}] Time: {marker.total_time_s:.1f}s, Distance: {marker.total_distance_m:.0f}m")
    print("-" * 60)

    return fit_data.lap_markers


# =============================================================================
# Power Curve Extraction
# =============================================================================

def extract_power_curve(
    records: List[FitRecord],
    durations: List[int] = None,
) -> Dict[int, float]:
    """
    Extract best average power for each duration.

    This finds the Maximum Mean Power (MMP) for each duration across
    the entire record set.

    Args:
        records: List of FIT records
        durations: List of durations in seconds (default: standard power curve)

    Returns:
        Dict mapping duration (seconds) to best average power (watts)
    """
    if durations is None:
        durations = [1, 2, 3, 5, 10, 15, 20, 30]

    if len(records) < 2:
        return {d: 0.0 for d in durations}

    # Extract power series with timestamps
    powers = [r.power_W for r in records]
    times = [r.elapsed_s for r in records]

    # For each duration, find the best average
    result = {}
    for duration in durations:
        best_avg = 0.0

        for i in range(len(records)):
            # Find window end
            end_time = times[i] + duration
            end_idx = i

            # Find the index at end_time
            while end_idx < len(records) - 1 and times[end_idx] < end_time:
                end_idx += 1

            if end_idx > i:
                # Calculate average power in this window
                window_powers = powers[i:end_idx+1]
                avg = np.mean(window_powers)
                if avg > best_avg:
                    best_avg = avg

        result[duration] = best_avg

    return result
