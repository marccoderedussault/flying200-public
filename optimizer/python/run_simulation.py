#!/usr/bin/env python3
"""
Python bridge script for running Flying 200m simulations.
Wraps flying200_model.simulate_profile() for Node.js communication.
"""
import sys
import json
import os
import numpy as np
import math

# Import the model module
import flying200_model as model

# Default values (matching flying200_gui.py)
DEFAULTS = {
    # Rider parameters
    "mass_kg": 92.0,
    "rho": 1.1627,           # Air density at velodrome
    "crr": 0.0020,           # Rolling resistance
    "v0_mps": 5.0,           # Initial velocity
    "drivetrain_eff": 0.98,  # 2% drivetrain loss

    # Power parameters
    "cp_W": 250.0,           # Critical Power
    "wPrime_J": 25000.0,     # W' capacity
    "sprint_delta_W": 250.0, # Sprint power increase

    # CdA parameters
    "cda_standing": 0.26,    # Standing CdA
    "cda_seated": 0.21,      # Seated CdA
    "cda_bend_factor": 1.00, # Bend CdA multiplier

    # Track parameters
    "s_total_m": 895.0,      # Total distance
    "ds_m": 0.25,            # Grid spacing
    "trans_len_m": 40.0,     # Transition length

    # Track geometry (Bromont defaults)
    "track_straight_m": 59.0,
    "track_banking_turn_deg": 42.0,
    "track_banking_straight_deg": 12.0,
    "track_lap_m": 250.0,
}


def safe_float(val, default=0.0):
    """Safely convert value to float, handling None, empty strings, and NaN."""
    if val is None or val == '':
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def apply_track_geometry_from_params(parameters):
    """Apply track geometry from request parameters, defaulting to Bromont."""
    track_geom = parameters.get("track_geometry")
    if track_geom and isinstance(track_geom, dict):
        model.apply_track_geometry(
            straight_m=safe_float(track_geom.get("straight_m"), DEFAULTS["track_straight_m"]),
            banking_turn_deg=safe_float(track_geom.get("banking_turn_deg"), DEFAULTS["track_banking_turn_deg"]),
            banking_straight_deg=safe_float(track_geom.get("banking_straight_deg"), DEFAULTS["track_banking_straight_deg"]),
            lap_m=safe_float(track_geom.get("lap_m"), DEFAULTS["track_lap_m"]),
            s_total_m=safe_float(track_geom.get("s_total_m"), None) if track_geom.get("s_total_m") else None,
        )
    else:
        # Reset to Bromont defaults
        model.apply_track_geometry(
            DEFAULTS["track_straight_m"],
            DEFAULTS["track_banking_turn_deg"],
            DEFAULTS["track_banking_straight_deg"],
            DEFAULTS["track_lap_m"],
        )


def compute_200m_segments(result, CdA_grid, P_grid, parameters):
    """
    Compute detailed 10m segment data for the 200m timed section.
    Returns array of segment data matching Python GUI format.
    """
    S_TOTAL = model.S_TOTAL
    S_200_START = S_TOTAL - 200.0  # 695m

    s_grid = model.s_grid
    v_array = result.get("v", np.array([0]))
    t_array = result.get("t", np.array([0]))
    section_arr = model.section_arr

    segments = []

    for i in range(20):  # 20 x 10m segments
        s_start = S_200_START + i * 10.0
        s_end = s_start + 10.0

        # Get indices for this segment
        mask = (s_grid >= s_start) & (s_grid <= s_end)
        if not mask.any():
            continue

        # Get values at segment boundaries
        idx_start = np.searchsorted(s_grid, s_start)
        idx_end = np.searchsorted(s_grid, s_end)
        idx_start = max(0, min(idx_start, len(s_grid) - 1))
        idx_end = max(0, min(idx_end, len(s_grid) - 1))

        v_start = float(v_array[idx_start])
        v_end = float(v_array[idx_end])
        t_start = float(t_array[idx_start])
        t_end = float(t_array[idx_end])

        segment_time = t_end - t_start
        v_avg = (v_start + v_end) / 2.0

        # Get section name at midpoint
        mid_idx = (idx_start + idx_end) // 2
        section = str(section_arr[mid_idx]) if mid_idx < len(section_arr) else "Unknown"

        # Get average CdA and Power for segment
        cda_segment = CdA_grid[mask]
        p_segment = P_grid[mask]
        cda_avg = float(np.mean(cda_segment)) if len(cda_segment) > 0 else 0.21
        p_avg = float(np.mean(p_segment)) if len(p_segment) > 0 else 0

        segments.append({
            "segment": f"{int(s_start)}-{int(s_end)}m",
            "s_start": float(s_start),
            "s_end": float(s_end),
            "section": section,
            "v_start_kph": v_start * 3.6,
            "v_end_kph": v_end * 3.6,
            "v_avg_kph": v_avg * 3.6,
            "t_start": t_start,
            "t_end": t_end,
            "delta_t": segment_time,
            "cda_avg": cda_avg,
            "p_avg": p_avg,
            "segment_distance": 10.0,
        })

    return segments


