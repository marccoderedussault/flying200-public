"""
Flying 200 Energy Budget Optimizer Web API Wrapper

Accepts JSON input with power curves, profile, and rider parameters.
Runs EnergyBudgetOptimizer and returns comprehensive results including
smoothed power profiles, segment allocations, and constraint diagnostics.

This wrapper provides exact parity with the Python GUI implementation.
"""

import sys
import os
import json
import numpy as np
import time as time_module

# Power optimizer is in the same directory (local copy with all required classes)
# No path manipulation needed as PYTHONPATH includes this directory


def log(msg):
    """Log to stderr for debugging (visible in server logs)"""
    print(f"[run_energy_optimizer] {msg}", file=sys.stderr, flush=True)


log("=" * 60)
log("Script started - importing modules...")

try:
    from power_optimizer import (
        EnergyBudgetOptimizer,
        calculate_watts_cda_analysis,
        smooth_power_profile
    )
    log("Successfully imported power_optimizer")
except ImportError as e:
    log(f"IMPORT ERROR: {e}")
    import traceback
    log(traceback.format_exc())
    raise

# Import flying200_model for physics simulation (same as frontend)
try:
    import flying200_model as model
    log("Successfully imported flying200_model")
except ImportError as e:
    log(f"IMPORT ERROR flying200_model: {e}")
    import traceback
    log(traceback.format_exc())
    raise

# Track geometry from flying200_model (ensures consistency with frontend)
LAP_LEN = model.LAP_LEN  # 250m
L_STRAIGHT = model.L_STRAIGHT  # 59m
ARC_LEN = model.ARC_LEN  # ~66.3m
R_BEND = model.R_BEND  # ~21.1m
S_OFFSET = model.S_OFFSET
S_TOTAL = model.S_TOTAL  # 895m

# Global effort type (set by main, used by simulate_profile)
EFFORT_TYPE = 200  # Default to F200


def in_bend_region(s_global):
    """Check if position is in bend region (uses model geometry)."""
    return model.in_bend_region(s_global)


def apply_cda_bend_factor(CdA_grid, s_grid, cda_bend_factor):
    """
    Apply CdA bend factor to reduce drag in bends.

    Factor < 1.0 means CdA is LOWER in bends (due to yaw angle reducing frontal area).
    Example: factor=0.97 means bend CdA is 97% of straight CdA.

    This matches run_simulation.py exactly.
    """
    if cda_bend_factor >= 1.0 or cda_bend_factor <= 0:
        return CdA_grid  # No modification needed

    modified_CdA = CdA_grid.copy()
    for i, s in enumerate(s_grid):
        if model.in_bend_region(float(s)):
            modified_CdA[i] = CdA_grid[i] * cda_bend_factor

    return modified_CdA


def get_section_name(s_m):
    """Get track section name at distance s_m."""
    # Use model's section classification
    lap_idx, section, quarter = model.classify_section_and_quarter(s_m)
    return section


def calculate_effort_time(result, effort_type=200):
    """
    Calculate time for a specific effort type from simulation result.

    Args:
        result: Simulation result dict with 'splits_200' key
        effort_type: Effort distance in meters (50, 100, 150, or 200)

    Returns:
        Time in seconds for the specified effort
    """
    if 'splits_200' not in result or not result['splits_200']:
        # Fallback to T_200 if splits not available
        return result.get('T_200', 0)

    # Calculate number of splits needed
    # F200=4 splits, F150=3 splits, F100=2 splits, F50=1 split
    num_splits = effort_type // 50
    splits = result['splits_200'][:num_splits]

    return sum(splits) if splits else result.get('T_200', 0)


def simulate_profile(y_grid, CdA_grid, P_grid, params, s_grid, theta_grid, label="base"):
    """
    Simulate the profile using flying200_model physics.

    This wrapper sets model parameters and calls model.simulate_profile()
    to ensure physics match the frontend exactly.
    """
    # Set model parameters from params dict
    model.MASS = params.get('mass', 92.0)
    model.RHO = params.get('rho', 1.1627)
    model.C_RR = params.get('crr', 0.002)
    model.CP = params.get('CP', 250.0)
    model.W_PRIME_TOTAL = params.get('W_PRIME_TOTAL', 25000.0)
    model.V0 = params.get('V0', 5.0)
    model.MIN_V = params.get('MIN_V', 0.1)
    model.DRIVETRAIN_EFF = params.get('drivetrain_eff', 0.98)

    # Call model's simulate_profile (uses module-level globals)
    result = model.simulate_profile(
        y_grid=y_grid,
        CdA_grid=CdA_grid,
        P_grid=P_grid,
        label=label
    )

    # Recalculate T_200 based on effort type (model always returns F200)
    # This ensures optimizer uses correct time for F50/F100/F150 efforts
    if EFFORT_TYPE != 200:
        result['T_200'] = calculate_effort_time(result, EFFORT_TYPE)

    return result


