"""
Flying 200 V2 - Effort Detection

Auto-detect Flying 200 efforts from FIT file data.
Ported from flying200-mobile/store/simulationStore.ts detectFlying200Efforts()

Key algorithm:
1. Find DROP-OFF points (sharp power AND speed drops = finish line)
2. Work backwards from drop-off to find:
   - SPRINT phase: sustained high power (20-35s)
   - RAMP phase: speed building up (50-70s)
3. Score confidence (0-100) based on pattern match
"""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

from .parser import FitRecord


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class DetectedEffort:
    """A detected Flying 200 effort."""
    start_index: int          # Index in records list
    end_index: int            # Index in records list
    start_time_s: float       # Elapsed time at effort start [s]
    end_time_s: float         # Elapsed time at effort end [s]
    duration_s: float         # Total duration [s]
    sprint_start_s: float     # When high-power sprint began [s]
    sprint_duration_s: float  # Sprint phase duration [s]
    ramp_duration_s: float    # Ramp phase duration [s]
    max_power_W: float        # Maximum power in effort [W]
    avg_power_W: float        # Average power over entire effort [W]
    sprint_avg_power_W: float # Average power during sprint [W]
    confidence: int           # Confidence score 0-100
    effort_type: int = 200    # Estimated effort type (200, 150, 100, 50)

    @property
    def is_high_confidence(self) -> bool:
        """True if confidence >= 70."""
        return self.confidence >= 70


# =============================================================================
# Detection Functions
# =============================================================================