def compute_section_stats(base_result, mod_result):
    """Compute per-section statistics for the bar chart."""
    import pandas as pd

    s_grid = model.s_grid
    section_arr = model.section_arr
    lap_idx_arr = model.lap_idx_arr

    # Build DataFrames for base and mod
    base_df = pd.DataFrame({
        "s": s_grid,
        "v": base_result["v"],
        "section": section_arr,
        "lap_idx": lap_idx_arr,
    })
    mod_df = pd.DataFrame({
        "s": s_grid,
        "v": mod_result["v"],
        "section": section_arr,
        "lap_idx": lap_idx_arr,
    })

    # Aggregate by lap and section
    base_agg = base_df.groupby(["lap_idx", "section"]).agg(
        v_mean_mps=("v", "mean")
    ).reset_index()
    mod_agg = mod_df.groupby(["lap_idx", "section"]).agg(
        v_mean_mps=("v", "mean")
    ).reset_index()

    # Merge
    merged = base_agg.merge(mod_agg, on=["lap_idx", "section"], suffixes=("_base", "_mod"))

    # Get ordered sections by first appearance
    seen = set()
    ordered_sections = []
    for lap, sec in zip(lap_idx_arr, section_arr):
        key = (int(lap), sec)
        if key not in seen:
            seen.add(key)
            ordered_sections.append(key)

    # Build output in order
    section_stats = []
    for lap, sec in ordered_sections:
        row = merged[(merged["lap_idx"] == lap) & (merged["section"] == sec)]
        if not row.empty:
            row = row.iloc[0]
            v_base = row["v_mean_mps_base"] * 3.6  # Convert to km/h
            v_mod = row["v_mean_mps_mod"] * 3.6
            v_diff = v_mod - v_base
            section_stats.append({
                "label": f"L{int(lap)}-{sec}",
                "lap_idx": int(lap),
                "section": sec,
                "v_base_kph": float(v_base),
                "v_mod_kph": float(v_mod),
                "v_diff_kph": float(v_diff)
            })

    return section_stats


# Track segment definitions (must match mobile app's TRACK_SEGMENTS)
TRACK_SEGMENTS = [
    # Lap 0 - Initial approach (partial lap)
    {"id": "lap0_back_2", "startM": 0, "endM": 24, "locked": False},
    {"id": "lap0_turn3", "startM": 25, "endM": 59, "locked": False},
    {"id": "lap0_turn4", "startM": 60, "endM": 94, "locked": False},
    {"id": "lap0_home_1", "startM": 95, "endM": 124, "locked": False},
    # Lap 1 - Full lap
    {"id": "lap1_home_2", "startM": 125, "endM": 154, "locked": False},
    {"id": "lap1_turn1", "startM": 155, "endM": 189, "locked": False},
    {"id": "lap1_turn2", "startM": 190, "endM": 224, "locked": False},
    {"id": "lap1_back_1", "startM": 225, "endM": 254, "locked": False},
    {"id": "lap1_back_2", "startM": 255, "endM": 284, "locked": False},
    {"id": "lap1_turn3", "startM": 285, "endM": 319, "locked": False},
    {"id": "lap1_turn4", "startM": 320, "endM": 354, "locked": False},
    # Lap 2 - Extended lap (extra long into start line)
    {"id": "lap2_home_1", "startM": 355, "endM": 384, "locked": False},
    {"id": "lap2_home_2", "startM": 385, "endM": 414, "locked": False},
    {"id": "lap2_turn1", "startM": 415, "endM": 449, "locked": False},
    {"id": "lap2_turn2", "startM": 450, "endM": 484, "locked": False},
    {"id": "lap2_back_1", "startM": 485, "endM": 514, "locked": False},
    {"id": "lap2_back_2", "startM": 515, "endM": 544, "locked": False},
    {"id": "lap2_turn3", "startM": 545, "endM": 579, "locked": False},
    {"id": "lap2_turn4", "startM": 580, "endM": 614, "locked": False},
    {"id": "lap2_home2_1", "startM": 615, "endM": 644, "locked": False},
    {"id": "lap2_home2_2", "startM": 645, "endM": 674, "locked": False},
    {"id": "lap2_turn1_2", "startM": 675, "endM": 694, "locked": False},
    # Lap 3 - Timed 200m section (LOCKED as seated)
    {"id": "lap3_timed", "startM": 695, "endM": 895, "locked": True},
]


def get_segment_for_distance(distance_m):
    """Find which segment a distance falls into."""
    for segment in TRACK_SEGMENTS:
        if segment["startM"] <= distance_m <= segment["endM"]:
            return segment
    return None


def apply_cda_bend_factor(CdA_grid, s_grid, cda_bend_factor):
    """
    Apply CdA bend factor to reduce drag in bends.

    Factor < 1.0 means CdA is LOWER in bends (due to yaw angle reducing frontal area).
    Example: factor=0.97 means bend CdA is 97% of straight CdA.

    Args:
        CdA_grid: Array of CdA values
        s_grid: Array of distances along track
        cda_bend_factor: Factor to multiply CdA by in bends (0.95-1.0)

    Returns:
        Modified CdA_grid with reduced CdA in bends
    """
    if cda_bend_factor >= 1.0 or cda_bend_factor <= 0:
        return CdA_grid  # No modification needed

    modified_CdA = CdA_grid.copy()
    for i, s in enumerate(s_grid):
        if model.in_bend_region(float(s)):
            modified_CdA[i] = CdA_grid[i] * cda_bend_factor

    return modified_CdA


