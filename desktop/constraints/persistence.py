"""
Persistence Layer for Power-Cadence Constraints

Store and load constraint data with incremental update support.
"""

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    from .models import (
        PowerCadenceObservation,
        GearConstraintProfile,
        ConstraintDataSet,
        CadenceBinStats,
        STANDARD_DURATIONS,
    )
except ImportError:
    from models import (
        PowerCadenceObservation,
        GearConstraintProfile,
        ConstraintDataSet,
        CadenceBinStats,
        STANDARD_DURATIONS,
    )


class ConstraintDataStore:
    """
    Persist raw observations and computed statistics.

    Supports:
    - Incremental appending of new observations
    - Deduplication by effort_id + timestamp
    - JSON and CSV export
    - Metadata tracking
    """

    def __init__(self, data_dir: str):
        """
        Initialize the data store.

        Args:
            data_dir: Directory for storing data files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.raw_observations_path = self.data_dir / "raw_observations.json"
        self.statistics_path = self.data_dir / "constraint_statistics.json"
        self.metadata_path = self.data_dir / "collection_metadata.json"

    # =========================================================================
    # Raw Observations
    # =========================================================================

    def save_observations(
        self,
        observations: List[PowerCadenceObservation],
        append: bool = True,
    ) -> int:
        """
        Save raw observations for reprocessing.

        Args:
            observations: New observations to save
            append: If True, append to existing; if False, overwrite

        Returns:
            Number of new observations added
        """
        existing = []
        if append and self.raw_observations_path.exists():
            existing = self.load_observations()

        # Deduplicate by effort_id + timestamp
        seen: Set[tuple] = {(o.effort_id, o.timestamp_s) for o in existing}
        new_obs = [
            o for o in observations
            if (o.effort_id, o.timestamp_s) not in seen
        ]

        all_obs = existing + new_obs

        # Save
        with open(self.raw_observations_path, 'w') as f:
            json.dump([o.to_dict() for o in all_obs], f, indent=2)

        return len(new_obs)

    def load_observations(self) -> List[PowerCadenceObservation]:
        """Load raw observations."""
        if not self.raw_observations_path.exists():
            return []

        with open(self.raw_observations_path, 'r') as f:
            data = json.load(f)

        return [PowerCadenceObservation.from_dict(d) for d in data]

    def get_observation_count(self) -> int:
        """Get total number of stored observations."""
        obs = self.load_observations()
        return len(obs)

    def get_unique_gears(self) -> List[str]:
        """Get list of unique gear ratios in observations."""
        obs = self.load_observations()
        return sorted(set(o.gear_ratio_str for o in obs))

    def get_unique_dates(self) -> List[date]:
        """Get list of unique dates in observations."""
        obs = self.load_observations()
        return sorted(set(o.source_date for o in obs))

    # =========================================================================
    # Statistics / Profiles
    # =========================================================================

    def save_statistics(
        self,
        data_set: ConstraintDataSet,
    ) -> None:
        """
        Save computed statistics.

        Args:
            data_set: ConstraintDataSet with all profiles
        """
        with open(self.statistics_path, 'w') as f:
            json.dump(data_set.to_dict(), f, indent=2)

    def load_statistics(self) -> Optional[ConstraintDataSet]:
        """Load computed statistics."""
        if not self.statistics_path.exists():
            return None

        with open(self.statistics_path, 'r') as f:
            data = json.load(f)

        return ConstraintDataSet.from_dict(data)

    def get_profile(self, gear_ratio_str: str) -> Optional[GearConstraintProfile]:
        """Get profile for a specific gear ratio."""
        data_set = self.load_statistics()
        if data_set:
            return data_set.get_profile(gear_ratio_str)
        return None

    # =========================================================================
    # CSV Export
    # =========================================================================

    def export_statistics_csv(
        self,
        output_path: Optional[str] = None,
        include_duration_power: bool = True,
    ) -> str:
        """
        Export statistics to CSV format.

        Args:
            output_path: Output file path (default: statistics.csv in data_dir)
            include_duration_power: Include columns for duration-based power (1s-30s)

        Returns:
            Path to exported CSV file
        """
        if output_path is None:
            output_path = str(self.data_dir / "statistics.csv")

        data_set = self.load_statistics()
        if not data_set or not data_set.profiles:
            raise ValueError("No statistics to export")

        rows = []
        for gear_str, profile in sorted(data_set.profiles.items()):
            for bin_stats in profile.bins:
                row = {
                    'gear_ratio': gear_str,
                    'gear_ratio_numeric': bin_stats.gear_ratio,
                    'chainring': profile.chainring,
                    'cog': profile.cog,
                    'cadence_bin': bin_stats.cadence_bin,
                    'cadence_range': bin_stats.cadence_range,
                    'n_samples': bin_stats.n_samples,
                    'n_efforts': bin_stats.n_efforts,
                    'mean_power_W': bin_stats.mean_power_W,
                    'std_power_W': bin_stats.std_power_W,
                    'min_power_W': bin_stats.min_power_W,
                    'max_power_W': bin_stats.max_power_W,
                    'median_power_W': bin_stats.median_power_W,
                    'p90_power_W': bin_stats.p90_power_W,
                    'p95_power_W': bin_stats.p95_power_W,
                    'ci_low_W': bin_stats.ci_low_W,
                    'ci_high_W': bin_stats.ci_high_W,
                    'mean_torque_Nm': bin_stats.mean_torque_Nm,
                    'std_torque_Nm': bin_stats.std_torque_Nm,
                    'max_torque_Nm': bin_stats.max_torque_Nm,
                    'is_interpolated': bin_stats.is_interpolated,
                }

                # Add duration-based power columns
                if include_duration_power:
                    for duration_s in STANDARD_DURATIONS:
                        dur_stats = bin_stats.power_by_duration.get(duration_s)
                        if dur_stats:
                            row[f'max_power_{duration_s}s_W'] = round(dur_stats.max_power_W, 1)
                            row[f'mean_power_{duration_s}s_W'] = round(dur_stats.mean_power_W, 1)
                            row[f'p95_power_{duration_s}s_W'] = round(dur_stats.p95_power_W, 1)
                            row[f'n_efforts_{duration_s}s'] = dur_stats.n_efforts
                        else:
                            row[f'max_power_{duration_s}s_W'] = ''
                            row[f'mean_power_{duration_s}s_W'] = ''
                            row[f'p95_power_{duration_s}s_W'] = ''
                            row[f'n_efforts_{duration_s}s'] = ''

                rows.append(row)

        if rows:
            fieldnames = list(rows[0].keys())
            with open(output_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        return output_path

    def export_observations_csv(self, output_path: Optional[str] = None) -> str:
        """
        Export raw observations to CSV format.

        Args:
            output_path: Output file path (default: observations.csv in data_dir)

        Returns:
            Path to exported CSV file
        """
        if output_path is None:
            output_path = str(self.data_dir / "observations.csv")

        observations = self.load_observations()
        if not observations:
            raise ValueError("No observations to export")

        rows = [o.to_dict() for o in observations]

        if rows:
            fieldnames = list(rows[0].keys())
            with open(output_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        return output_path

    # =========================================================================
    # Metadata
    # =========================================================================

    def save_metadata(self, metadata: dict) -> None:
        """Save collection metadata."""
        # Merge with existing
        existing = self.load_metadata()
        existing.update(metadata)
        existing['last_updated'] = datetime.now().isoformat()

        with open(self.metadata_path, 'w') as f:
            json.dump(existing, f, indent=2)

    def load_metadata(self) -> dict:
        """Load collection metadata."""
        if not self.metadata_path.exists():
            return {}

        with open(self.metadata_path, 'r') as f:
            return json.load(f)

    def get_summary(self) -> dict:
        """
        Get summary of stored data.

        Returns:
            Dict with summary statistics
        """
        obs = self.load_observations()
        stats = self.load_statistics()
        metadata = self.load_metadata()

        summary = {
            'n_observations': len(obs),
            'n_gears': len(self.get_unique_gears()),
            'n_dates': len(self.get_unique_dates()),
            'gear_ratios': self.get_unique_gears(),
        }

        if obs:
            summary['date_range'] = [
                min(o.source_date for o in obs).isoformat(),
                max(o.source_date for o in obs).isoformat(),
            ]
            summary['n_efforts'] = len(set(o.effort_id for o in obs))

        if stats:
            summary['n_profiles'] = len(stats.profiles)

        summary.update(metadata)

        return summary


# =============================================================================
# Helper Functions
# =============================================================================

def merge_data_stores(
    source_stores: List[ConstraintDataStore],
    target_store: ConstraintDataStore,
) -> int:
    """
    Merge multiple data stores into one.

    Args:
        source_stores: List of stores to merge from
        target_store: Store to merge into

    Returns:
        Total number of new observations added
    """
    total_new = 0

    for source in source_stores:
        obs = source.load_observations()
        new_count = target_store.save_observations(obs, append=True)
        total_new += new_count

    return total_new


def create_backup(store: ConstraintDataStore, backup_dir: str) -> str:
    """
    Create a backup of the data store.

    Args:
        store: Store to backup
        backup_dir: Directory for backup

    Returns:
        Path to backup directory
    """
    import shutil
    from datetime import datetime

    backup_path = Path(backup_dir) / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copytree(store.data_dir, backup_path)

    return str(backup_path)