def detect_flying_efforts(
    records: List[FitRecord],
    effort_type: int = 200,
    verbose: bool = False,
) -> List[DetectedEffort]:
    """
    Auto-detect Flying 200 efforts in FIT file data.

    Pattern: gradual ramp up from low speed (~15-25km/h),
    then sprint at high power, then sharp drop.

    Key difference from STANDING STARTS:
    - Flying efforts: start at 10-25 km/h, gradual 50-70s buildup
    - Standing starts: start at 0 km/h, 0W period before, explosive 0→max

    Args:
        records: List of FIT records
        effort_type: Expected effort type (200, 150, 100, 50)
        verbose: Print debug output

    Returns:
        List of detected efforts, sorted by start time
    """
    if len(records) < 50:
        return []

    efforts: List[DetectedEffort] = []

    # Calculate file max power for dynamic thresholds
    file_max_power = max(r.power_W for r in records)

    # Thresholds based on athlete's max power - CAPPED for files with high-power sprints
    HIGH_POWER_THRESHOLD = min(file_max_power * 0.30, 500)
    LOW_POWER_THRESHOLD = min(file_max_power * 0.15, 200)
    RAMP_POWER_CEILING = min(file_max_power * 0.45, 450)
    RAMP_POWER_FLOOR = 50

    # Speed-based thresholds
    HIGH_SPEED_THRESHOLD = 55  # km/h
    LOW_SPEED_THRESHOLD = 25   # km/h

    if verbose:
        print(f"Auto-detect: fileMaxPower={file_max_power:.0f}W, "
              f"highThreshold={HIGH_POWER_THRESHOLD:.0f}W, "
              f"rampCeiling={RAMP_POWER_CEILING:.0f}W")

    # Helper functions
    def avg_power(start: int, end: int) -> float:
        vals = [records[i].power_W for i in range(start, min(end + 1, len(records)))]
        return np.mean(vals) if vals else 0

    def avg_speed(start: int, end: int) -> float:
        vals = [records[i].speed_kph for i in range(start, min(end + 1, len(records)))]
        return np.mean(vals) if vals else 0

    def max_power_range(start: int, end: int) -> float:
        vals = [records[i].power_W for i in range(start, min(end + 1, len(records)))]
        return max(vals) if vals else 0

    def count_zero_power(start: int, end: int) -> int:
        return sum(1 for i in range(start, min(end + 1, len(records)))
                   if records[i].power_W < 10)

    # STEP 1: Find all sharp drop-offs using BOTH power and speed
    drop_off_points: List[int] = []
    for i in range(10, len(records) - 5):
        before_avg_power = avg_power(i - 5, i)
        after_avg_power = avg_power(i + 1, i + 5)
        before_avg_speed = avg_speed(i - 5, i)
        after_avg_speed = avg_speed(i + 1, i + 5)

        power_drop = (before_avg_power >= HIGH_POWER_THRESHOLD and
                      after_avg_power < LOW_POWER_THRESHOLD)
        speed_drop = (before_avg_speed >= HIGH_SPEED_THRESHOLD and
                      after_avg_speed < LOW_SPEED_THRESHOLD)

        if power_drop or speed_drop:
            # Avoid duplicates within 30s
            if (not drop_off_points or
                records[i].elapsed_s - records[drop_off_points[-1]].elapsed_s > 30):
                drop_off_points.append(i)
                if verbose:
                    print(f"  Drop-off at {records[i].elapsed_s:.0f}s: "
                          f"power {'YES' if power_drop else 'no'}, "
                          f"speed {'YES' if speed_drop else 'no'}")

    if verbose:
        print(f"Found {len(drop_off_points)} potential drop-off points")

    # STEP 2: For each drop-off, work backwards to find the full effort
    for end_index in drop_off_points:
        end_time = records[end_index].elapsed_s
        if verbose:
            print(f"Analyzing drop-off at {end_time:.0f}s")

        # Find actual end of high power
        actual_end_index = end_index
        for j in range(end_index, min(len(records), end_index + 15)):
            if records[j].power_W < HIGH_POWER_THRESHOLD:
                actual_end_index = max(end_index, j - 1)
                break

        while (actual_end_index > 0 and
               records[actual_end_index].power_W < HIGH_POWER_THRESHOLD):
            actual_end_index -= 1

        actual_end_time = records[actual_end_index].elapsed_s

        # Find where high-power sprint phase begins
        sprint_start_index = actual_end_index
        for j in range(actual_end_index - 1, max(0, actual_end_index - 60), -1):
            if records[j].power_W < HIGH_POWER_THRESHOLD:
                sprint_start_index = j + 1
                break

        sprint_start_time = records[sprint_start_index].elapsed_s
        sprint_duration = actual_end_time - sprint_start_time

        if verbose:
            print(f"  Sprint: {sprint_start_time:.0f}s to {actual_end_time:.0f}s "
                  f"({sprint_duration:.1f}s)")

        # Validate sprint duration (8-60s)
        if sprint_duration < 8 or sprint_duration > 60:
            if verbose:
                print(f"  REJECTED: sprint {sprint_duration:.1f}s outside 8-60s range")
            continue

        # Find ramp start - TARGET 85-95 seconds total duration
        # Search outward from 90 seconds to find the best ramp start point
        RAMP_MIN_SPEED_KPH = 5
        RAMP_MAX_SPEED_KPH = 35
        TARGET_DURATION = 90  # User feedback: efforts are 80-90 seconds

        effort_start_index = actual_end_index
        found_ramp_start = False

        # Search pattern: 90, 85, 95, 80, 100, 75, 105, 70, 110, 65, 115, 60, 120, 125, 130
        # This prioritizes durations close to 90 seconds
        search_order = []
        for offset in range(0, 41, 5):
            if TARGET_DURATION - offset >= 60:
                search_order.append(TARGET_DURATION - offset)
            if TARGET_DURATION + offset <= 130 and offset > 0:
                search_order.append(TARGET_DURATION + offset)

        for total_len in search_order:
            if found_ramp_start:
                break
            candidate_index = actual_end_index - total_len
            if candidate_index < 0:
                break

            candidate_speed = records[candidate_index].speed_kph
            candidate_power = avg_power(candidate_index, candidate_index + 5)

            if (RAMP_MIN_SPEED_KPH <= candidate_speed <= RAMP_MAX_SPEED_KPH and
                RAMP_POWER_FLOOR <= candidate_power < RAMP_POWER_CEILING):

                # Verify speed is increasing
                mid_point = (candidate_index + sprint_start_index) // 2
                start_speed = avg_speed(candidate_index, candidate_index + 5)
                mid_speed = avg_speed(mid_point, mid_point + 5)
                end_speed = avg_speed(sprint_start_index - 5, sprint_start_index)

                if mid_speed > start_speed and end_speed > mid_speed:
                    effort_start_index = candidate_index
                    found_ramp_start = True
                    if verbose:
                        print(f"  Found ramp start at {records[candidate_index].elapsed_s:.0f}s: "
                              f"{candidate_speed:.1f} km/h, {candidate_power:.0f}W, "
                              f"duration={total_len}s")

        if not found_ramp_start:
            if verbose:
                print(f"  REJECTED: Could not find valid ramp start point")
            continue

        start_time = records[effort_start_index].elapsed_s
        total_duration = actual_end_time - start_time
        ramp_duration = sprint_start_time - start_time

        if verbose:
            print(f"  Total: {total_duration:.1f}s, Ramp: {ramp_duration:.1f}s, "
                  f"Sprint: {sprint_duration:.1f}s")

        # Validate total duration (40-140s)
        if total_duration < 40 or total_duration > 140:
            if verbose:
                print(f"  REJECTED: duration {total_duration:.1f}s outside 40-140s range")
            continue

        # Check for zero-power before start (standing start indicator)
        pre_start_index = max(0, effort_start_index - 15)
        zero_power_before = count_zero_power(pre_start_index, effort_start_index)
        if zero_power_before >= 8:
            if verbose:
                print(f"  REJECTED: {zero_power_before}s of 0W before start")
            continue

        # Check ramp phase has increasing speed
        ramp_start_speed = avg_speed(effort_start_index, effort_start_index + 5)
        ramp_end_speed = avg_speed(sprint_start_index - 5, sprint_start_index)
        speed_increase = ramp_end_speed - ramp_start_speed

        if speed_increase < 2:
            if verbose:
                print(f"  REJECTED: speed increase {speed_increase:.1f} km/h < 2 km/h")
            continue

        # Override: use END - 90s for final effort start (matches mobile logic)
        EFFORT_DURATION_FIRST = 90
        target_start = max(0, actual_end_time - EFFORT_DURATION_FIRST)
        final_start_index = effort_start_index
        for i in range(len(records)):
            if records[i].elapsed_s >= target_start:
                final_start_index = i
                break
        effort_start_index = final_start_index

        start_time = records[effort_start_index].elapsed_s
        total_duration = actual_end_time - start_time
        ramp_duration = sprint_start_time - start_time

        # Calculate stats
        max_power = max_power_range(effort_start_index, actual_end_index)
        total_avg_power = avg_power(effort_start_index, actual_end_index)
        sprint_avg_power = avg_power(sprint_start_index, actual_end_index)
        ramp_avg_power = avg_power(effort_start_index, sprint_start_index - 1)

        # Calculate confidence score
        confidence = 50

        # Good total duration (85-100s ideal)
        if 85 <= total_duration <= 100:
            confidence += 15
        elif 75 <= total_duration <= 110:
            confidence += 10

        # Good sprint duration (25-35s ideal)
        if 25 <= sprint_duration <= 35:
            confidence += 15
        elif 20 <= sprint_duration <= 40:
            confidence += 10

        # High max power
        if max_power >= 1000:
            confidence += 10
        elif max_power >= 800:
            confidence += 5

        # Good power ratio
        power_ratio = sprint_avg_power / (ramp_avg_power or 1)
        if power_ratio >= 3:
            confidence += 10
        elif power_ratio >= 2:
            confidence += 5

        if verbose:
            print(f"ACCEPTED effort: total={total_duration:.1f}s, "
                  f"confidence={min(100, confidence)}%")

        # Check for overlapping efforts
        overlaps = any(abs(e.end_time_s - actual_end_time) < 60 for e in efforts)

        if not overlaps:
            efforts.append(DetectedEffort(
                start_index=effort_start_index,
                end_index=actual_end_index,
                start_time_s=start_time,
                end_time_s=actual_end_time,
                duration_s=total_duration,
                sprint_start_s=sprint_start_time,
                sprint_duration_s=sprint_duration,
                ramp_duration_s=ramp_duration,
                max_power_W=max_power,
                avg_power_W=total_avg_power,
                sprint_avg_power_W=sprint_avg_power,
                confidence=min(100, confidence),
                effort_type=effort_type,
            ))

    # If first pass found efforts, return them
    if efforts:
        efforts.sort(key=lambda e: e.start_time_s)
        if verbose:
            print(f"First pass found {len(efforts)} efforts — returning")
        return efforts[:10]

    # =================================================================
    # SECOND PASS (FALLBACK): Simple END - 90s approach
    # When the ramp-detection algorithm can't find valid ramp starts,
    # fall back to: find dropoff → back up 90s → create effort.
    # =================================================================
    if verbose:
        print("--- SECOND PASS: Fallback (END - 90s) ---")

    EFFORT_DURATION = 90  # All flying efforts are ~90 seconds

    for end_index in drop_off_points:
        if verbose:
            print(f"Fallback analyzing drop-off at {records[end_index].elapsed_s:.0f}s")

        # Find actual end of high power
        actual_end_index = end_index
        for j in range(end_index, min(len(records), end_index + 15)):
            if records[j].power_W < HIGH_POWER_THRESHOLD:
                actual_end_index = max(end_index, j - 1)
                break

        while (actual_end_index > 0 and
               records[actual_end_index].power_W < HIGH_POWER_THRESHOLD):
            actual_end_index -= 1

        actual_end_time = records[actual_end_index].elapsed_s

        # Verify meaningful sprint phase (last 30s before end)
        sprint_check_start = max(0, actual_end_index - 30)
        sprint_check_end = max(0, actual_end_index - 5)
        sprint_avg = avg_power(sprint_check_start, sprint_check_end)

        if sprint_avg < HIGH_POWER_THRESHOLD * 0.5:
            if verbose:
                print(f"  REJECTED: sprint avg {sprint_avg:.0f}W too low")
            continue

        # Calculate START = END - 90 seconds
        target_start_time = max(0, actual_end_time - EFFORT_DURATION)
        effort_start_index = 0
        for i in range(len(records)):
            if records[i].elapsed_s >= target_start_time:
                effort_start_index = i
                break

        start_time = records[effort_start_index].elapsed_s
        total_duration = actual_end_time - start_time

        # Check for standing start indicator
        pre_start_index = max(0, effort_start_index - 15)
        zero_power_before = count_zero_power(pre_start_index, effort_start_index)
        if zero_power_before >= 8:
            if verbose:
                print(f"  REJECTED: {zero_power_before}s of 0W before start")
            continue

        max_power = max_power_range(effort_start_index, actual_end_index)
        total_avg_power = avg_power(effort_start_index, actual_end_index)

        confidence = 50
        if max_power >= 1000:
            confidence += 15
        elif max_power >= 800:
            confidence += 10

        if verbose:
            print(f"ACCEPTED (fallback): {start_time:.0f}s to {actual_end_time:.0f}s "
                  f"({total_duration:.1f}s), confidence={confidence}%")

        # Estimate sprint boundary
        sprint_start_index = actual_end_index
        for j in range(actual_end_index - 1, max(0, actual_end_index - 60), -1):
            if records[j].power_W < HIGH_POWER_THRESHOLD:
                sprint_start_index = j + 1
                break
        sprint_start_index = max(effort_start_index, sprint_start_index)
        sprint_start_time = records[sprint_start_index].elapsed_s
        sprint_duration = actual_end_time - sprint_start_time
        ramp_duration = sprint_start_time - start_time
        sprint_avg_power = avg_power(sprint_start_index, actual_end_index)

        overlaps = any(abs(e.end_time_s - actual_end_time) < 60 for e in efforts)
        if not overlaps:
            efforts.append(DetectedEffort(
                start_index=effort_start_index,
                end_index=actual_end_index,
                start_time_s=start_time,
                end_time_s=actual_end_time,
                duration_s=total_duration,
                sprint_start_s=sprint_start_time,
                sprint_duration_s=sprint_duration,
                ramp_duration_s=ramp_duration,
                max_power_W=max_power,
                avg_power_W=total_avg_power,
                sprint_avg_power_W=sprint_avg_power,
                confidence=min(100, confidence),
                effort_type=effort_type,
            ))

    efforts.sort(key=lambda e: e.start_time_s)
    return efforts[:10]


