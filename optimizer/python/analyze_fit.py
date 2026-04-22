#!/usr/bin/env python3
"""
Python bridge script for FIT file analysis.
Wraps the existing fit_analyzer.py functionality for Node.js communication.
"""
import sys
import json
import os
import math
from datetime import datetime

from fit_analyzer import parse_fit_file

try:
    from fitparse import FitFile
except ImportError:
    FitFile = None

def safe_float(val, default=0.0):
    """Safely convert value to float, handling None and NaN."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    """Safely convert value to int, handling None and NaN."""
    return int(safe_float(val, default))


def extract_fit_metadata(file_path):
    """
    Extract metadata from FIT file header and session/activity messages.
    Returns device info, activity date/time, temperature, etc.
    """
    if FitFile is None:
        return {"error": "fitparse library not installed"}

    metadata = {
        "file_name": os.path.basename(file_path),
        "activity_date": None,
        "activity_time": None,
        "device_manufacturer": None,
        "device_product": None,
        "device_serial": None,
        "software_version": None,
        "temperature_c": None,
        "humidity_pct": None,
        "sport": None,
        "sub_sport": None,
        "total_elapsed_time": None,
        "total_distance": None,
        "avg_heart_rate": None,
        "max_heart_rate": None,
        "avg_cadence": None,
        "max_cadence": None,
        "avg_power": None,
        "max_power": None,
        "normalized_power": None,
        "threshold_power": None,
        "training_stress_score": None,
        "intensity_factor": None,
    }

    try:
        fitfile = FitFile(file_path)

        # Extract file_id message (device info)
        for msg in fitfile.get_messages('file_id'):
            for field in msg:
                if field.name == 'manufacturer':
                    metadata['device_manufacturer'] = str(field.value) if field.value else None
                elif field.name == 'product':
                    metadata['device_product'] = str(field.value) if field.value else None
                elif field.name == 'serial_number':
                    metadata['device_serial'] = str(field.value) if field.value else None
                elif field.name == 'time_created':
                    if field.value:
                        try:
                            dt = field.value
                            if isinstance(dt, datetime):
                                metadata['activity_date'] = dt.strftime('%Y-%m-%d')
                                metadata['activity_time'] = dt.strftime('%H:%M:%S')
                            else:
                                metadata['activity_date'] = str(dt)
                        except:
                            pass

        # Extract device_info messages (software version + sensor names)
        sensors = []
        for msg in fitfile.get_messages('device_info'):
            dev = {}
            for field in msg:
                if field.name == 'software_version' and metadata.get('software_version') is None:
                    metadata['software_version'] = str(field.value) if field.value else None
                if field.name == 'manufacturer' and field.value:
                    dev['manufacturer'] = str(field.value)
                elif field.name == 'product_name' and field.value:
                    dev['product_name'] = str(field.value)
                elif field.name == 'product' and field.value:
                    dev['product'] = str(field.value)
                elif field.name == 'device_type' and field.value:
                    dev['device_type'] = str(field.value)
                elif field.name == 'source_type' and field.value:
                    dev['source_type'] = str(field.value)
                elif field.name == 'ant_device_number' and field.value:
                    dev['ant_id'] = int(field.value) if field.value else None
            # Only include remote sensors (ANT+/BLE), skip the recording device itself
            if dev.get('source_type') in ('antplus', 'bluetooth_low_energy') or dev.get('ant_id'):
                name_parts = []
                if dev.get('manufacturer'):
                    name_parts.append(dev['manufacturer'].replace('_', ' ').title())
                if dev.get('product_name'):
                    name_parts.append(dev['product_name'])
                elif dev.get('product'):
                    name_parts.append(str(dev['product']))
                sensor_name = ' '.join(name_parts) if name_parts else None
                dtype = dev.get('device_type', '').lower()
                sensors.append({
                    'name': sensor_name,
                    'type': dtype,
                })
        if sensors:
            metadata['sensors'] = sensors

        # Extract session message (activity summary)
        for msg in fitfile.get_messages('session'):
            for field in msg:
                if field.name == 'sport':
                    metadata['sport'] = str(field.value) if field.value else None
                elif field.name == 'sub_sport':
                    metadata['sub_sport'] = str(field.value) if field.value else None
                elif field.name == 'total_elapsed_time':
                    metadata['total_elapsed_time'] = safe_float(field.value)
                elif field.name == 'total_distance':
                    metadata['total_distance'] = safe_float(field.value)
                elif field.name == 'avg_heart_rate':
                    metadata['avg_heart_rate'] = safe_int(field.value)
                elif field.name == 'max_heart_rate':
                    metadata['max_heart_rate'] = safe_int(field.value)
                elif field.name == 'avg_cadence':
                    metadata['avg_cadence'] = safe_int(field.value)
                elif field.name == 'max_cadence':
                    metadata['max_cadence'] = safe_int(field.value)
                elif field.name == 'avg_power':
                    metadata['avg_power'] = safe_int(field.value)
                elif field.name == 'max_power':
                    metadata['max_power'] = safe_int(field.value)
                elif field.name == 'normalized_power':
                    metadata['normalized_power'] = safe_int(field.value)
                elif field.name == 'threshold_power':
                    metadata['threshold_power'] = safe_int(field.value)
                elif field.name == 'training_stress_score':
                    metadata['training_stress_score'] = safe_float(field.value)
                elif field.name == 'intensity_factor':
                    metadata['intensity_factor'] = safe_float(field.value)
                elif field.name == 'avg_temperature':
                    metadata['temperature_c'] = safe_float(field.value)
                elif field.name == 'start_time':
                    if field.value and metadata['activity_date'] is None:
                        try:
                            dt = field.value
                            if isinstance(dt, datetime):
                                metadata['activity_date'] = dt.strftime('%Y-%m-%d')
                                metadata['activity_time'] = dt.strftime('%H:%M:%S')
                        except:
                            pass
            break  # Only need first session

        # Check for weather/environment data in developer fields or event messages
        for msg in fitfile.get_messages():
            for field in msg:
                if 'temperature' in field.name.lower() and metadata['temperature_c'] is None:
                    metadata['temperature_c'] = safe_float(field.value)
                elif 'humidity' in field.name.lower() and metadata['humidity_pct'] is None:
                    metadata['humidity_pct'] = safe_float(field.value)

        # Filter out None values for cleaner output
        metadata = {k: v for k, v in metadata.items() if v is not None}

    except Exception as e:
        metadata['error'] = str(e)

    return metadata


def parse_fit_for_chart(file_path):
    """Parse FIT file and return data suitable for charting, including metadata."""
    try:
        # Get metadata first
        metadata = extract_fit_metadata(file_path)

        result = parse_fit_file(file_path)

        # parse_fit_file returns (df, lap_markers) tuple
        if isinstance(result, tuple):
            df, lap_markers = result
        else:
            df = result

        if df is None or df.empty:
            return {"success": False, "error": "Failed to parse FIT file or no data found"}

        # Determine column names (FIT files use 'power', 'cadence', 'speed', etc.)
        power_col = 'power' if 'power' in df.columns else 'power_watts' if 'power_watts' in df.columns else None
        speed_col = 'speed' if 'speed' in df.columns else 'enhanced_speed' if 'enhanced_speed' in df.columns else None
        cadence_col = 'cadence' if 'cadence' in df.columns else None
        distance_col = 'distance' if 'distance' in df.columns else None

        # Calculate elapsed time from timestamps
        if 'timestamp' in df.columns:
            first_ts = df['timestamp'].iloc[0]
            df['elapsed_time_s'] = (df['timestamp'] - first_ts).dt.total_seconds()
        else:
            df['elapsed_time_s'] = range(len(df))

        # Convert to list of records for JSON
        records = []
        for idx, row in df.iterrows():
            # Speed from FIT is typically in m/s, convert to km/h
            speed_mps = safe_float(row.get(speed_col, 0)) if speed_col else 0
            speed_kph = speed_mps * 3.6 if speed_mps < 100 else speed_mps  # Already in kph if > 100

            record = {
                "elapsed_s": safe_float(row.get('elapsed_time_s', idx)),
                "power_W": safe_int(row.get(power_col, 0)) if power_col else 0,
                "speed_kph": round(speed_kph, 2),
                "cadence_rpm": safe_int(row.get(cadence_col, 0)) if cadence_col else 0,
                "distance_m": safe_float(row.get(distance_col, 0)) if distance_col else 0,
            }
            records.append(record)

        # Calculate summary stats
        power_values = [r["power_W"] for r in records if r["power_W"] > 0]
        speed_values = [r["speed_kph"] for r in records if r["speed_kph"] > 0]
        cadence_values = [r["cadence_rpm"] for r in records if r["cadence_rpm"] > 0]

        summary = {
            "total_records": len(records),
            "duration_s": records[-1]["elapsed_s"] if records else 0,
            "avg_power": int(sum(power_values) / len(power_values)) if power_values else 0,
            "max_power": max(power_values) if power_values else 0,
            "avg_speed": round(sum(speed_values) / len(speed_values), 1) if speed_values else 0,
            "max_speed": round(max(speed_values), 1) if speed_values else 0,
            "avg_cadence": int(sum(cadence_values) / len(cadence_values)) if cadence_values else 0,
            "max_cadence": max(cadence_values) if cadence_values else 0,
        }

        return {
            "success": True,
            "summary": summary,
            "metadata": metadata,
            "records": records
        }
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


def generate_power_curve_from_fit(file_path, start_time, end_time):
    """
    Generate best power curve (1-60s durations) from FIT file selection.
    Similar to MMP (Mean Maximal Power) for the selected segment.
    """
    try:
        result = parse_fit_file(file_path)

        if isinstance(result, tuple):
            df, _ = result
        else:
            df = result

        if df is None or df.empty:
            return {"success": False, "error": "Failed to parse FIT file"}

        # Determine power column
        power_col = 'power' if 'power' in df.columns else 'power_watts' if 'power_watts' in df.columns else None

        if not power_col:
            return {"success": False, "error": "No power data in FIT file"}

        # Calculate elapsed time
        if 'timestamp' in df.columns:
            first_ts = df['timestamp'].iloc[0]
            df['elapsed_time_s'] = (df['timestamp'] - first_ts).dt.total_seconds()
        else:
            df['elapsed_time_s'] = list(range(len(df)))

        # Filter to the selected time range
        mask = (df['elapsed_time_s'] >= start_time) & (df['elapsed_time_s'] <= end_time)
        section_df = df[mask].copy().reset_index(drop=True)

        if section_df.empty:
            return {"success": False, "error": "No data in selected time range"}

        power_data = section_df[power_col].fillna(0).values

        # Calculate best power for durations 1-60s
        # Standard power curve durations for track cycling
        durations = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40, 50, 60]
        power_curve = []

        for duration in durations:
            if len(power_data) >= duration:
                # Rolling average to find best power for this duration
                best_power = 0
                for i in range(len(power_data) - duration + 1):
                    avg = sum(power_data[i:i+duration]) / duration
                    if avg > best_power:
                        best_power = avg
                power_curve.append({
                    "duration_s": duration,
                    "power_W": int(round(best_power))
                })

        # Create seated/standing curves
        # Standing = raw MMP (what was actually measured during max effort)
        # Seated = standing * factor, converging at 40s
        # Factor: 0.71 (1/1.4) at 1s, 1.0 at 40s (linear interpolation)
        power_curve_full = []
        convergence_seconds = 40
        min_factor = 1 / 1.4  # ~0.714

        for pc in power_curve:
            duration = pc['duration_s']
            standing_power = pc['power_W']  # Raw MMP = standing

            # Calculate seated factor (converges to 1.0 at 40s)
            if duration >= convergence_seconds:
                factor = 1.0
            else:
                factor = min_factor + (1.0 - min_factor) * ((duration - 1) / (convergence_seconds - 1))

            seated_power = int(round(standing_power * factor))

            power_curve_full.append({
                "duration_s": duration,
                "seated_W": seated_power,
                "standing_W": standing_power
            })

        # Summary
        segment_duration = len(power_data)
        summary = {
            "segment_duration_s": segment_duration,
            "avg_power_W": int(sum(power_data) / len(power_data)) if power_data.any() else 0,
            "max_power_W": int(max(power_data)) if len(power_data) > 0 else 0,
            "durations_available": [pc['duration_s'] for pc in power_curve],
        }

        return {
            "success": True,
            "power_curve": power_curve_full,
            "summary": summary
        }
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


def extract_power_curve(file_path, start_time, end_time):
    """Extract power curve data from a section of the ride."""
    try:
        result = parse_fit_file(file_path)

        if isinstance(result, tuple):
            df, _ = result
        else:
            df = result

        if df is None or df.empty:
            return {"success": False, "error": "Failed to parse FIT file"}

        # Determine power column
        power_col = 'power' if 'power' in df.columns else 'power_watts' if 'power_watts' in df.columns else None

        # Calculate elapsed time
        if 'timestamp' in df.columns:
            first_ts = df['timestamp'].iloc[0]
            df['elapsed_time_s'] = (df['timestamp'] - first_ts).dt.total_seconds()
        else:
            df['elapsed_time_s'] = range(len(df))

        # Filter to the selected time range
        mask = (df['elapsed_time_s'] >= start_time) & (df['elapsed_time_s'] <= end_time)
        section_df = df[mask]

        if section_df.empty:
            return {"success": False, "error": "No data in selected time range"}

        power_data = section_df[power_col].fillna(0).values if power_col and power_col in section_df.columns else []

        # Calculate best power for various durations
        durations = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40, 50, 60]
        power_curve = []

        for duration in durations:
            if len(power_data) >= duration:
                # Rolling average to find best power for this duration
                best_power = 0
                for i in range(len(power_data) - duration + 1):
                    avg = sum(power_data[i:i+duration]) / duration
                    if avg > best_power:
                        best_power = avg
                power_curve.append({
                    "duration_s": duration,
                    "seated_W": int(best_power),
                    "standing_W": int(best_power * 1.05)
                })

        return {
            "success": True,
            "power_curve": power_curve
        }
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


def extract_power_by_distance(file_path, start_time, end_time, chainring, cog,
                               wheel_circ_mm=2096, s_total=895.0):
    """
    Extract power-by-distance profile from FIT file.

    Uses cadence to calculate speed, integrates distance BACKWARDS from the
    end point (finish line at s_total). User only needs to select the END
    of the effort - we automatically cover 0m to s_total.

    Args:
        file_path: Path to FIT file
        start_time: Start time in seconds (ignored - we auto-calculate)
        end_time: End time in seconds - the finish line moment
        chainring: Number of teeth on chainring
        cog: Number of teeth on rear cog
        wheel_circ_mm: Wheel circumference in mm (default 2096)
        s_total: Total distance / finish line position (default 895m)

    Returns:
        Dict with power_profile array of {s_m, P_W} objects from 0 to s_total
    """
    import numpy as np

    try:
        result = parse_fit_file(file_path)

        if isinstance(result, tuple):
            df, _ = result
        else:
            df = result

        if df is None or df.empty:
            return {"success": False, "error": "Failed to parse FIT file"}

        # Determine column names
        power_col = 'power' if 'power' in df.columns else 'power_watts' if 'power_watts' in df.columns else None
        cadence_col = 'cadence' if 'cadence' in df.columns else None

        if not power_col:
            return {"success": False, "error": "No power data in FIT file"}
        if not cadence_col:
            return {"success": False, "error": "No cadence data in FIT file - required for distance calculation"}

        # Calculate elapsed time
        if 'timestamp' in df.columns:
            first_ts = df['timestamp'].iloc[0]
            df['elapsed_time_s'] = (df['timestamp'] - first_ts).dt.total_seconds()
        else:
            df['elapsed_time_s'] = list(range(len(df)))

        # Calculate speed and distance for ALL data up to end_time
        gear_ratio = chainring / cog
        wheel_circ_m = wheel_circ_mm / 1000.0

        # Get all data up to end_time
        mask = df['elapsed_time_s'] <= end_time
        full_df = df[mask].copy().reset_index(drop=True)

        if full_df.empty:
            return {"success": False, "error": "No data before selected end time"}

        # Check for valid cadence data
        valid_cadence = full_df[cadence_col].dropna()
        if len(valid_cadence) == 0 or valid_cadence.max() == 0:
            return {"success": False, "error": "No valid cadence data"}

        # Calculate speed from cadence: speed = (cadence/60) * gear_ratio * wheel_circ
        full_df['speed_mps'] = full_df[cadence_col].fillna(0) / 60.0 * gear_ratio * wheel_circ_m

        # Calculate time delta between samples
        full_df['dt_s'] = full_df['elapsed_time_s'].diff().fillna(1.0)

        # Integrate speed to get distance (cumulative from start)
        full_df['ds_m'] = full_df['speed_mps'] * full_df['dt_s']
        full_df['distance_from_start'] = full_df['ds_m'].cumsum()

        total_distance_at_end = full_df['distance_from_start'].iloc[-1]

        if total_distance_at_end <= 0:
            return {"success": False, "error": "Could not calculate valid distance from cadence data"}

        # Now calculate s_m: distance along track where END = s_total (finish line)
        # s_m = s_total - (total_distance_at_end - distance_from_start)
        full_df['s_m'] = s_total - (total_distance_at_end - full_df['distance_from_start'])

        # Filter to only include data where s_m >= 0 (on the track)
        track_df = full_df[full_df['s_m'] >= 0].copy().reset_index(drop=True)

        if track_df.empty:
            return {"success": False, "error": "No data maps to track distance 0-895m. Check end time selection."}

        s_min = max(0, track_df['s_m'].min())  # Floor to 0
        s_max = track_df['s_m'].max()

        if np.isnan(s_min) or np.isnan(s_max):
            return {"success": False, "error": "Invalid distance calculation - check cadence data"}

        # Round to nearest 10m for grid, starting from 0
        s_start_grid = 0  # Always start from 0
        s_end_grid = int(np.floor(s_max / 10) * 10)

        # Create 10m grid points from 0 to end
        grid_points = list(np.arange(s_start_grid, s_end_grid + 10, 10))

        # Include 695m marker (timed 200m start) if in range
        if 695 <= s_max and 695 not in grid_points:
            grid_points.append(695)
            grid_points.sort()

        # Include finish line (895m) if data extends near it
        if s_max >= s_total - 5 and s_total not in grid_points:
            grid_points.append(s_total)

        grid_points = np.array(grid_points)

        # Interpolate power onto grid
        # For points before our data starts, use the first available power value
        first_s = track_df['s_m'].iloc[0]
        first_power = track_df[power_col].iloc[0]

        power_interp = []
        for s in grid_points:
            if s < first_s:
                # Before data starts - use first power value (or could use 0)
                power_interp.append(first_power)
            else:
                # Interpolate from data
                p = np.interp(s, track_df['s_m'].values, track_df[power_col].fillna(0).values)
                power_interp.append(p)

        power_interp = np.array(power_interp)

        # Build power profile
        power_profile = [
            {"s_m": float(s), "P_W": int(round(p))}
            for s, p in zip(grid_points, power_interp)
        ]

        # Summary stats
        summary = {
            "total_distance_m": float(total_distance_at_end),
            "s_range_start": float(s_min),
            "s_range_end": float(s_max),
            "grid_points": len(power_profile),
            "gear_ratio": float(gear_ratio),
            "avg_power_W": int(np.mean(power_interp)),
            "max_power_W": int(np.max(power_interp)),
        }

        return {
            "success": True,
            "power_profile": power_profile,
            "summary": summary
        }

    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


def main():
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)

        action = input_data.get("action", "parse")
        file_path = input_data.get("file_path")

        if not file_path:
            print(json.dumps({"success": False, "error": "No file path provided"}))
            return

        if action == "parse":
            result = parse_fit_for_chart(file_path)
        elif action == "extract_power_curve":
            result = extract_power_curve(
                file_path,
                input_data.get("start_time", 0),
                input_data.get("end_time", 9999)
            )
        elif action == "extract_power_by_distance":
            result = extract_power_by_distance(
                file_path,
                input_data.get("start_time", 0),
                input_data.get("end_time", 9999),
                input_data.get("chainring", 55),
                input_data.get("cog", 14),
                input_data.get("wheel_circ_mm", 2096),
                input_data.get("s_total", 895.0)
            )
        elif action == "generate_power_curve":
            result = generate_power_curve_from_fit(
                file_path,
                input_data.get("start_time", 0),
                input_data.get("end_time", 9999)
            )
        elif action == "get_metadata":
            result = {
                "success": True,
                "metadata": extract_fit_metadata(file_path)
            }
        else:
            result = {"success": False, "error": f"Unknown action: {action}"}

        print(json.dumps(result))
    except Exception as e:
        import traceback
        print(json.dumps({"success": False, "error": str(e), "traceback": traceback.format_exc()}))


if __name__ == "__main__":
    main()
