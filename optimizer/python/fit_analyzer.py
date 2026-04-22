"""
FIT File Analyzer for Flying 200m
Extracts power and cadence data from FIT files, converts to distance-based data
using gear ratio and wheel size, and allows overlay with buildup profiles.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict
import os

try:
    from fitparse import FitFile
except ImportError:
    print("fitparse library not found. Install with: pip install fitparse")
    FitFile = None


# Default wheel circumference in mm for 700c track wheel with 23mm tire
# Common track wheel: 700c x 23mm = ~2096mm circumference
DEFAULT_WHEEL_CIRCUMFERENCE_MM = 2096


def calculate_speed_from_cadence(cadence_rpm: float, chainring: int, cog: int,
                                  wheel_circumference_mm: float = DEFAULT_WHEEL_CIRCUMFERENCE_MM) -> float:
    """
    Calculate speed (m/s) from cadence using gear ratio.

    Speed = (cadence_rpm / 60) * gear_ratio * wheel_circumference

    Args:
        cadence_rpm: Pedaling cadence in RPM
        chainring: Number of teeth on chainring
        cog: Number of teeth on rear cog
        wheel_circumference_mm: Wheel circumference in millimeters

    Returns:
        Speed in m/s
    """
    if cadence_rpm <= 0 or cog <= 0:
        return 0.0
    gear_ratio = chainring / cog
    revs_per_second = cadence_rpm / 60.0
    wheel_circumference_m = wheel_circumference_mm / 1000.0
    speed_mps = revs_per_second * gear_ratio * wheel_circumference_m
    return speed_mps


def parse_fit_file(fit_path: str) -> pd.DataFrame:
    """
    Parse a FIT file and extract all record data with timestamps.

    Returns DataFrame with columns: timestamp, power, cadence, speed, heart_rate, etc.
    """
    if FitFile is None:
        raise ImportError("fitparse library not installed")

    records = []
    lap_markers = []

    try:
        fitfile = FitFile(fit_path)

        # Extract lap/index markers
        for lap in fitfile.get_messages('lap'):
            lap_data = {}
            for field in lap:
                lap_data[field.name] = field.value
            lap_markers.append(lap_data)

        # Extract record data
        for record in fitfile.get_messages('record'):
            record_data = {}
            for field in record:
                record_data[field.name] = field.value
            records.append(record_data)

    except Exception as e:
        raise Exception(f"Error parsing FIT file: {e}")

    df = pd.DataFrame(records)

    # Convert timestamp to datetime if present
    if 'timestamp' in df.columns:
        # FIT timestamps are often datetime objects already
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])

    return df, lap_markers


def extract_segment_between_markers(df: pd.DataFrame, lap_markers: List[Dict],
                                     start_marker_idx: int = 0,
                                     end_marker_idx: Optional[int] = None) -> pd.DataFrame:
    """
    Extract data between two lap/index markers.

    Args:
        df: Full DataFrame from parse_fit_file
        lap_markers: List of lap marker dictionaries
        start_marker_idx: Index of starting lap marker (0-based)
        end_marker_idx: Index of ending lap marker (None = end of file)

    Returns:
        Filtered DataFrame containing only records between markers
    """
    if not lap_markers:
        print("No lap markers found in file")
        return df

    if start_marker_idx >= len(lap_markers):
        raise ValueError(f"start_marker_idx {start_marker_idx} >= number of markers {len(lap_markers)}")

    # Get start timestamp from marker
    start_time = lap_markers[start_marker_idx].get('start_time') or lap_markers[start_marker_idx].get('timestamp')

    # Get end timestamp
    if end_marker_idx is not None and end_marker_idx < len(lap_markers):
        end_time = lap_markers[end_marker_idx].get('start_time') or lap_markers[end_marker_idx].get('timestamp')
    else:
        end_time = df['timestamp'].max()

    # Filter DataFrame
    mask = (df['timestamp'] >= start_time) & (df['timestamp'] <= end_time)
    segment_df = df[mask].copy()

    # Reset time to start from 0
    if not segment_df.empty:
        segment_df['elapsed_s'] = (segment_df['timestamp'] - segment_df['timestamp'].iloc[0]).dt.total_seconds()

    return segment_df


def extract_segment_by_time(df: pd.DataFrame, start_time_s: float = 0.0,
                             end_time_s: Optional[float] = None) -> pd.DataFrame:
    """
    Extract data between two time points (in seconds from start of file).

    Args:
        df: Full DataFrame from parse_fit_file
        start_time_s: Start time in seconds from beginning of file
        end_time_s: End time in seconds (None = end of file)

    Returns:
        Filtered DataFrame containing only records in the time range
    """
    if df.empty or 'timestamp' not in df.columns:
        return df

    # Calculate elapsed time from start of file
    file_start = df['timestamp'].iloc[0]
    df = df.copy()
    df['file_elapsed_s'] = (df['timestamp'] - file_start).dt.total_seconds()

    # Filter by time range
    mask = df['file_elapsed_s'] >= start_time_s
    if end_time_s is not None:
        mask = mask & (df['file_elapsed_s'] <= end_time_s)

    segment_df = df[mask].copy()

    # Reset elapsed time to start from 0 for the segment
    if not segment_df.empty:
        segment_df['elapsed_s'] = segment_df['file_elapsed_s'] - segment_df['file_elapsed_s'].iloc[0]

    # Drop the temporary column
    if 'file_elapsed_s' in segment_df.columns:
        segment_df = segment_df.drop(columns=['file_elapsed_s'])

    return segment_df


def convert_time_to_distance(df: pd.DataFrame, chainring: int, cog: int,
                              wheel_circumference_mm: float = DEFAULT_WHEEL_CIRCUMFERENCE_MM,
                              use_fit_speed: bool = False) -> pd.DataFrame:
    """
    Convert time-based FIT data to distance-based data.

    Uses cadence + gear ratio to calculate speed, then integrates to get distance.
    Alternatively can use the speed field from the FIT file if available.

    Args:
        df: DataFrame with 'cadence' and 'elapsed_s' columns
        chainring: Number of teeth on chainring
        cog: Number of teeth on rear cog
        wheel_circumference_mm: Wheel circumference in millimeters
        use_fit_speed: If True, use 'speed' field from FIT file instead of calculating

    Returns:
        DataFrame with additional columns: calculated_speed_mps, distance_m
    """
    df = df.copy()

    # Calculate speed from cadence
    if 'cadence' in df.columns:
        df['calculated_speed_mps'] = df['cadence'].apply(
            lambda c: calculate_speed_from_cadence(c, chainring, cog, wheel_circumference_mm) if pd.notna(c) else 0.0
        )
    else:
        df['calculated_speed_mps'] = 0.0

    # Use FIT speed if requested and available
    if use_fit_speed and 'speed' in df.columns:
        df['speed_mps'] = df['speed'].fillna(0.0)
    else:
        df['speed_mps'] = df['calculated_speed_mps']

    # Calculate time differences
    if 'elapsed_s' in df.columns:
        df['dt_s'] = df['elapsed_s'].diff().fillna(0.0)
    else:
        df['dt_s'] = 1.0  # Assume 1 second intervals if no timestamp

    # Integrate speed to get distance
    df['ds_m'] = df['speed_mps'] * df['dt_s']
    df['distance_m'] = df['ds_m'].cumsum()

    return df


def resample_to_distance_grid(df: pd.DataFrame, ds: float = 0.25,
                               max_distance: Optional[float] = None) -> pd.DataFrame:
    """
    Resample time-based data onto a regular distance grid.

    Args:
        df: DataFrame with 'distance_m' and other columns to resample
        ds: Distance step in meters
        max_distance: Maximum distance (None = use max from data)

    Returns:
        DataFrame with regular distance spacing
    """
    if max_distance is None:
        max_distance = df['distance_m'].max()

    # Create distance grid
    distance_grid = np.arange(0, max_distance + ds, ds)

    # Columns to interpolate
    interp_cols = ['power', 'cadence', 'speed_mps', 'calculated_speed_mps', 'elapsed_s']
    interp_cols = [c for c in interp_cols if c in df.columns]

    # Create output DataFrame
    result = pd.DataFrame({'distance_m': distance_grid})

    # Interpolate each column
    for col in interp_cols:
        valid_mask = df[col].notna() & df['distance_m'].notna()
        if valid_mask.sum() > 1:
            result[col] = np.interp(
                distance_grid,
                df.loc[valid_mask, 'distance_m'].values,
                df.loc[valid_mask, col].values
            )
        else:
            result[col] = np.nan

    return result


def analyze_fit_file(fit_path: str, chainring: int, cog: int,
                      wheel_circumference_mm: float = DEFAULT_WHEEL_CIRCUMFERENCE_MM,
                      start_marker_idx: int = 0,
                      end_marker_idx: Optional[int] = None,
                      ds: float = 0.25) -> Tuple[pd.DataFrame, Dict]:
    """
    Complete analysis pipeline: parse FIT file, extract segment, convert to distance.

    Args:
        fit_path: Path to FIT file
        chainring: Number of teeth on chainring
        cog: Number of teeth on rear cog
        wheel_circumference_mm: Wheel circumference in millimeters
        start_marker_idx: Index of starting lap marker
        end_marker_idx: Index of ending lap marker (None = end of file)
        ds: Distance step for resampling

    Returns:
        Tuple of (resampled DataFrame, metadata dict)
    """
    # Parse file
    df, lap_markers = parse_fit_file(fit_path)

    # Extract segment
    segment_df = extract_segment_between_markers(df, lap_markers, start_marker_idx, end_marker_idx)

    # Convert to distance
    distance_df = convert_time_to_distance(segment_df, chainring, cog, wheel_circumference_mm)

    # Resample to regular grid
    resampled_df = resample_to_distance_grid(distance_df, ds)

    # Calculate metadata
    metadata = {
        'file': os.path.basename(fit_path),
        'total_markers': len(lap_markers),
        'segment_start_marker': start_marker_idx,
        'segment_end_marker': end_marker_idx,
        'total_records': len(df),
        'segment_records': len(segment_df),
        'total_distance_m': resampled_df['distance_m'].max() if not resampled_df.empty else 0,
        'total_time_s': segment_df['elapsed_s'].max() if 'elapsed_s' in segment_df.columns else 0,
        'chainring': chainring,
        'cog': cog,
        'gear_ratio': chainring / cog,
        'wheel_circumference_mm': wheel_circumference_mm,
    }

    if 'power' in resampled_df.columns:
        metadata['avg_power'] = resampled_df['power'].mean()
        metadata['max_power'] = resampled_df['power'].max()

    if 'cadence' in resampled_df.columns:
        metadata['avg_cadence'] = resampled_df['cadence'].mean()
        metadata['max_cadence'] = resampled_df['cadence'].max()

    return resampled_df, metadata


def align_to_finish_line(df: pd.DataFrame, finish_line_s: float = 895.0) -> pd.DataFrame:
    """
    Align FIT data so that it ends at the finish line.

    The FIT data always ENDS at the finish line (last ~20m at ~60kph = ~1s).
    This function transforms distance_m to s_m (profile coordinates) by
    aligning the end of the FIT segment to the finish line and mapping backwards.

    s_m = finish_line_s - (total_distance - distance_m)

    Args:
        df: DataFrame with 'distance_m' column from FIT analysis
        finish_line_s: Position of finish line in profile coordinates (default 895m)

    Returns:
        DataFrame with additional 's_m' column for profile alignment
    """
    df = df.copy()

    if 'distance_m' not in df.columns or df.empty:
        df['s_m'] = np.nan
        return df

    total_distance = df['distance_m'].max()

    # s_m = finish_line - (total_distance - distance_m)
    # This means: at distance_m=total_distance (end of FIT), s_m=finish_line_s
    # At distance_m=0 (start of FIT), s_m = finish_line_s - total_distance
    df['s_m'] = finish_line_s - (total_distance - df['distance_m'])

    return df


def analyze_fit_file_by_time(fit_path: str, chainring: int, cog: int,
                              wheel_circumference_mm: float = DEFAULT_WHEEL_CIRCUMFERENCE_MM,
                              start_time_s: float = 0.0,
                              end_time_s: Optional[float] = None,
                              ds: float = 0.25,
                              align_to_finish: bool = True,
                              finish_line_s: float = 895.0) -> Tuple[pd.DataFrame, Dict]:
    """
    Complete analysis pipeline using time-based segment selection.

    Args:
        fit_path: Path to FIT file
        chainring: Number of teeth on chainring
        cog: Number of teeth on rear cog
        wheel_circumference_mm: Wheel circumference in millimeters
        start_time_s: Start time in seconds from beginning of file
        end_time_s: End time in seconds (None = end of file)
        ds: Distance step for resampling
        align_to_finish: If True, align FIT data so end corresponds to finish line
        finish_line_s: Position of finish line in profile coordinates (default 895m = S_TOTAL)

    Returns:
        Tuple of (resampled DataFrame, metadata dict)
    """
    # Parse file
    df, lap_markers = parse_fit_file(fit_path)

    # Extract segment by time
    segment_df = extract_segment_by_time(df, start_time_s, end_time_s)

    # Convert to distance
    distance_df = convert_time_to_distance(segment_df, chainring, cog, wheel_circumference_mm)

    # Resample to regular grid
    resampled_df = resample_to_distance_grid(distance_df, ds)

    # Align to finish line (FIT data ends at finish)
    if align_to_finish:
        resampled_df = align_to_finish_line(resampled_df, finish_line_s)

    # Calculate metadata
    metadata = {
        'file': os.path.basename(fit_path),
        'start_time_s': start_time_s,
        'end_time_s': end_time_s,
        'total_records': len(df),
        'segment_records': len(segment_df),
        'total_distance_m': resampled_df['distance_m'].max() if not resampled_df.empty else 0,
        'total_time_s': segment_df['elapsed_s'].max() if 'elapsed_s' in segment_df.columns and not segment_df.empty else 0,
        'chainring': chainring,
        'cog': cog,
        'gear_ratio': chainring / cog,
        'wheel_circumference_mm': wheel_circumference_mm,
        'aligned_to_finish': align_to_finish,
        'finish_line_s': finish_line_s,
    }

    # Add aligned distance range to metadata
    if align_to_finish and 's_m' in resampled_df.columns:
        metadata['s_m_start'] = resampled_df['s_m'].min()
        metadata['s_m_end'] = resampled_df['s_m'].max()

    if 'power' in resampled_df.columns:
        metadata['avg_power'] = resampled_df['power'].mean()
        metadata['max_power'] = resampled_df['power'].max()

    if 'cadence' in resampled_df.columns:
        metadata['avg_cadence'] = resampled_df['cadence'].mean()
        metadata['max_cadence'] = resampled_df['cadence'].max()

    return resampled_df, metadata


def plot_fit_vs_profile(fit_df: pd.DataFrame, profile_df: pd.DataFrame = None,
                         title: str = "FIT Data vs Profile",
                         save_path: Optional[str] = None):
    """
    Plot FIT file data, optionally overlaid with profile data.

    Args:
        fit_df: DataFrame from analyze_fit_file with 'distance_m', 'power', 'cadence'
        profile_df: Optional profile DataFrame with 's_m', 'P_W' columns
        title: Plot title
        save_path: Optional path to save figure
    """
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle(title, fontsize=14, fontweight='bold')

    # Plot 1: Power vs Distance
    ax1 = axes[0]
    if 'power' in fit_df.columns:
        ax1.plot(fit_df['distance_m'], fit_df['power'], 'b-', linewidth=1.5,
                 label='FIT Power', alpha=0.8)

    if profile_df is not None and 'P_W' in profile_df.columns:
        ax1.plot(profile_df['s_m'], profile_df['P_W'], 'r--', linewidth=2,
                 label='Profile Power', alpha=0.8)

    ax1.set_xlabel('Distance (m)')
    ax1.set_ylabel('Power (W)')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.set_title('Power vs Distance')

    # Plot 2: Speed/Cadence vs Distance
    ax2 = axes[1]

    if 'speed_mps' in fit_df.columns:
        speed_kph = fit_df['speed_mps'] * 3.6
        ax2.plot(fit_df['distance_m'], speed_kph, 'g-', linewidth=1.5,
                 label='Speed (km/h)', alpha=0.8)

    # Secondary axis for cadence
    if 'cadence' in fit_df.columns:
        ax2_twin = ax2.twinx()
        ax2_twin.plot(fit_df['distance_m'], fit_df['cadence'], 'orange',
                      linewidth=1, label='Cadence (RPM)', alpha=0.7)
        ax2_twin.set_ylabel('Cadence (RPM)', color='orange')
        ax2_twin.tick_params(axis='y', labelcolor='orange')

    ax2.set_xlabel('Distance (m)')
    ax2.set_ylabel('Speed (km/h)', color='green')
    ax2.tick_params(axis='y', labelcolor='green')
    ax2.grid(True, alpha=0.3)
    ax2.set_title('Speed & Cadence vs Distance')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Chart saved to: {save_path}")

    plt.show()


def list_lap_markers(fit_path: str) -> List[Dict]:
    """
    List all lap markers in a FIT file for user reference.

    Returns list of marker info dicts.
    """
    _, lap_markers = parse_fit_file(fit_path)

    print(f"\nLap markers in {os.path.basename(fit_path)}:")
    print("-" * 60)

    for i, marker in enumerate(lap_markers):
        start_time = marker.get('start_time') or marker.get('timestamp', 'N/A')
        total_time = marker.get('total_elapsed_time', 'N/A')
        distance = marker.get('total_distance', 'N/A')

        print(f"  [{i}] Start: {start_time}, Duration: {total_time}s, Distance: {distance}m")

    print("-" * 60)
    return lap_markers


# CLI interface for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python fit_analyzer.py <fit_file> [chainring] [cog] [wheel_circ_mm]")
        print("\nExample: python fit_analyzer.py ride.fit 55 14 2096")
        sys.exit(1)

    fit_file = sys.argv[1]
    chainring = int(sys.argv[2]) if len(sys.argv) > 2 else 55
    cog = int(sys.argv[3]) if len(sys.argv) > 3 else 14
    wheel_circ_mm = int(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_WHEEL_CIRCUMFERENCE_MM

    print(f"Analyzing: {fit_file}")
    print(f"Gear: {chainring}x{cog}")
    print(f"Wheel circumference: {wheel_circ_mm} mm")

    # List markers
    markers = list_lap_markers(fit_file)

    if markers:
        # Analyze first segment
        df, meta = analyze_fit_file(fit_file, chainring, cog, wheel_circ_mm, start_marker_idx=0)

        print("\nMetadata:")
        for k, v in meta.items():
            print(f"  {k}: {v}")

        # Plot
        plot_fit_vs_profile(df, title=f"FIT Analysis: {meta['file']}")