def create_manual_effort(
    records: List[FitRecord],
    final_row: int,
    effort_type: int = 200,
    lookback_s: float = 90.0,
    verbose: bool = False,
) -> Optional[DetectedEffort]:
    """
    Create a Flying 200 effort manually from a user-specified final row.

    When auto-detect fails to find the real effort (e.g., unusual power
    profile), the user picks the row where the effort ends and this
    function backs out `lookback_s` seconds to define the interval.

    Within that window the sprint / ramp boundary is estimated so the
    rest of the pipeline (distance conversion, simulation) works unchanged.

    Args:
        records: Full list of FIT records.
        final_row: Index of the last row of the effort (end / finish line).
        effort_type: Effort type label (200, 150, 100, 50).
        lookback_s: Seconds to back out from final_row (default 90).
        verbose: Print debug info.

    Returns:
        A DetectedEffort, or None if the window is too short.
    """
    if final_row < 0 or final_row >= len(records):
        if verbose:
            print(f"Manual effort: final_row {final_row} out of range (0-{len(records)-1})")
        return None

    end_time = records[final_row].elapsed_s
    target_start_time = end_time - lookback_s

    # Find the start index closest to target_start_time
    start_index = final_row
    for i in range(final_row, -1, -1):
        if records[i].elapsed_s <= target_start_time:
            start_index = i
            break
    else:
        start_index = 0  # file is shorter than lookback

    start_time = records[start_index].elapsed_s
    total_duration = end_time - start_time

    if total_duration < 10:
        if verbose:
            print(f"Manual effort: duration {total_duration:.1f}s too short")
        return None

    if verbose:
        print(f"Manual effort: rows {start_index}-{final_row}, "
              f"{start_time:.1f}s - {end_time:.1f}s ({total_duration:.1f}s)")

    # --- Estimate sprint start within the window ---
    # Use the same dynamic thresholds as auto-detect
    file_max_power = max(r.power_W for r in records)
    HIGH_POWER_THRESHOLD = min(file_max_power * 0.30, 500)

    # Walk backwards from the end to find the start of the high-power phase
    sprint_start_index = final_row
    for j in range(final_row, start_index, -1):
        if records[j].power_W < HIGH_POWER_THRESHOLD:
            sprint_start_index = j + 1
            break
    else:
        # Entire window is above threshold – put sprint start at midpoint
        sprint_start_index = (start_index + final_row) // 2

    # Clamp
    sprint_start_index = max(start_index, min(sprint_start_index, final_row))
    sprint_start_time = records[sprint_start_index].elapsed_s
    sprint_duration = end_time - sprint_start_time
    ramp_duration = sprint_start_time - start_time

    # --- Calculate stats ---
    effort_powers = [records[i].power_W for i in range(start_index, final_row + 1)]
    sprint_powers = [records[i].power_W for i in range(sprint_start_index, final_row + 1)]

    max_power = max(effort_powers) if effort_powers else 0
    avg_power = float(np.mean(effort_powers)) if effort_powers else 0
    sprint_avg_power = float(np.mean(sprint_powers)) if sprint_powers else 0

    if verbose:
        print(f"  Sprint: {sprint_start_time:.1f}s - {end_time:.1f}s "
              f"({sprint_duration:.1f}s), ramp: {ramp_duration:.1f}s")
        print(f"  Max power: {max_power:.0f}W, sprint avg: {sprint_avg_power:.0f}W")

    return DetectedEffort(
        start_index=start_index,
        end_index=final_row,
        start_time_s=start_time,
        end_time_s=end_time,
        duration_s=total_duration,
        sprint_start_s=sprint_start_time,
        sprint_duration_s=sprint_duration,
        ramp_duration_s=ramp_duration,
        max_power_W=max_power,
        avg_power_W=avg_power,
        sprint_avg_power_W=sprint_avg_power,
        confidence=0,  # 0 = manual override (not auto-scored)
        effort_type=effort_type,
    )