def build_grids_from_profile(profile_data, rider_params, s_total=895.0, ds=0.25):
    """
    Build simulation grids from profile data.

    Uses model.s_grid and model.theta_grid for consistency with frontend simulation.

    Args:
        profile_data: List of {s_m, y_m, CdA_m2, P_W} dicts
        rider_params: Dict with rider parameters
        s_total: Total simulation distance
        ds: Grid spacing

    Returns:
        Tuple of (s_grid, y_grid, CdA_profile_grid, CdA_seated_grid, CdA_standing_grid, P_base_grid, theta_grid, params)
    """
    # Use model's s_grid for exact consistency with frontend
    s_grid = model.s_grid
    n = len(s_grid)

    # Extract profile arrays
    profile_s = np.array([p['s_m'] for p in profile_data])
    profile_y = np.array([p.get('y_m', 0.0) for p in profile_data])
    profile_CdA = np.array([p.get('CdA_m2', rider_params.get('cda_seated', 0.24)) for p in profile_data])
    profile_P = np.array([p.get('P_W', 0.0) for p in profile_data])

    # Interpolate to s_grid
    y_grid = np.interp(s_grid, profile_s, profile_y)
    P_base_grid = np.interp(s_grid, profile_s, profile_P)

    # Interpolate profile CdA to s_grid for baseline simulation
    # This matches how run_simulation.py handles CdA
    CdA_profile_grid = np.interp(s_grid, profile_s, profile_CdA)

    # Build CdA grids from rider params (CONSTANT values for optimization)
    # These are used by the optimizer to explore seated/standing choices
    cda_seated = rider_params.get('cda_seated', 0.24)
    cda_standing = rider_params.get('cda_standing', 0.38)
    CdA_seated_grid = np.full_like(s_grid, cda_seated)
    CdA_standing_grid = np.full_like(s_grid, cda_standing)

    # Use model's theta_grid for correct track geometry
    theta_grid = model.theta_grid

    # Build simulation params (matching run_simulation.py defaults exactly)
    params = {
        'mass': rider_params.get('mass', 92.0),
        'rho': rider_params.get('rho', 1.1627),  # Match run_simulation.py default
        'crr': rider_params.get('crr', 0.002),
        'g': 9.81,
        'V0': rider_params.get('v0', 5.0),  # Model default is 5.0
        'MIN_V': 0.1,  # Model default
        'CP': rider_params.get('cp', 250),  # Model default is 250
        'W_PRIME_TOTAL': rider_params.get('w_prime', 25000),
        'drivetrain_eff': rider_params.get('drivetrain_eff', 0.98),  # Match run_simulation.py default (2% loss)
        'cda_bend_factor': rider_params.get('cda_bend_factor', 1.0),
    }

    return s_grid, y_grid, CdA_profile_grid, CdA_seated_grid, CdA_standing_grid, P_base_grid, theta_grid, params


def build_power_curve_dict(curve_data, durations_data=None, max_duration=60):
    """
    Build power curve dictionary from input data.

    Args:
        curve_data: List of {duration_s, power_W} or flat array of powers
        durations_data: Optional list of durations (e.g., [1, 2, 3, 5, 10, 15, 20, 30, 40, 60])
        max_duration: Maximum duration to include

    Returns:
        Dict mapping duration_s -> power_W
    """
    if not curve_data:
        return {}

    if isinstance(curve_data[0], dict):
        # Format: [{duration_s: 1, power_W: 1400}, ...]
        return {
            int(p['duration_s']): p['power_W']
            for p in curve_data
            if p['duration_s'] <= max_duration
        }
    else:
        # Format: [1400, 1350, 1300, ...] with explicit durations
        if durations_data is not None:
            # Use explicit durations (e.g., [1, 2, 3, 5, 10, 15, 20, 30, 40, 60])
            return {
                int(d): curve_data[i]
                for i, d in enumerate(durations_data)
                if d <= max_duration and i < len(curve_data)
            }
        else:
            # Legacy fallback: assume contiguous (1s, 2s, 3s, ...)
            return {
                i + 1: p
                for i, p in enumerate(curve_data[:max_duration])
            }


def build_constraint_table(optimizer, s_grid, elapsed_time_grid, P_discrete, P_smooth=None):
    """
    Build constraint diagnostics table for each grid point.

    Args:
        optimizer: EnergyBudgetOptimizer instance
        s_grid: Distance grid
        elapsed_time_grid: Elapsed time at each grid point
        P_discrete: Discrete power grid
        P_smooth: Smoothed power grid (optional)

    Returns:
        List of constraint diagnostic dicts
    """
    diagnostics = []
    opt_start_idx = np.searchsorted(s_grid, optimizer.opt_start_m)

    # Calculate running average at each point
    cumulative_energy = 0.0
    ds_grid = np.diff(s_grid)
    ds_grid = np.append(ds_grid, ds_grid[-1])

    for i in range(opt_start_idx, len(s_grid), 40):  # Sample every 10m (40 * 0.25m)
        s_m = s_grid[i]
        elapsed_s = elapsed_time_grid[i]

        if elapsed_s <= 0:
            continue

        # Calculate cumulative energy up to this point
        P_to_use = P_smooth if P_smooth is not None else P_discrete
        energy_here = 0
        for j in range(opt_start_idx, i + 1):
            dt = elapsed_time_grid[j] - (elapsed_time_grid[j-1] if j > 0 else 0)
            energy_here += P_to_use[j] * max(dt, 0.001)

        running_avg = energy_here / elapsed_s if elapsed_s > 0 else 0

        # Get floor and ceiling
        baseline_power = optimizer.P_base_grid[i]
        floor = baseline_power * optimizer.min_power_pct
        ceiling = optimizer.get_max_power(elapsed_s, 'seated')

        # Determine status
        if running_avg > ceiling * 1.01:
            status = f"CEILING EXCEEDED (+{(running_avg - ceiling):.0f}W)"
        elif P_discrete[i] < floor * 0.99:
            status = f"BELOW FLOOR (-{(floor - P_discrete[i]):.0f}W)"
        else:
            status = "OK"

        diagnostics.append({
            's_m': round(s_m, 1),
            'elapsed_s': round(elapsed_s, 2),
            'P_discrete': round(P_discrete[i], 0),
            'P_smooth': round(P_smooth[i], 0) if P_smooth is not None else None,
            'floor': round(floor, 0),
            'ceiling': round(ceiling, 0),
            'running_avg': round(running_avg, 0),
            'status': status
        })

    return diagnostics


