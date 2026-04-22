"""
Data Sources for Power-Cadence Constraint Collection

Load activity data from FIT files or Strava API.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional
import os
import glob
import requests

# Import from existing FIT module
try:
    from ..fit import parse_fit_file, FitFileData, FitRecord
    HAS_FIT_MODULE = True
except ImportError:
    try:
        # Try absolute import for direct execution
        import sys
        parent_dir = str(Path(__file__).parent.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from fit import parse_fit_file, FitFileData, FitRecord
        HAS_FIT_MODULE = True
    except ImportError:
        HAS_FIT_MODULE = False
        # Define placeholder types for type annotations
        FitFileData = None
        FitRecord = None
        parse_fit_file = None

try:
    from .models import GearCalendarEntry
except ImportError:
    from models import GearCalendarEntry


# =============================================================================
# FIT File Data Source
# =============================================================================

class FitFileSource:
    """Load activity data from local FIT files."""

    def __init__(self, fit_directory: str):
        """
        Initialize with a directory containing FIT files.

        Args:
            fit_directory: Path to directory containing FIT files
        """
        self.fit_directory = Path(fit_directory)
        if not self.fit_directory.exists():
            raise FileNotFoundError(f"FIT directory not found: {fit_directory}")

    def find_file_for_date(self, activity_date: date) -> Optional[Path]:
        """
        Find FIT file matching a date.

        Tries various naming patterns commonly used by devices:
        - *2025-03-02*.fit (ISO format)
        - *20250302*.fit (compact format)
        - Activity files with date in name

        Args:
            activity_date: Date to search for

        Returns:
            Path to matching FIT file, or None if not found
        """
        iso_date = activity_date.isoformat()  # 2025-03-02
        compact_date = activity_date.strftime('%Y%m%d')  # 20250302
        us_date = activity_date.strftime('%m-%d-%Y')  # 03-02-2025
        us_compact = activity_date.strftime('%m%d%Y')  # 03022025 (Strava export format)

        patterns = [
            f"{us_compact}*.fit",  # Strava: 03022025_Morning_Ride.fit (check first, most common)
            f"*{iso_date}*.fit",
            f"*{compact_date}*.fit",
            f"*{us_date}*.fit",
            f"*{activity_date.year}_{activity_date.month:02d}_{activity_date.day:02d}*.fit",
        ]

        for pattern in patterns:
            matches = list(self.fit_directory.glob(pattern))
            if matches:
                # Return most recently modified if multiple matches
                return max(matches, key=lambda p: p.stat().st_mtime)

        # Fallback: search recursively
        for pattern in patterns:
            matches = list(self.fit_directory.rglob(pattern))
            if matches:
                return max(matches, key=lambda p: p.stat().st_mtime)

        return None

    def load_file(self, filepath: str) -> FitFileData:
        """
        Load and parse a FIT file.

        Args:
            filepath: Path to FIT file

        Returns:
            Parsed FIT file data
        """
        if not HAS_FIT_MODULE:
            raise ImportError("FIT module not available. Cannot parse FIT files.")
        return parse_fit_file(filepath)

    def load_for_entry(self, entry: GearCalendarEntry) -> Optional[FitFileData]:
        """
        Load FIT data for a calendar entry.

        Args:
            entry: Calendar entry with date and optional FIT file path

        Returns:
            Parsed FIT file data, or None if not found
        """
        # If explicit path provided, use it
        if entry.fit_file_path:
            fit_path = Path(entry.fit_file_path)
            if not fit_path.is_absolute():
                fit_path = self.fit_directory / fit_path
            if fit_path.exists():
                return self.load_file(str(fit_path))

        # Otherwise search by date
        fit_path = self.find_file_for_date(entry.date)
        if fit_path:
            return self.load_file(str(fit_path))

        return None

    def list_available_files(self) -> List[Path]:
        """List all FIT files in the directory."""
        return sorted(self.fit_directory.glob("*.fit"))


# =============================================================================
# Strava API Data Source
# =============================================================================

class StravaDataSource:
    """
    Fetch activity data from Strava API.

    This is a lightweight Python wrapper around the Strava API.
    For full OAuth flow, use the existing web service integration.
    """

    BASE_URL = "https://www.strava.com/api/v3"

    def __init__(self, access_token: str):
        """
        Initialize with a valid Strava access token.

        To get an access token:
        1. Use the existing web app OAuth flow
        2. Or create a personal access token in Strava settings

        Args:
            access_token: Valid Strava API access token
        """
        self.access_token = access_token
        self.session = requests.Session()
        self.session.headers['Authorization'] = f"Bearer {access_token}"

    def get_activities_for_date(self, activity_date: date) -> List[dict]:
        """
        Find activities on a specific date.

        Args:
            activity_date: Date to search for

        Returns:
            List of activity dicts from Strava API
        """
        from datetime import datetime, timedelta

        # Convert to epoch timestamps for the full day
        start_of_day = datetime.combine(activity_date, datetime.min.time())
        end_of_day = start_of_day + timedelta(days=1)

        params = {
            'before': int(end_of_day.timestamp()),
            'after': int(start_of_day.timestamp()),
            'per_page': 30,
        }

        response = self.session.get(
            f"{self.BASE_URL}/athlete/activities",
            params=params
        )
        response.raise_for_status()

        activities = response.json()

        # Filter to cycling with power data
        return [
            a for a in activities
            if a.get('type') in ('Ride', 'VirtualRide')
            and a.get('device_watts', False)
        ]

    def get_activity_streams(self, activity_id: int) -> dict:
        """
        Fetch detailed streams for an activity.

        Args:
            activity_id: Strava activity ID

        Returns:
            Dict with stream arrays: time, power, cadence, velocity, etc.
        """
        params = {
            'keys': 'time,distance,watts,cadence,velocity_smooth,heartrate',
            'key_by_type': 'true',
        }

        response = self.session.get(
            f"{self.BASE_URL}/activities/{activity_id}/streams",
            params=params
        )
        response.raise_for_status()

        return response.json()

    def streams_to_fit_records(self, streams: dict) -> List['FitRecord']:
        """
        Convert Strava streams to FitRecord format.

        This provides unified data format regardless of source (FIT or Strava).

        Args:
            streams: Raw streams from Strava API

        Returns:
            List of FitRecord objects
        """
        from datetime import datetime

        records = []

        # Extract stream arrays
        time_data = streams.get('time', {}).get('data', [])
        power_data = streams.get('watts', {}).get('data', [])
        cadence_data = streams.get('cadence', {}).get('data', [])
        velocity_data = streams.get('velocity_smooth', {}).get('data', [])
        distance_data = streams.get('distance', {}).get('data', [])
        hr_data = streams.get('heartrate', {}).get('data', [])

        # Ensure arrays are same length
        n_points = len(time_data)
        if not n_points:
            return records

        # Pad shorter arrays with zeros/None
        def pad(arr, length, default=0):
            return arr + [default] * (length - len(arr)) if len(arr) < length else arr

        power_data = pad(power_data, n_points)
        cadence_data = pad(cadence_data, n_points)
        velocity_data = pad(velocity_data, n_points)
        distance_data = pad(distance_data, n_points)
        hr_data = pad(hr_data, n_points)

        # Convert to FitRecord format
        for i in range(n_points):
            records.append(FitRecord(
                timestamp=datetime.now(),  # Placeholder, not used for analysis
                elapsed_s=float(time_data[i]),
                power_W=float(power_data[i]) if power_data[i] else 0.0,
                cadence_rpm=float(cadence_data[i]) if cadence_data[i] else 0.0,
                speed_kph=float(velocity_data[i]) * 3.6 if velocity_data[i] else 0.0,  # m/s to kph
                heart_rate_bpm=float(hr_data[i]) if hr_data[i] else 0.0,
                distance_m=float(distance_data[i]) if distance_data[i] else 0.0,
            ))

        return records

    def load_for_entry(self, entry: GearCalendarEntry) -> Optional[List['FitRecord']]:
        """
        Load Strava data for a calendar entry.

        Args:
            entry: Calendar entry with date and optional Strava activity ID

        Returns:
            List of FitRecords, or None if not found
        """
        activity_id = entry.strava_activity_id

        if not activity_id:
            # Search for activity on that date
            activities = self.get_activities_for_date(entry.date)
            if not activities:
                return None
            # Use first cycling activity with power
            activity_id = activities[0]['id']

        # Fetch streams and convert
        streams = self.get_activity_streams(activity_id)
        return self.streams_to_fit_records(streams)


# =============================================================================
# Unified Data Loader
# =============================================================================

class DataLoader:
    """
    Unified data loading from multiple sources.

    Tries FIT files first, then falls back to Strava API.
    """

    def __init__(
        self,
        fit_directory: Optional[str] = None,
        strava_token: Optional[str] = None,
    ):
        """
        Initialize with available data sources.

        Args:
            fit_directory: Path to directory with FIT files
            strava_token: Strava API access token
        """
        self.fit_source = FitFileSource(fit_directory) if fit_directory else None
        self.strava_source = StravaDataSource(strava_token) if strava_token else None

        if not self.fit_source and not self.strava_source:
            raise ValueError("At least one data source must be provided")

    def load_records_for_entry(
        self,
        entry: GearCalendarEntry,
        prefer_fit: bool = True,
    ) -> Optional[List['FitRecord']]:
        """
        Load activity records for a calendar entry.

        Args:
            entry: Calendar entry with date and source info
            prefer_fit: If True, try FIT files first

        Returns:
            List of FitRecords, or None if not found
        """
        if prefer_fit:
            sources = [self.fit_source, self.strava_source]
        else:
            sources = [self.strava_source, self.fit_source]

        for source in sources:
            if source is None:
                continue

            try:
                if isinstance(source, FitFileSource):
                    fit_data = source.load_for_entry(entry)
                    if fit_data:
                        return fit_data.records
                elif isinstance(source, StravaDataSource):
                    records = source.load_for_entry(entry)
                    if records:
                        return records
            except Exception as e:
                print(f"  Warning: Failed to load from {source.__class__.__name__}: {e}")
                continue

        return None