def build_cda_grid_with_positions(s_grid, segment_positions, cda_seated, cda_standing):
    """
    Build a CdA grid where each point uses seated or standing CdA based on segment positions.

    Args:
        s_grid: Distance grid (numpy array)
        segment_positions: Dict mapping segment_id -> "seated" or "standing"
        cda_seated: CdA value for seated segments
        cda_standing: CdA value for standing segments

    Returns:
        CdA grid (numpy array) with appropriate values for each distance
    """
    CdA_grid = np.full_like(s_grid, cda_seated)  # Default to seated

    for i, s in enumerate(s_grid):
        segment = get_segment_for_distance(float(s))
        if segment is None:
            continue

        # Locked segments (timed 200m) are always seated
        if segment.get("locked", False):
            CdA_grid[i] = cda_seated
        else:
            position = segment_positions.get(segment["id"], "seated")
            CdA_grid[i] = cda_standing if position == "standing" else cda_seated

    return CdA_grid


def compute_dual_breakeven_cda(profile_data, parameters, target_entry_speed_kph, target_timed_section_s,
                                segment_positions, effort_type=200, max_iterations=50):
    """
    Compute BOTH seated and standing breakeven CdA values using sequential solve.

    This requires BOTH targets:
    1. Use timed section time to solve for seated CdA (timed section is always seated)
    2. Use entry speed with known seated CdA to solve for standing CdA

    Args:
        profile_data: Profile rows with s_m, y_m, CdA_m2, P_W
        parameters: Simulation parameters
        target_entry_speed_kph: Target entry speed at 695m (required)
        target_timed_section_s: Target time for timed section (required)
        segment_positions: Dict mapping segment_id -> "seated" or "standing"
        effort_type: 50, 100, 150, or 200 (meters)
        max_iterations: Maximum binary search iterations

    Returns:
        dict with solved_cda_seated, solved_cda_standing, and convergence info
    """
    try:
        if target_entry_speed_kph is None or target_timed_section_s is None:
            return {
                "success": False,
                "error": "Dual breakeven requires both entry speed AND timed section targets"
            }

        if not segment_positions:
            segment_positions = {}  # Default all to seated

        rows = profile_data.get("rows", profile_data)
        if not rows or len(rows) == 0:
            return {"success": False, "error": "No profile data"}

        # Apply track geometry
        apply_track_geometry_from_params(parameters)

        # Setup model parameters
        model.MASS = safe_float(parameters.get("mass_kg"), DEFAULTS["mass_kg"])
        model.RHO = safe_float(parameters.get("rho"), DEFAULTS["rho"])
        model.C_RR = safe_float(parameters.get("crr"), DEFAULTS["crr"])
        model.CP = safe_float(parameters.get("cp_W"), DEFAULTS["cp_W"])
        model.W_PRIME_TOTAL = safe_float(parameters.get("wPrime_J"), DEFAULTS["wPrime_J"])
        model.V0 = safe_float(parameters.get("v0_mps"), DEFAULTS["v0_mps"])
        model.DRIVETRAIN_EFF = safe_float(parameters.get("drivetrain_eff"), DEFAULTS["drivetrain_eff"])

        # CdA bend factor (reduces CdA in bends when < 1.0)
        cda_bend_factor = safe_float(parameters.get("cda_bend_factor"), DEFAULTS["cda_bend_factor"])

        # Extract profile data
        s_input = np.array([safe_float(r.get("s_m"), 0) for r in rows])
        y_input = np.array([safe_float(r.get("y_m"), 3.5) for r in rows])
        P_input = np.array([safe_float(r.get("P_W"), 0) for r in rows])

        target_s_grid = model.s_grid
        y_grid = np.interp(target_s_grid, s_input, y_input)
        P_grid = np.interp(target_s_grid, s_input, P_input)

        # Calculate number of splits based on effort type
        num_splits = effort_type // 50  # F200=4, F150=3, F100=2, F50=1

        results = {
            "success": True,
            "solved_cda_seated": None,
            "solved_cda_standing": None,
            "seated_converged": False,
            "standing_converged": False,
        }

        # Check if there are any standing segments
        has_standing_segments = any(
            segment_positions.get(seg["id"]) == "standing"
            for seg in TRACK_SEGMENTS
            if not seg.get("locked", False)
        )

        if has_standing_segments:
            # ========== NESTED BINARY SEARCH: standing (outer) + seated (inner) ==========
            #
            # The problem has 2 unknowns (seated CdA, standing CdA) and 2 targets
            # (entry speed, timed section time).  The key insight is that for any
            # given standing CdA, there is a unique seated CdA that matches the
            # timed time — so we can reduce the 2-D problem to a 1-D search:
            #
            #   outer: binary search on standing CdA using entry speed residual
            #   inner: for each standing CdA candidate, binary search on seated CdA
            #          to match the timed section time
            #
            # This avoids the Gauss-Seidel oscillation that plagued the previous
            # alternating-solve approach.

            results["mode"] = "seated_vs_standing"

            CDA_LO = 0.15
            CDA_HI_SEATED = 0.40
            CDA_HI_STANDING = 0.60

            time_tolerance = 0.00005    # seconds — inner convergence
            speed_tolerance = 0.001     # kph — outer convergence
            max_inner = max_iterations  # iterations for seated binary search
            max_outer = max_iterations  # iterations for standing binary search

            def simulate_pair(cda_seated, cda_standing):
                """Run simulation and return (entry_speed_kph, timed_time_s)."""
                CdA_grid = build_cda_grid_with_positions(
                    target_s_grid, segment_positions,
                    cda_seated, cda_standing
                )
                CdA_grid = apply_cda_bend_factor(CdA_grid, target_s_grid, cda_bend_factor)
                result = model.simulate_profile(
                    y_grid=y_grid, CdA_grid=CdA_grid, P_grid=P_grid, label="test"
                )
                entry_kph = float(result.get("v_200_entry", 0)) * 3.6
                splits = result.get("splits_200", [0, 0, 0, 0])
                timed_s = float(sum(splits[:num_splits]))
                return entry_kph, timed_s

            def solve_seated_for_standing(cda_standing):
                """Inner binary search: find seated CdA that matches timed time,
                given a fixed standing CdA.  Returns (seated_cda, converged)."""
                lo, hi = CDA_LO, CDA_HI_SEATED

                _, time_lo = simulate_pair(lo, cda_standing)
                _, time_hi = simulate_pair(hi, cda_standing)

                # Bracket check
                if target_timed_section_s < time_lo:
                    return lo, False   # Target faster than achievable
                if target_timed_section_s > time_hi:
                    return hi, False   # Target slower than achievable

                for _ in range(max_inner):
                    mid = (lo + hi) / 2.0
                    _, timed = simulate_pair(mid, cda_standing)
                    if abs(timed - target_timed_section_s) < time_tolerance:
                        return mid, True
                    if timed > target_timed_section_s:
                        hi = mid   # Too slow — reduce CdA
                    else:
                        lo = mid   # Too fast — increase CdA
                return (lo + hi) / 2.0, True  # Close enough after max iterations

            # ---------- Outer binary search on standing CdA ----------
            st_lo, st_hi = CDA_LO, CDA_HI_STANDING

            # Evaluate endpoints to check bracket and collect debug info
            seated_at_lo, _ = solve_seated_for_standing(st_lo)
            speed_at_lo, _ = simulate_pair(seated_at_lo, st_lo)
            seated_at_hi, _ = solve_seated_for_standing(st_hi)
            speed_at_hi, _ = simulate_pair(seated_at_hi, st_hi)

            results["debug_entry_speed_at_lo"] = float(round(speed_at_lo, 2))
            results["debug_entry_speed_at_hi"] = float(round(speed_at_hi, 2))

            # Higher standing CdA → more drag → lower entry speed.
            # speed_at_lo should be the fastest, speed_at_hi the slowest.
            if target_entry_speed_kph > speed_at_lo:
                # Target faster than achievable even with minimum standing CdA
                results["standing_note"] = "Target faster than achievable"
                solved_standing_cda = st_lo
                solved_seated_cda = seated_at_lo
            elif target_entry_speed_kph < speed_at_hi:
                # Target slower than achievable even with maximum standing CdA
                results["standing_note"] = "Target slower than achievable"
                solved_standing_cda = st_hi
                solved_seated_cda = seated_at_hi
            else:
                solved_standing_cda = None
                solved_seated_cda = None

                for outer_iter in range(max_outer):
                    st_mid = (st_lo + st_hi) / 2.0

                    # Inner: solve seated CdA for this standing candidate
                    seated_mid, seated_ok = solve_seated_for_standing(st_mid)

                    # Evaluate entry speed with the solved pair
                    entry_speed, achieved_time = simulate_pair(seated_mid, st_mid)

                    if abs(entry_speed - target_entry_speed_kph) < speed_tolerance:
                        solved_standing_cda = st_mid
                        solved_seated_cda = seated_mid
                        results["standing_converged"] = True
                        results["seated_converged"] = seated_ok
                        results["standing_iterations"] = outer_iter + 1
                        results["standing_achieved_kph"] = float(round(entry_speed, 2))
                        results["seated_achieved_s"] = float(round(achieved_time, 4))
                        break

                    if entry_speed > target_entry_speed_kph:
                        st_lo = st_mid   # Too fast — need more standing drag
                    else:
                        st_hi = st_mid   # Too slow — need less standing drag
                else:
                    # Didn't converge within tolerance; use best midpoint
                    st_mid = (st_lo + st_hi) / 2.0
                    seated_mid, seated_ok = solve_seated_for_standing(st_mid)
                    entry_speed, achieved_time = simulate_pair(seated_mid, st_mid)
                    solved_standing_cda = st_mid
                    solved_seated_cda = seated_mid
                    results["standing_converged"] = False
                    results["seated_converged"] = seated_ok
                    results["standing_iterations"] = max_outer
                    results["standing_achieved_kph"] = float(round(entry_speed, 2))
                    results["seated_achieved_s"] = float(round(achieved_time, 4))
                    results["outer_note"] = "Outer loop did not fully converge"

            if solved_standing_cda is None or solved_seated_cda is None:
                return {"success": False, "error": "Failed to find CdA values"}

            # Sanity check: physically, standing CdA should be >= seated CdA.
            if solved_standing_cda < solved_seated_cda:
                results["standing_note"] = (
                    f"Warning: solved standing CdA ({solved_standing_cda:.4f}) < "
                    f"seated CdA ({solved_seated_cda:.4f}); targets may be inconsistent"
                )

            results["solved_cda_seated"] = float(round(solved_seated_cda, 4))
            results["solved_cda_standing"] = float(round(solved_standing_cda, 4))

        else:
            # ========== ALL SEATED: uniform step 1 + buildup vs timed split ==========

            def run_with_uniform_cda(cda_value):
                """Run simulation with uniform CdA (for finding seated CdA)."""
                CdA_grid = np.full_like(target_s_grid, cda_value)
                CdA_grid = apply_cda_bend_factor(CdA_grid, target_s_grid, cda_bend_factor)
                result = model.simulate_profile(
                    y_grid=y_grid, CdA_grid=CdA_grid, P_grid=P_grid, label="test"
                )
                entry_speed_kph = float(result.get("v_200_entry", 0)) * 3.6
                splits = result.get("splits_200", [0, 0, 0, 0])
                timed_section_s = float(sum(splits[:num_splits]))
                return entry_speed_kph, timed_section_s

            # Binary search for seated CdA using timed section
            lo, hi = 0.15, 0.60
            _, time_at_lo = run_with_uniform_cda(lo)
            _, time_at_hi = run_with_uniform_cda(hi)

            results["debug_time_at_lo"] = float(round(time_at_lo, 4))
            results["debug_time_at_hi"] = float(round(time_at_hi, 4))

            solved_seated_cda = None

            if target_timed_section_s < time_at_lo:
                results["seated_note"] = "Target faster than achievable"
                solved_seated_cda = lo
            elif target_timed_section_s > time_at_hi:
                results["seated_note"] = "Target slower than achievable"
                solved_seated_cda = hi
            else:
                for iteration in range(max_iterations):
                    mid = (lo + hi) / 2
                    _, timed_section = run_with_uniform_cda(mid)

                    if abs(timed_section - target_timed_section_s) < 0.001:
                        solved_seated_cda = mid
                        results["seated_converged"] = True
                        results["seated_iterations"] = iteration + 1
                        results["seated_achieved_s"] = float(round(timed_section, 4))
                        break

                    if timed_section > target_timed_section_s:
                        hi = mid  # Need lower CdA to go faster
                    else:
                        lo = mid  # Need higher CdA to go slower
                else:
                    solved_seated_cda = (lo + hi) / 2

            if solved_seated_cda is None:
                return {"success": False, "error": "Failed to find seated CdA"}

            results["solved_cda_seated"] = float(round(solved_seated_cda, 4))

            # No standing segments - solve for buildup CdA (windup 0-695m) vs timed CdA (695-895m)
            def run_with_split_cda(cda_buildup):
                """Run simulation with different CdA for buildup (0-695m) vs timed (695m+)."""
                CdA_grid = np.full_like(target_s_grid, solved_seated_cda)  # Timed section CdA
                buildup_mask = target_s_grid < 695.0
                CdA_grid[buildup_mask] = cda_buildup
                CdA_grid = apply_cda_bend_factor(CdA_grid, target_s_grid, cda_bend_factor)
                result = model.simulate_profile(
                    y_grid=y_grid, CdA_grid=CdA_grid, P_grid=P_grid, label="test"
                )
                entry_speed_kph = float(result.get("v_200_entry", 0)) * 3.6
                return entry_speed_kph

            # Binary search for buildup CdA
            lo, hi = 0.15, 0.60
            speed_at_lo = run_with_split_cda(lo)
            speed_at_hi = run_with_split_cda(hi)

            results["debug_entry_speed_at_lo"] = float(round(speed_at_lo, 2))
            results["debug_entry_speed_at_hi"] = float(round(speed_at_hi, 2))
            results["mode"] = "buildup_vs_timed"  # Indicate this is buildup/timed split, not seated/standing

            if target_entry_speed_kph > speed_at_lo:
                results["standing_note"] = "Target faster than achievable"
                results["solved_cda_standing"] = float(round(lo, 4))  # Using "standing" field for buildup CdA
            elif target_entry_speed_kph < speed_at_hi:
                results["standing_note"] = "Target slower than achievable"
                results["solved_cda_standing"] = float(round(hi, 4))
            else:
                for iteration in range(max_iterations):
                    mid = (lo + hi) / 2
                    entry_speed = run_with_split_cda(mid)

                    if abs(entry_speed - target_entry_speed_kph) < 0.1:
                        results["solved_cda_standing"] = float(round(mid, 4))
                        results["standing_converged"] = True
                        results["standing_iterations"] = iteration + 1
                        results["standing_achieved_kph"] = float(round(entry_speed, 2))
                        break

                    if entry_speed > target_entry_speed_kph:
                        lo = mid  # Need higher CdA to slow down
                    else:
                        hi = mid  # Need lower CdA to speed up
                else:
                    results["solved_cda_standing"] = float(round((lo + hi) / 2, 4))

            # Relabel for clarity when no standing segments
            results["solved_cda_buildup"] = results["solved_cda_standing"]
            results["solved_cda_timed"] = results["solved_cda_seated"]

        return results

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def compute_breakeven_cda(profile_data, parameters, target_entry_speed_kph=None, target_timed_section_s=None, effort_type=200, max_iterations=50):
    """
    Compute the breakeven CdA that achieves target entry speed or timed section time.
    Uses binary search to find the CdA value.

    Args:
        profile_data: Profile rows with s_m, y_m, CdA_m2, P_W
        parameters: Simulation parameters
        target_entry_speed_kph: Target entry speed at 695m (for entry speed breakeven)
        target_timed_section_s: Target time for timed section (for time breakeven)
        effort_type: 50, 100, 150, or 200 (meters)
        max_iterations: Maximum binary search iterations

    Returns:
        dict with breakeven_cda_entry, breakeven_cda_time, and convergence info
    """
    try:
        rows = profile_data.get("rows", profile_data)
        if not rows or len(rows) == 0:
            return {"success": False, "error": "No profile data"}

        # Apply track geometry
        apply_track_geometry_from_params(parameters)

        # Setup model parameters
        model.MASS = safe_float(parameters.get("mass_kg"), DEFAULTS["mass_kg"])
        model.RHO = safe_float(parameters.get("rho"), DEFAULTS["rho"])
        model.C_RR = safe_float(parameters.get("crr"), DEFAULTS["crr"])
        model.CP = safe_float(parameters.get("cp_W"), DEFAULTS["cp_W"])
        model.W_PRIME_TOTAL = safe_float(parameters.get("wPrime_J"), DEFAULTS["wPrime_J"])
        model.V0 = safe_float(parameters.get("v0_mps"), DEFAULTS["v0_mps"])
        model.DRIVETRAIN_EFF = safe_float(parameters.get("drivetrain_eff"), DEFAULTS["drivetrain_eff"])

        # CdA bend factor (reduces CdA in bends when < 1.0)
        cda_bend_factor = safe_float(parameters.get("cda_bend_factor"), DEFAULTS["cda_bend_factor"])

        # Extract profile data
        s_input = np.array([safe_float(r.get("s_m"), 0) for r in rows])
        y_input = np.array([safe_float(r.get("y_m"), 3.5) for r in rows])
        CdA_input_base = np.array([safe_float(r.get("CdA_m2"), 0.24) for r in rows])  # Default to 0.24
        P_input = np.array([safe_float(r.get("P_W"), 0) for r in rows])

        target_s_grid = model.s_grid
        y_grid = np.interp(target_s_grid, s_input, y_input)
        P_grid = np.interp(target_s_grid, s_input, P_input)

        # Get base CdA value (use the mean of what was passed in, or default 0.24)
        base_cda = float(np.mean(CdA_input_base))
        if base_cda < 0.15 or base_cda > 0.40:
            base_cda = 0.24  # Reset to sensible default if out of range

        # Calculate number of splits based on effort type
        num_splits = effort_type // 50  # F200=4, F150=3, F100=2, F50=1

        def run_with_cda(cda_value):
            """Run simulation with absolute CdA value (uniform across profile)."""
            CdA_grid = np.full_like(target_s_grid, cda_value)
            # Apply bend factor (reduces CdA in bends)
            CdA_grid = apply_cda_bend_factor(CdA_grid, target_s_grid, cda_bend_factor)

            result = model.simulate_profile(
                y_grid=y_grid,
                CdA_grid=CdA_grid,
                P_grid=P_grid,
                label="test"
            )

            entry_speed_kph = float(result.get("v_200_entry", 0)) * 3.6
            splits = result.get("splits_200", [0, 0, 0, 0])
            timed_section_s = sum(splits[:num_splits])

            return entry_speed_kph, timed_section_s

        # First, run with base CdA to get baseline values
        base_entry_speed, base_timed_section = run_with_cda(base_cda)

        # Debug: check power profile
        p_min = float(np.min(P_grid))
        p_max = float(np.max(P_grid))
        p_mean = float(np.mean(P_grid))
        p_nonzero = int(np.sum(P_grid > 0))

        results = {
            "success": True,
            "breakeven_cda_entry": None,
            "breakeven_cda_time": None,
            "entry_speed_converged": False,
            "time_converged": False,
            "base_cda": round(base_cda, 4),
            "base_entry_speed_kph": round(base_entry_speed, 2),
            "base_timed_section_s": round(base_timed_section, 4),
            "debug_p_min": p_min,
            "debug_p_max": p_max,
            "debug_p_mean": round(p_mean, 1),
            "debug_p_nonzero_count": p_nonzero,
            "debug_p_grid_len": len(P_grid),
            "debug_s_input_range": f"{float(s_input[0])}-{float(s_input[-1])}",
        }

        # Binary search for entry speed breakeven CdA
        if target_entry_speed_kph is not None and target_entry_speed_kph > 0:
            lo, hi = 0.15, 0.60  # Absolute CdA range

            # First check if target is achievable within range
            speed_at_lo, _ = run_with_cda(lo)  # Low CdA = fast
            speed_at_hi, _ = run_with_cda(hi)  # High CdA = slow

            results["debug_entry_speed_at_lo_cda"] = round(speed_at_lo, 2)
            results["debug_entry_speed_at_hi_cda"] = round(speed_at_hi, 2)

            # Check if target is within achievable range
            if target_entry_speed_kph > speed_at_lo:
                # Target faster than achievable with lowest CdA
                results["breakeven_cda_entry"] = round(lo, 4)
                results["entry_speed_converged"] = False
                results["entry_speed_note"] = "Target faster than achievable"
            elif target_entry_speed_kph < speed_at_hi:
                # Target slower than achievable with highest CdA
                results["breakeven_cda_entry"] = round(hi, 4)
                results["entry_speed_converged"] = False
                results["entry_speed_note"] = "Target slower than achievable"
            else:
                # Binary search
                for iteration in range(max_iterations):
                    mid = (lo + hi) / 2
                    entry_speed, _ = run_with_cda(mid)

                    if abs(entry_speed - target_entry_speed_kph) < 0.1:  # 0.1 kph precision
                        results["breakeven_cda_entry"] = round(mid, 4)
                        results["entry_speed_converged"] = True
                        results["entry_speed_iterations"] = iteration + 1
                        results["entry_speed_achieved_kph"] = round(entry_speed, 2)
                        break

                    # Higher CdA = more drag = slower speed
                    # If simulated speed > target, need higher CdA (more drag, slower)
                    # If simulated speed < target, need lower CdA (less drag, faster)
                    if entry_speed > target_entry_speed_kph:
                        lo = mid  # Need higher CdA to slow down
                    else:
                        hi = mid  # Need lower CdA to speed up
                else:
                    # Didn't converge, return best estimate
                    results["breakeven_cda_entry"] = round((lo + hi) / 2, 4)
                    results["entry_speed_converged"] = False

        # Binary search for timed section breakeven CdA
        if target_timed_section_s is not None and target_timed_section_s > 0:
            lo, hi = 0.15, 0.60  # Absolute CdA range

            # First check if target is achievable within range
            _, time_at_lo = run_with_cda(lo)  # Low CdA = fast = low time
            _, time_at_hi = run_with_cda(hi)  # High CdA = slow = high time

            results["debug_time_at_lo_cda"] = round(time_at_lo, 4)
            results["debug_time_at_hi_cda"] = round(time_at_hi, 4)

            # Check if target is within achievable range
            if target_timed_section_s < time_at_lo:
                # Target faster than achievable with lowest CdA
                results["breakeven_cda_time"] = round(lo, 4)
                results["time_converged"] = False
                results["time_note"] = "Target faster than achievable"
            elif target_timed_section_s > time_at_hi:
                # Target slower than achievable with highest CdA
                results["breakeven_cda_time"] = round(hi, 4)
                results["time_converged"] = False
                results["time_note"] = "Target slower than achievable"
            else:
                # Binary search
                for iteration in range(max_iterations):
                    mid = (lo + hi) / 2
                    _, timed_section = run_with_cda(mid)

                    if abs(timed_section - target_timed_section_s) < 0.001:  # 0.001s precision
                        results["breakeven_cda_time"] = round(mid, 4)
                        results["time_converged"] = True
                        results["time_iterations"] = iteration + 1
                        results["time_achieved_s"] = round(timed_section, 4)
                        break

                    # Higher CdA = more drag = slower = higher time
                    # If simulated time > target, need lower CdA (faster)
                    # If simulated time < target, need higher CdA (slower)
                    if timed_section > target_timed_section_s:
                        hi = mid  # Need lower CdA to go faster
                    else:
                        lo = mid  # Need higher CdA to go slower
                else:
                    # Didn't converge, return best estimate
                    results["breakeven_cda_time"] = round((lo + hi) / 2, 4)
                    results["time_converged"] = False

        return results

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def run_simulation(profile_data, parameters, power_curve_data=None):
    """
    Run simulation for base and modified profiles.
    """
    try:
        # Extract arrays from profile data
        rows = profile_data.get("rows", profile_data)

        if not rows or len(rows) == 0:
            return {"success": False, "error": "No profile data provided"}

        # Apply track geometry (must be done BEFORE setting other model params,
        # because it rebuilds s_grid, theta_grid, and section arrays)
        apply_track_geometry_from_params(parameters)

        # Update module-level globals with user parameters
        model.MASS = safe_float(parameters.get("mass_kg"), DEFAULTS["mass_kg"])
        model.RHO = safe_float(parameters.get("rho"), DEFAULTS["rho"])
        model.C_RR = safe_float(parameters.get("crr"), DEFAULTS["crr"])
        model.CP = safe_float(parameters.get("cp_W"), DEFAULTS["cp_W"])
        model.W_PRIME_TOTAL = safe_float(parameters.get("wPrime_J"), DEFAULTS["wPrime_J"])
        model.V0 = safe_float(parameters.get("v0_mps"), DEFAULTS["v0_mps"])
        model.DRIVETRAIN_EFF = safe_float(parameters.get("drivetrain_eff"), DEFAULTS["drivetrain_eff"])

        # CdA bend factor (reduces CdA in bends when < 1.0)
        cda_bend_factor = safe_float(parameters.get("cda_bend_factor"), DEFAULTS["cda_bend_factor"])

        # Extract input s_m values and corresponding data
        s_input = np.array([safe_float(r.get("s_m"), 0) for r in rows])

        # Base values with safe conversion
        y_input_base = np.array([safe_float(r.get("y_m"), 3.5) for r in rows])
        CdA_input_base = np.array([safe_float(r.get("CdA_m2"), 0.21) for r in rows])
        P_input_base = np.array([safe_float(r.get("P_W"), 0) for r in rows])

        # Modified values (use _2 columns if present and not empty, else use base)
        y_input_mod = np.array([
            safe_float(r.get("y_m_2"), safe_float(r.get("y_m"), 3.5))
            for r in rows
        ])
        CdA_input_mod = np.array([
            safe_float(r.get("CdA_m2_2"), safe_float(r.get("CdA_m2"), 0.21))
            for r in rows
        ])
        P_input_mod = np.array([
            safe_float(r.get("P_W_2"), safe_float(r.get("P_W"), 0))
            for r in rows
        ])

        # The model uses module-level s_grid (0 to 895m with 0.25m spacing = 3581 points)
        # We need to interpolate our input arrays onto this grid
        target_s_grid = model.s_grid

        # Interpolate base values onto model's s_grid
        y_base = np.interp(target_s_grid, s_input, y_input_base)
        CdA_base = np.interp(target_s_grid, s_input, CdA_input_base)
        P_base = np.interp(target_s_grid, s_input, P_input_base)

        # Interpolate modified values onto model's s_grid
        y_mod = np.interp(target_s_grid, s_input, y_input_mod)
        CdA_mod = np.interp(target_s_grid, s_input, CdA_input_mod)
        P_mod = np.interp(target_s_grid, s_input, P_input_mod)

        # Apply CdA bend factor (reduces CdA in bends when factor < 1.0)
        CdA_base = apply_cda_bend_factor(CdA_base, target_s_grid, cda_bend_factor)
        CdA_mod = apply_cda_bend_factor(CdA_mod, target_s_grid, cda_bend_factor)

        # Run base simulation using the correct function signature
        base_result = model.simulate_profile(
            y_grid=y_base,
            CdA_grid=CdA_base,
            P_grid=P_base,
            label="base"
        )

        # Run modified simulation
        mod_result = model.simulate_profile(
            y_grid=y_mod,
            CdA_grid=CdA_mod,
            P_grid=P_mod,
            label="mod"
        )

        # Extract key results
        def extract_results(result, label, CdA_grid, P_grid):
            # Get velocity array and compute max
            v_array = result.get("v", np.array([0]))
            v_max = float(np.max(v_array)) if len(v_array) > 0 else 0

            # Get W' remaining at end
            W_prime_arr = result.get("W_prime_rem", np.array([0]))
            W_prime_remaining = float(W_prime_arr[-1]) if len(W_prime_arr) > 0 else 0

            # Get time array
            t_array = result.get("t", np.array([0]))

            # Use the model's s_grid for distance values
            s_array = model.s_grid

            return {
                "label": label,
                "T_total": float(result.get("T_total", 0)),
                "T_200": float(result.get("T_200", 0)),
                "T_sprint": float(result.get("T_sprint", 0)),
                "v_200_entry_kph": float(result.get("v_200_entry", 0)) * 3.6,
                "v_200_exit_kph": float(result.get("v_200_exit", 0)) * 3.6,
                "v_max_kph": v_max * 3.6,
                "P_avg_sprint": float(result.get("P_avg_sprint", 0)),
                "W_prime_remaining": W_prime_remaining,
                "s_sprint_start": float(result.get("s_sprint_start", 0)),
                "splits_200": [float(s) for s in result.get("splits_200", [])],
                # Speed profile for charting (downsample for performance)
                "speed_profile": [
                    {
                        "s_m": float(s),
                        "v_kph": float(v) * 3.6,
                        "t_s": float(t),
                        "section": str(sec),
                        "lap_idx": int(lap),
                        "p_w": float(p),
                        "cda": float(cda),
                    }
                    for s, v, t, sec, lap, p, cda in zip(
                        s_array[::4],  # Every 4th point from model's s_grid
                        v_array[::4],
                        t_array[::4],
                        model.section_arr[::4],
                        model.lap_idx_arr[::4],
                        P_grid[::4],
                        CdA_grid[::4],
                    )
                ]
            }

        base_extracted = extract_results(base_result, "base", CdA_base, P_base)
        mod_extracted = extract_results(mod_result, "mod", CdA_mod, P_mod)

        # Calculate per-section statistics
        section_stats = compute_section_stats(base_result, mod_result)

        # Calculate detailed 200m segment data for comparison table
        base_segments = compute_200m_segments(base_result, CdA_base, P_base, parameters)
        mod_segments = compute_200m_segments(mod_result, CdA_mod, P_mod, parameters)

        # Calculate comparison
        comparison = {
            "deltaT_total": mod_extracted["T_total"] - base_extracted["T_total"],
            "deltaT_200": mod_extracted["T_200"] - base_extracted["T_200"],
            "deltaT_sprint": mod_extracted["T_sprint"] - base_extracted["T_sprint"],
        }

        return {
            "success": True,
            "base": base_extracted,
            "mod": mod_extracted,
            "comparison": comparison,
            "section_stats": section_stats,
            "base_segments": base_segments,
            "mod_segments": mod_segments,
            "constants": {
                "S_TOTAL": float(model.S_TOTAL),
                "S_200_START": float(model.S_TOTAL - 200.0)
            }
        }

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def main():
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)

        action = input_data.get("action", "simulate")

        if action == "breakeven_cda":
            # Compute breakeven CdA values (single uniform CdA)
            profile = input_data.get("profile", {})
            parameters = input_data.get("parameters", {})
            target_entry_speed_kph = input_data.get("target_entry_speed_kph")
            target_timed_section_s = input_data.get("target_timed_section_s")
            effort_type = input_data.get("effort_type", 200)

            result = compute_breakeven_cda(
                profile,
                parameters,
                target_entry_speed_kph=target_entry_speed_kph,
                target_timed_section_s=target_timed_section_s,
                effort_type=effort_type
            )
        elif action == "dual_breakeven_cda":
            # Compute BOTH seated and standing breakeven CdA values
            profile = input_data.get("profile", {})
            parameters = input_data.get("parameters", {})
            target_entry_speed_kph = input_data.get("target_entry_speed_kph")
            target_timed_section_s = input_data.get("target_timed_section_s")
            segment_positions = input_data.get("segment_positions", {})
            effort_type = input_data.get("effort_type", 200)

            result = compute_dual_breakeven_cda(
                profile,
                parameters,
                target_entry_speed_kph=target_entry_speed_kph,
                target_timed_section_s=target_timed_section_s,
                segment_positions=segment_positions,
                effort_type=effort_type
            )
        else:
            # Default: run simulation
            profile = input_data.get("profile", {})
            parameters = input_data.get("parameters", {})
            power_curve = input_data.get("power_curve")

            result = run_simulation(profile, parameters, power_curve)

        print(json.dumps(result))
    except Exception as e:
        import traceback
        print(json.dumps({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }))


if __name__ == "__main__":
    main()