def build_detail_table(optimizer, baseline_result, opt_result, s_grid, P_base_grid, P_opt_grid):
    """
    Build 10-column detail table matching Python GUI.

    Columns: Segment, Section, v Base, v Opt, Δv, Δt, P Base, P Opt, ΔP, Position
    """
    details = []

    # Use the module-level get_section_name function (uses model.classify_section_and_quarter)

    # Create interpolators for velocity
    v_base_interp = np.interp
    v_opt_interp = np.interp

    # Get time interpolators
    t_base = baseline_result['t']
    t_opt = opt_result['t']

    # Calculate details at 10m intervals in the optimization zone
    opt_start = optimizer.opt_start_m
    s_total = s_grid[-1]

    for seg_start in range(int(opt_start), int(s_total), 10):
        seg_end = min(seg_start + 10, s_total)
        seg_mid = (seg_start + seg_end) / 2

        # Get velocities
        v_base = np.interp(seg_mid, s_grid, baseline_result['v']) * 3.6  # km/h
        v_opt = np.interp(seg_mid, s_grid, opt_result['v']) * 3.6  # km/h
        delta_v = v_opt - v_base

        # Get times
        t_base_start = np.interp(seg_start, s_grid, t_base)
        t_base_end = np.interp(seg_end, s_grid, t_base)
        t_opt_start = np.interp(seg_start, s_grid, t_opt)
        t_opt_end = np.interp(seg_end, s_grid, t_opt)

        dt_base = t_base_end - t_base_start
        dt_opt = t_opt_end - t_opt_start
        delta_t = dt_opt - dt_base  # Negative = faster

        # Get powers
        seg_mask = (s_grid >= seg_start) & (s_grid < seg_end)
        P_base = P_base_grid[seg_mask].mean() if seg_mask.any() else 0
        P_opt = P_opt_grid[seg_mask].mean() if seg_mask.any() else 0
        delta_P = P_opt - P_base

        # Get position from optimizer segments
        position = 'seated'
        if hasattr(optimizer, '_last_segment_positions') and optimizer._last_segment_positions:
            for seg_idx, seg in enumerate(optimizer.segments):
                if seg['start_m'] <= seg_mid < seg['end_m']:
                    if seg_idx < len(optimizer._last_segment_positions):
                        position = optimizer._last_segment_positions[seg_idx]
                    break

        details.append({
            'segment': f"{seg_start}-{seg_end}",
            'section': get_section_name(seg_mid),
            'v_base_kph': round(v_base, 2),
            'v_opt_kph': round(v_opt, 2),
            'delta_v_kph': round(delta_v, 2),
            'delta_t_s': round(delta_t, 4),
            'P_base_W': round(P_base, 0),
            'P_opt_W': round(P_opt, 0),
            'delta_P_W': round(delta_P, 0),
            'position': position
        })

    return details