def quick_sim_preview(
    records: List[FitRecord],
    effort: DetectedEffort,
) -> dict:
    """
    Quick simulation preview for a detected effort.

    Provides a rough estimate of 200m time without full simulation.

    Args:
        records: List of FIT records
        effort: Detected effort to preview

    Returns:
        Dict with preview metrics
    """
    # Extract records for this effort
    effort_records = records[effort.start_index:effort.end_index + 1]

    if not effort_records:
        return {"error": "No records for effort"}

    # Calculate basic stats
    speeds = [r.speed_kph for r in effort_records]
    powers = [r.power_W for r in effort_records]

    max_speed = max(speeds) if speeds else 0
    avg_speed = np.mean(speeds) if speeds else 0
    max_power = max(powers) if powers else 0
    avg_power = np.mean(powers) if powers else 0

    # Find sprint start index by searching for the time
    sprint_start_index = effort.start_index
    for i in range(effort.start_index, effort.end_index + 1):
        if records[i].elapsed_s >= effort.sprint_start_s:
            sprint_start_index = i
            break

    # Extract sprint phase records using indices
    sprint_records = records[sprint_start_index:effort.end_index + 1]
    sprint_speeds = [r.speed_kph for r in sprint_records if r.speed_kph > 0]
    sprint_avg_speed = np.mean(sprint_speeds) if sprint_speeds else avg_speed

    # Convert km/h to m/s, estimate 200m time
    sprint_speed_mps = sprint_avg_speed / 3.6
    estimated_200m_time = 200 / sprint_speed_mps if sprint_speed_mps > 0 else 0

    return {
        "duration_s": effort.duration_s,
        "max_speed_kph": max_speed,
        "avg_speed_kph": avg_speed,
        "max_power_W": max_power,
        "avg_power_W": avg_power,
        "sprint_avg_speed_kph": sprint_avg_speed,
        "estimated_200m_time_s": estimated_200m_time,
        "confidence": effort.confidence,
    }


# =============================================================================
# Peak Finder Fallback
# =============================================================================

def find_power_peaks(
    records: List[FitRecord],
    min_power_W: float = 300,
    verbose: bool = False,
) -> List[DetectedEffort]:
    """
    Find power peaks as a fallback when auto-detect finds nothing.

    Logic: Find power dropoffs (high→low transitions) → back up 90s → create effort.
    Simpler than detect_flying_efforts — no ramp validation, no speed checks.
    Results are sorted by max power (highest first).

    Args:
        records: List of FIT records
        min_power_W: Minimum power to count as "high" (default 300W)
        verbose: Print debug output

    Returns:
        List of detected efforts sorted by max power (highest first)
    """
    if len(records) < 50:
        return []

    EFFORT_DURATION = 90  # All flying efforts are ~90 seconds
    efforts: List[DetectedEffort] = []

    # File stats for adaptive thresholds
    file_max_power = max(r.power_W for r in records)
    high_threshold = max(min_power_W, file_max_power * 0.30)
    low_threshold = max(min_power_W * 0.5, file_max_power * 0.15)

    if verbose:
        print(f"Peak finder: fileMax={file_max_power:.0f}W, "
              f"highThreshold={high_threshold:.0f}W, lowThreshold={low_threshold:.0f}W")

    def avg_power(start: int, end: int) -> float:
        vals = [records[i].power_W for i in range(start, min(end + 1, len(records)))]
        return np.mean(vals) if vals else 0

    def max_power_range(start: int, end: int) -> float:
        vals = [records[i].power_W for i in range(start, min(end + 1, len(records)))]
        return max(vals) if vals else 0

    # Find all sharp dropoffs (high power → low power)
    drop_off_points: List[int] = []
    for i in range(10, len(records) - 5):
        before_avg = avg_power(i - 5, i)
        after_avg = avg_power(i + 1, i + 5)

        if before_avg >= high_threshold and after_avg < low_threshold:
            # Avoid duplicates within 60s
            if (not drop_off_points or
                records[i].elapsed_s - records[drop_off_points[-1]].elapsed_s > 60):
                drop_off_points.append(i)
                if verbose:
                    print(f"  Dropoff at {records[i].elapsed_s:.0f}s: "
                          f"{before_avg:.0f}W → {after_avg:.0f}W")

    if verbose:
        print(f"Peak finder: found {len(drop_off_points)} dropoff points")

    # For each dropoff, create a 90-second effort ending at that point
    for drop_off_index in drop_off_points:
        end_time = records[drop_off_index].elapsed_s
        end_index = drop_off_index

        # Calculate START = END - 90 seconds
        target_start_time = max(0, end_time - EFFORT_DURATION)

        # Find the index closest to target start time
        start_index = 0
        for i in range(len(records)):
            if records[i].elapsed_s >= target_start_time:
                start_index = i
                break

        start_time = records[start_index].elapsed_s
        duration = end_time - start_time

        # Calculate stats
        max_power = max_power_range(start_index, end_index)
        total_avg_power = avg_power(start_index, end_index)

        # Estimate sprint boundary
        sprint_start_index = end_index
        sprint_threshold = max(min_power_W, file_max_power * 0.30)
        for j in range(end_index - 1, max(0, end_index - 60), -1):
            if records[j].power_W < sprint_threshold:
                sprint_start_index = j + 1
                break
        sprint_start_index = max(start_index, sprint_start_index)
        sprint_start_time = records[sprint_start_index].elapsed_s
        sprint_duration = end_time - sprint_start_time
        ramp_duration = sprint_start_time - start_time
        sprint_avg_power = avg_power(sprint_start_index, end_index)

        efforts.append(DetectedEffort(
            start_index=start_index,
            end_index=end_index,
            start_time_s=start_time,
            end_time_s=end_time,
            duration_s=duration,
            sprint_start_s=sprint_start_time,
            sprint_duration_s=sprint_duration,
            ramp_duration_s=ramp_duration,
            max_power_W=max_power,
            avg_power_W=total_avg_power,
            sprint_avg_power_W=sprint_avg_power,
            confidence=40,  # Medium-low confidence — peak finder results
            effort_type=200,
        ))

        if verbose:
            print(f"  Effort: {start_time:.0f}s to {end_time:.0f}s "
                  f"({duration:.1f}s), maxPower={max_power:.0f}W")

    # Sort by max power (highest first)
    efforts.sort(key=lambda e: e.max_power_W, reverse=True)

    return efforts[:15]