def run_energy_optimization(input_data):
    """
    Run the EnergyBudgetOptimizer with exact Python GUI parity.

    Args:
        input_data: Dictionary with:
            - power_curves: {seated: [...], standing: [...]}
            - profile: [{s_m, y_m, CdA_m2, P_W}, ...]
            - rider_params: {mass, rho, crr, cda_seated, cda_standing, ...}
            - config: {opt_start_m, segment_length_m, energy_budget_J, ...}
            - options: {n_samples, stream_progress, smoothing_method, ...}

    Returns:
        Comprehensive optimization result dictionary
    """
    start_time = time_module.time()
    log("=" * 60)
    log("run_energy_optimization() called")

    try:
        # Extract inputs
        power_curves = input_data.get('power_curves', {})
        profile_data = input_data.get('profile', [])
        rider_params = input_data.get('rider_params', {})
        config = input_data.get('config', {})
        options = input_data.get('options', {})

        log(f"Power curves - seated: {len(power_curves.get('seated', []))} pts, standing: {len(power_curves.get('standing', []))} pts")
        log(f"Profile data: {len(profile_data)} points")
        log(f"Rider params: {rider_params}")
        log(f"Config: {config}")
        log(f"Options: {options}")

        # Validate inputs
        if not power_curves.get('seated') or not power_curves.get('standing'):
            log("ERROR: Missing seated or standing power curve")
            return {"success": False, "error": "Missing seated or standing power curve"}

        if not profile_data:
            log("ERROR: Missing wind-up profile")
            return {"success": False, "error": "Missing wind-up profile"}

        # Build power curve dictionaries (with optional explicit durations)
        log("Building power curve dictionaries...")
        durations_data = power_curves.get('durations', None)
        seated_curve = build_power_curve_dict(power_curves['seated'], durations_data)
        standing_curve = build_power_curve_dict(power_curves['standing'], durations_data)
        log(f"Seated curve durations: {sorted(seated_curve.keys())}")
        log(f"Standing curve durations: {sorted(standing_curve.keys())}")
        # Log actual power values at key durations to verify curve is correct
        log(f"Seated curve values: 1s={seated_curve.get(1, 'N/A')}, 5s={seated_curve.get(5, 'N/A')}, 10s={seated_curve.get(10, 'N/A')}, 15s={seated_curve.get(15, 'N/A')}")
        log(f"Standing curve values: 1s={standing_curve.get(1, 'N/A')}, 5s={standing_curve.get(5, 'N/A')}, 10s={standing_curve.get(10, 'N/A')}, 15s={standing_curve.get(15, 'N/A')}")

        # Build simulation grids
        log("Building simulation grids...")
        s_total = config.get('s_total', 895.0)
        ds = config.get('ds', 0.25)

        s_grid, y_grid, CdA_profile_grid, CdA_seated_grid, CdA_standing_grid, P_base_grid, theta_grid, params = \
            build_grids_from_profile(profile_data, rider_params, s_total, ds)
        log(f"Grid size: {len(s_grid)} points, s_range: {s_grid[0]}-{s_grid[-1]}")

        # Apply cda_bend_factor to ALL CdA grids (matching run_simulation.py)
        # This must be applied consistently — profile, seated, and standing
        cda_bend_factor = params.get('cda_bend_factor', 1.0)
        CdA_profile_grid = apply_cda_bend_factor(CdA_profile_grid, s_grid, cda_bend_factor)
        CdA_seated_grid = apply_cda_bend_factor(CdA_seated_grid, s_grid, cda_bend_factor)
        CdA_standing_grid = apply_cda_bend_factor(CdA_standing_grid, s_grid, cda_bend_factor)
        log(f"Applied cda_bend_factor={cda_bend_factor} to all CdA grids (profile, seated, standing)")

        # Extract config parameters (with defaults matching Python GUI)
        opt_start_m = config.get('opt_start_m', 480.0)
        timed_start_m = config.get('timed_start_m', 695.0)
        segment_length_m = config.get('segment_length_m', 50.0)
        min_standing_m = config.get('min_standing_m', 50.0)
        energy_budget_J = config.get('energy_budget_J', 25000.0)
        energy_levels = config.get('energy_levels', 10)
        min_power_pct = config.get('min_power_pct', 0.8)  # 80% of baseline floor (user configurable)
        timed_mode = config.get('timed_mode', 'FLATOUT')
        constraint_buffer_pct = config.get('constraint_buffer_pct', 0.02)  # 2% buffer for floor/ceiling

        # Extract options
        n_samples = options.get('n_samples', 1000)
        stream_progress = options.get('stream_progress', False)
        smoothing_method = options.get('smoothing_method', 'cubic')
        max_position_iterations = options.get('max_position_iterations', 3)
        effort_type = options.get('effort_type', 200)  # F50, F100, F150, or F200
        optimizer_method = options.get('optimizer_method', 'legacy')  # 'legacy' or 'slsqp'
        gravity_aware = options.get('gravity_aware_position', False)  # gravity-aware position decision

        # Set global effort type for simulate_profile to use
        global EFFORT_TYPE
        EFFORT_TYPE = effort_type
        log(f"Effort type: F{effort_type}")

        # Log key optimization parameters
        log(f"Config: energy_budget={energy_budget_J}J, min_power_pct={min_power_pct*100:.0f}%, buffer={constraint_buffer_pct*100:.0f}%, n_samples={n_samples}")
        log(f"Segments: opt_start={opt_start_m}m, segment_len={segment_length_m}m, timed_mode={timed_mode}")
        log(f"Optimizer method: {optimizer_method}, gravity_aware_position: {gravity_aware}")

        # Create optimizer
        log("Creating EnergyBudgetOptimizer...")
        optimizer = EnergyBudgetOptimizer(
            simulate_func=simulate_profile,
            params=params,
            s_grid=s_grid,
            theta_grid=theta_grid,
            y_base_grid=y_grid,
            CdA_standing_grid=CdA_standing_grid,
            CdA_seated_grid=CdA_seated_grid,
            P_base_grid=P_base_grid,
            power_curve_seated=seated_curve,
            power_curve_standing=standing_curve,
            total_energy_budget_J=energy_budget_J,
            opt_start_m=opt_start_m,
            timed_start_m=timed_start_m,
            segment_length_m=segment_length_m,
            min_standing_m=min_standing_m,
            min_power_pct=min_power_pct,
            timed_mode=timed_mode,
            constraint_buffer_pct=constraint_buffer_pct,
            gravity_aware_position=gravity_aware,
            CdA_profile_grid=CdA_profile_grid
        )
        log(f"Optimizer created with {len(optimizer.segments)} segments")
        # Log interpolated ceiling values at key elapsed times (these are what actually constrain the optimizer)
        for t in [3, 5, 8, 10, 12, 15]:
            ceiling_seated = optimizer.get_max_power(t, 'seated')
            ceiling_standing = optimizer.get_max_power(t, 'standing')
            log(f"Ceiling at t={t}s: seated={ceiling_seated:.0f}W, standing={ceiling_standing:.0f}W")

        # Log baseline power in optimization zone
        opt_start_idx = np.searchsorted(s_grid, opt_start_m)
        opt_end_idx = np.searchsorted(s_grid, timed_start_m)  # End of FLATOUT pre-timed zone
        opt_zone_power = P_base_grid[opt_start_idx:opt_end_idx]
        log(f"Baseline power in opt zone ({opt_start_m}-{timed_start_m}m): min={opt_zone_power.min():.0f}W, max={opt_zone_power.max():.0f}W, avg={opt_zone_power.mean():.0f}W")
        log(f"Floor values (with {min_power_pct*100:.0f}% floor): min={opt_zone_power.min()*min_power_pct:.0f}W, max={opt_zone_power.max()*min_power_pct:.0f}W, avg={opt_zone_power.mean()*min_power_pct:.0f}W")

        # Run baseline simulation first using PROFILE CdA
        # This matches how run_simulation.py computes baseline (uses CdA from profile with segment positions)
        log("Running baseline simulation with profile CdA...")
        baseline_result = simulate_profile(
            y_grid, CdA_profile_grid, P_base_grid,
            params, s_grid, theta_grid, label="baseline"
        )
        # Calculate baseline time based on effort type
        internal_baseline_T_200 = calculate_effort_time(baseline_result, effort_type)
        log(f"Baseline time for F{effort_type}: {internal_baseline_T_200:.3f}s (using profile CdA with bend factor)")

        # Use provided baseline from frontend simulation if available
        # This ensures the baseline matches what the user sees in the main simulation
        provided_baseline_T_200 = options.get('baseline_T_200')

        if provided_baseline_T_200 is not None:
            baseline_T_200 = provided_baseline_T_200
            if stream_progress:
                # Log that we're using the provided baseline
                print(json.dumps({
                    "type": "debug",
                    "message": f"Using SIMULATION baseline T_200: {baseline_T_200:.3f}s (internal calc was: {internal_baseline_T_200:.3f}s)"
                }), flush=True)
        else:
            # Fall back to internally computed baseline (may differ from main sim due to physics differences)
            baseline_T_200 = internal_baseline_T_200
            if stream_progress:
                print(json.dumps({
                    "type": "debug",
                    "message": f"No simulation baseline provided - using INTERNAL baseline T_200: {baseline_T_200:.3f}s"
                }), flush=True)

        # Progress callback for streaming - includes solution details and profiles
        # Access optimizer's internal state to get current best solution
        last_best_time_sent = [float('inf')]  # Track when we last sent profile data

        def progress_callback(iteration, total, best_time):
            if stream_progress:
                progress_data = {
                    "type": "progress",
                    "current": iteration,
                    "total": total,
                    "best_time": round(best_time, 3) if best_time < float('inf') else None,
                    "valid_count": optimizer.valid_count,
                    "rejected_count": optimizer.rejected_count,
                }

                # Include solution details from optimizer's internal state if available
                if hasattr(optimizer, 'best_allocation') and optimizer.best_allocation is not None:
                    best_alloc = optimizer.best_allocation
                    best_pos = getattr(optimizer, 'best_positions', None) or ['seated'] * len(best_alloc)

                    # Build segment summary for current best
                    segments_info = []
                    try:
                        energy_alloc = optimizer.allocate_energy(best_alloc)
                        for seg_idx, (segment, frac) in enumerate(zip(optimizer.segments, best_alloc)):
                            pos = best_pos[seg_idx] if seg_idx < len(best_pos) else 'seated'
                            segments_info.append({
                                'start_m': segment['start_m'],
                                'end_m': segment['end_m'],
                                'energy_pct': round(frac * 100, 1),
                                'energy_J': round(energy_alloc[seg_idx], 0),
                                'position': pos
                            })

                        progress_data["best_allocation"] = [round(a, 4) for a in best_alloc]
                        progress_data["best_positions"] = list(best_pos)
                        progress_data["segments"] = segments_info

                        # Include profile data when we have a new best (for graphs when stopped)
                        # Only send profiles when best_time improves to reduce data transfer
                        if hasattr(optimizer, 'best_result') and optimizer.best_result is not None:
                            if best_time < last_best_time_sent[0]:
                                last_best_time_sent[0] = best_time
                                best_res = optimizer.best_result

                                # Downsample profiles for transfer (max 200 points)
                                step = max(1, len(s_grid) // 200)

                                # Get power grids
                                P_discrete = optimizer.P_discrete if hasattr(optimizer, 'P_discrete') else P_base_grid
                                CdA_opt = optimizer.CdA_optimized if hasattr(optimizer, 'CdA_optimized') else CdA_seated_grid

                                progress_data["profiles"] = {
                                    "distance_m": s_grid[::step].tolist(),
                                    "baseline_speed_kph": (baseline_result['v'][::step] * 3.6).tolist(),
                                    "optimized_speed_kph": (best_res['v'][::step] * 3.6).tolist(),
                                    "baseline_power_W": P_base_grid[::step].tolist(),
                                    "P_discrete": P_discrete[::step].tolist(),
                                    "CdA": CdA_opt[::step].tolist(),
                                    "baseline_CdA": CdA_seated_grid[::step].tolist(),
                                }

                                # Add comparison data using internal baseline for consistency
                                progress_data["comparison"] = {
                                    "baseline_T_200": round(internal_baseline_T_200, 3),
                                    "optimized_T_200": round(best_time, 3),
                                    "time_saved_ms": round((internal_baseline_T_200 - best_time) * 1000, 1),
                                    "improvement_pct": round((internal_baseline_T_200 - best_time) / internal_baseline_T_200 * 100, 2) if internal_baseline_T_200 > 0 else 0,
                                }

                    except Exception:
                        pass  # Skip solution details if there's an error

                progress_msg = json.dumps(progress_data)
                print(progress_msg, flush=True)
                sys.stdout.flush()

        # Run optimizer (legacy random search or SLSQP gradient-based)
        search_start = time_module.time()
        if optimizer_method == 'slsqp':
            log(f"Starting SLSQP optimization (gradient-based)")
            best_alloc, best_positions, best_time, best_result, was_stopped = optimizer.optimize_slsqp(
                energy_levels=energy_levels,
                progress_callback=progress_callback if stream_progress else None,
                max_position_iterations=max_position_iterations,
                baseline_result=baseline_result
            )
            search_elapsed = time_module.time() - search_start
            log(f"SLSQP optimization completed in {search_elapsed:.2f}s, was_stopped={was_stopped}")
        else:
            log(f"Starting random_search with n_samples={n_samples}, energy_levels={energy_levels}")
            best_alloc, best_positions, best_time, best_result, was_stopped = optimizer.random_search(
                n_samples=n_samples,
                energy_levels=energy_levels,
                progress_callback=progress_callback if stream_progress else None,
                max_position_iterations=max_position_iterations,
                baseline_result=baseline_result
            )
            search_elapsed = time_module.time() - search_start
            log(f"random_search completed in {search_elapsed:.2f}s, was_stopped={was_stopped}")

        # Safety check: never return a result that's slower than baseline
        if best_result is not None:
            opt_T_200 = best_result.get('T_200', float('inf'))
            if opt_T_200 >= internal_baseline_T_200:
                log(f"WARNING: Optimizer result ({opt_T_200:.3f}s) is not faster than baseline ({internal_baseline_T_200:.3f}s) - discarding")
                best_result = None

        if best_result is None:
            log(f"ERROR: No improvement found over baseline {internal_baseline_T_200:.3f}s")
            log(f"Samples tested: {optimizer.iteration_count}, Valid: {optimizer.valid_count}, Rejected: {optimizer.rejected_count}")

            # Build detailed diagnostics for debugging
            diagnostics = {
                "samples_tested": optimizer.iteration_count,
                "valid_samples": optimizer.valid_count,
                "rejected_samples": optimizer.rejected_count,
                "segments": [],
                "power_curve_ceilings": {},
                "baseline_powers": {},
            }

            # Calculate floor/ceiling for each segment
            avg_speed_estimate = 17.0  # m/s
            elapsed_time = 0.0
            opt_start_idx = np.searchsorted(s_grid, opt_start_m)

            for seg_idx, segment in enumerate(optimizer.segments):
                start_m = segment['start_m']
                end_m = segment['end_m']
                length_m = segment.get('length_m', end_m - start_m)
                seg_mask = (s_grid >= start_m) & (s_grid < end_m)

                # Get baseline power in this segment
                baseline_power = P_base_grid[seg_mask].mean() if seg_mask.any() else 0.0

                # Estimate segment duration
                seg_duration_est = length_m / avg_speed_estimate
                elapsed_time += seg_duration_est

                # Get power curve ceiling at this elapsed time
                ceiling_seated = optimizer.get_max_power(elapsed_time, 'seated')
                ceiling_standing = optimizer.get_max_power(elapsed_time, 'standing')

                # Calculate floor (min power as % of baseline)
                floor = baseline_power * min_power_pct

                # Determine if floor > ceiling (impossible segment)
                floor_exceeds_ceiling = bool(floor > ceiling_seated)

                seg_info = {
                    "segment": f"{int(start_m)}-{int(end_m)}m",
                    "elapsed_s": round(elapsed_time, 2),
                    "baseline_power_W": int(round(baseline_power, 0)),
                    "floor_W": int(round(floor, 0)),
                    "ceiling_seated_W": int(round(ceiling_seated, 0)),
                    "ceiling_standing_W": int(round(ceiling_standing, 0)),
                    "floor_exceeds_ceiling": floor_exceeds_ceiling,
                    "headroom_W": int(round(ceiling_seated - floor, 0)),
                }
                diagnostics["segments"].append(seg_info)
                log(f"Segment {int(start_m)}-{int(end_m)}m: baseline={baseline_power:.0f}W, floor={floor:.0f}W, ceiling={ceiling_seated:.0f}W, headroom={ceiling_seated - floor:.0f}W")

            # Add power curve ceiling values at key durations
            for t in [1, 2, 3, 5, 10, 15, 20, 30]:
                if seated_curve.get(t):
                    diagnostics["power_curve_ceilings"][f"{t}s"] = float(seated_curve[t])

            # Summary of first few baseline powers
            sample_distances = [500, 550, 600, 650, 700, 750, 800, 850]
            for dist in sample_distances:
                idx = np.searchsorted(s_grid, dist)
                if idx < len(P_base_grid):
                    diagnostics["baseline_powers"][f"{dist}m"] = int(round(P_base_grid[idx], 0))

            log(f"Power curve (first 5): {list(seated_curve.items())[:5]}")
            log(f"Baseline powers at key points: {diagnostics['baseline_powers']}")

            return {
                "success": False,
                "error": f"No improvement found over baseline ({internal_baseline_T_200:.3f}s). "
                         f"Tested {optimizer.iteration_count} samples, {optimizer.valid_count} valid, {optimizer.rejected_count} rejected. "
                         f"Try lowering Min Power % or increasing energy budget.",
                "baseline_T_200": float(round(internal_baseline_T_200, 3)),
                "diagnostics": diagnostics
            }

        # Run smoothed simulation
        smooth_result = optimizer.run_smoothed_simulation(
            smoothing_method=smoothing_method,
            preserve_energy=True
        )

        T_200_discrete = best_time
        T_200_smoothed = smooth_result['T_200_smoothed'] if smooth_result else best_time
        smoothing_penalty_ms = (T_200_smoothed - T_200_discrete) * 1000

        # Calculate improvement using internal baseline for consistency
        # (speeds and times should be from the same physics model)
        time_saved = internal_baseline_T_200 - T_200_smoothed
        improvement_ms = time_saved * 1000

        # Build elapsed time grid for constraint analysis
        elapsed_time_grid = np.zeros_like(s_grid)
        opt_start_idx = np.searchsorted(s_grid, opt_start_m)
        t_opt_start = best_result['t'][opt_start_idx]
        for i in range(len(s_grid)):
            if i >= opt_start_idx:
                elapsed_time_grid[i] = best_result['t'][i] - t_opt_start

        # Get power grids
        P_discrete = optimizer.P_discrete if hasattr(optimizer, 'P_discrete') else P_base_grid
        P_smooth = optimizer.P_smooth if hasattr(optimizer, 'P_smooth') else P_discrete
        CdA_optimized = optimizer.CdA_optimized if hasattr(optimizer, 'CdA_optimized') else CdA_seated_grid

        # Build constraint diagnostics
        constraint_diagnostics = build_constraint_table(
            optimizer, s_grid, elapsed_time_grid, P_discrete, P_smooth
        )

        # Build detail table
        detail_table = build_detail_table(
            optimizer, baseline_result, best_result,
            s_grid, P_base_grid, P_discrete
        )

        # Build segment allocation summary with track section names
        segments_summary = []
        energy_allocation = optimizer.allocate_energy(best_alloc)
        for seg_idx, (segment, frac) in enumerate(zip(optimizer.segments, best_alloc)):
            pos = best_positions[seg_idx] if seg_idx < len(best_positions) else 'seated'
            seg_energy = energy_allocation[seg_idx]
            # Get track section name at segment midpoint
            seg_mid = (segment['start_m'] + segment['end_m']) / 2
            section_name = get_section_name(seg_mid)
            segments_summary.append({
                'start_m': segment['start_m'],
                'end_m': segment['end_m'],
                'name': f"{int(segment['start_m'])}-{int(segment['end_m'])}m",
                'section': section_name,
                'energy_pct': round(frac * 100, 1),
                'energy_J': round(seg_energy, 0),
                'position': pos
            })

        # Downsample profiles for web (max 400 points)
        step = max(1, len(s_grid) // 400)

        # Build response
        response = {
            "success": True,
            "optimizer_method": optimizer_method,
            "gravity_aware_position": gravity_aware,
            "optimization": {
                "T_200_discrete": round(T_200_discrete, 3),
                "T_200_smoothed": round(T_200_smoothed, 3),
                "smoothing_penalty_ms": round(smoothing_penalty_ms, 1),
                "best_allocation": [round(a, 4) for a in best_alloc],
                "best_positions": best_positions,
                "iterations_used": optimizer.best_iterations_used,
            },
            "comparison": {
                # Use internally consistent values from optimizer's simulation
                # This ensures speeds and times are comparable (same physics model)
                "baseline_T_200": round(internal_baseline_T_200, 3),
                "optimized_T_200": round(T_200_smoothed, 3),
                "time_saved_ms": round((internal_baseline_T_200 - T_200_smoothed) * 1000, 1),
                "improvement_pct": round((internal_baseline_T_200 - T_200_smoothed) / internal_baseline_T_200 * 100, 2) if internal_baseline_T_200 > 0 else 0,
                "baseline_v_200_entry_kph": round(np.interp(timed_start_m, s_grid, baseline_result['v']) * 3.6, 2),
                "baseline_v_200_exit_kph": round(baseline_result['v'][-1] * 3.6, 2),
                "optimized_v_200_entry_kph": round(np.interp(timed_start_m, s_grid, best_result['v']) * 3.6, 2),
                "optimized_v_200_exit_kph": round(best_result['v'][-1] * 3.6, 2),
                # Also report frontend baseline for reference (may differ due to physics model)
                "frontend_baseline_T_200": round(baseline_T_200, 3) if provided_baseline_T_200 else None,
            },
            "statistics": {
                "samples_tested": optimizer.iteration_count,
                "valid_combinations": optimizer.valid_count,
                "rejected_violations": optimizer.rejected_count,
                "was_stopped": was_stopped,
            },
            "profiles": {
                "distance_m": s_grid[::step].tolist(),
                "baseline_speed_kph": (baseline_result['v'][::step] * 3.6).tolist(),
                "optimized_speed_kph": (best_result['v'][::step] * 3.6).tolist(),
                "baseline_power_W": P_base_grid[::step].tolist(),
                "P_discrete": P_discrete[::step].tolist(),
                "P_smooth": P_smooth[::step].tolist(),
                "CdA": CdA_optimized[::step].tolist(),
                "baseline_CdA": CdA_seated_grid[::step].tolist(),
            },
            "markers": {
                "timed_start_m": timed_start_m,
                "timed_end_m": s_total,
                "opt_start_m": opt_start_m,
            },
            "segments": segments_summary,
            "detail_table": detail_table,
            "constraint_diagnostics": constraint_diagnostics,
            "config_used": {
                "opt_start_m": opt_start_m,
                "timed_start_m": timed_start_m,
                "segment_length_m": segment_length_m,
                "min_standing_m": min_standing_m,
                "energy_budget_J": energy_budget_J,
                "energy_levels": energy_levels,
                "min_power_pct": min_power_pct,
                "constraint_buffer_pct": constraint_buffer_pct,
                "timed_mode": timed_mode,
                "n_samples": n_samples,
                "smoothing_method": smoothing_method,
                "optimizer_method": optimizer_method,
                "gravity_aware_position": gravity_aware,
            },
            "summary_text": build_summary_text(
                optimizer, internal_baseline_T_200, T_200_discrete, T_200_smoothed,
                smoothing_penalty_ms, improvement_ms, segments_summary, best_positions
            ),
        }

        total_elapsed = time_module.time() - start_time
        log(f"SUCCESS: T_200_smoothed={T_200_smoothed:.3f}s, total time={total_elapsed:.2f}s")
        log("=" * 60)
        return response

    except Exception as e:
        import traceback
        log(f"EXCEPTION: {e}")
        log(traceback.format_exc())
        log("=" * 60)
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def build_summary_text(optimizer, baseline_T_200, T_200_discrete, T_200_smoothed,
                       smoothing_penalty_ms, improvement_ms, segments, positions):
    """
    Build summary text matching Python GUI format exactly.
    """
    lines = [
        "=" * 50,
        "OPTIMIZATION COMPLETE",
        "=" * 50,
        "",
        f"Samples tested: {optimizer.iteration_count}",
        f"Valid combinations: {optimizer.valid_count}",
        f"Rejected (constraint violations): {optimizer.rejected_count}",
        f"Baseline 200m time: {baseline_T_200:.3f}s",
        f"Best 200m time: {T_200_discrete:.3f}s",
        f"Improvement: {improvement_ms:.0f}ms",
        "",
    ]

    # Position summary
    standing_ranges = []
    for i, pos in enumerate(positions):
        if pos == 'standing' and i < len(segments):
            seg = segments[i]
            standing_ranges.append(f"{seg['start_m']:.0f}-{seg['end_m']:.0f}m")

    if standing_ranges:
        lines.append(f"Position: Standing {', '.join(standing_ranges)}")
    else:
        lines.append("Position: All seated")

    lines.append(f"Position converged in {optimizer.best_iterations_used} iteration(s)")
    lines.append("")
    lines.append("Energy Allocation by Segment:")

    for seg in segments:
        pos_marker = "S" if seg['position'] == 'standing' else "s"
        lines.append(f"  [{pos_marker}] {seg['start_m']:.0f}-{seg['end_m']:.0f}m: "
                    f"{seg['energy_pct']:.1f}% ({seg['energy_J']:.0f} J)")

    lines.extend([
        "",
        "--- Power Smoothing ---",
        f"Discrete step-function time: {T_200_discrete:.3f}s",
        f"Smoothed power curve time:   {T_200_smoothed:.3f}s",
        f"Smoothing penalty:           +{smoothing_penalty_ms:.0f}ms",
        "",
        f"Realistic achievable time: {T_200_smoothed:.3f}s",
        f"Improvement over baseline: +{improvement_ms:.0f}ms",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    log("Reading input from stdin...")
    # Read input from stdin
    try:
        input_text = sys.stdin.read()
        log(f"Received {len(input_text)} bytes of input")
        input_data = json.loads(input_text)
        log("JSON parsed successfully")
    except json.JSONDecodeError as e:
        log(f"JSON PARSE ERROR: {e}")
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    # Run optimization
    result = run_energy_optimization(input_data)

    # Output result
    log("Writing JSON result to stdout...")
    print(json.dumps(result))
    log("Done.")
