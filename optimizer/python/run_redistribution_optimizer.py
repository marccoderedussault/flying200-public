"""
Flying 200 Power Redistribution Optimizer Web API Wrapper

Redistributes power across segments while maintaining constant total work (zero-sum).
Uses the actual activity power profile and finds optimal redistribution.
"""

import sys
import os
import json
import numpy as np
import time as time_module

# Power optimizer is in the same directory (local copy with PowerRedistributionOptimizer)
# No path manipulation needed as PYTHONPATH includes this directory


def log(msg):
    """Log to stderr for debugging (visible in server logs)"""
    print(f"[run_redistribution] {msg}", file=sys.stderr, flush=True)


log("=" * 60)
log("Script started - importing modules...")

try:
    from power_optimizer import PowerRedistributionOptimizer
    log("Successfully imported PowerRedistributionOptimizer")
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


def get_section_name(s_m):
    """Get track section name at distance s_m."""
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
    model.RHO = params.get('rho', 1.18)
    model.C_RR = params.get('crr', 0.002)
    model.CP = params.get('CP', 250.0)
    model.W_PRIME_TOTAL = params.get('W_PRIME_TOTAL', 25000.0)
    model.V0 = params.get('V0', 5.0)
    model.MIN_V = params.get('MIN_V', 0.1)
    model.DRIVETRAIN_EFF = params.get('drivetrain_eff', 1.0)

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


def apply_cda_bend_factor(CdA_grid, s_grid, cda_bend_factor):
    """Apply CdA bend factor to reduce drag in bends (matches run_simulation.py)."""
    if cda_bend_factor >= 1.0 or cda_bend_factor <= 0:
        return CdA_grid  # No modification needed

    modified_CdA = CdA_grid.copy()
    for i, s in enumerate(s_grid):
        if model.in_bend_region(float(s)):
            modified_CdA[i] = CdA_grid[i] * cda_bend_factor

    return modified_CdA


def build_grids_from_profile(profile_data, rider_params, s_total=895.0, ds=0.25):
    """Build simulation grids from profile data using model grids."""
    # Use model's s_grid for exact consistency with frontend
    s_grid = model.s_grid

    # Extract profile arrays
    profile_s = np.array([p['s_m'] for p in profile_data])
    profile_y = np.array([p.get('y_m', 0.0) for p in profile_data])
    profile_CdA = np.array([p.get('CdA_m2', rider_params.get('cda_seated', 0.24)) for p in profile_data])
    profile_P = np.array([p.get('P_W', 0.0) for p in profile_data])

    # Interpolate to s_grid
    y_grid = np.interp(s_grid, profile_s, profile_y)
    CdA_grid = np.interp(s_grid, profile_s, profile_CdA)
    P_grid = np.interp(s_grid, profile_s, profile_P)

    # Apply cda_bend_factor to reduce CdA in bends (matching run_simulation.py)
    cda_bend_factor = rider_params.get('cda_bend_factor', 1.0)
    CdA_grid = apply_cda_bend_factor(CdA_grid, s_grid, cda_bend_factor)

    # Use model's theta_grid for correct track geometry
    theta_grid = model.theta_grid

    # Build simulation params (matching run_simulation.py defaults exactly)
    params = {
        'mass': rider_params.get('mass', 92.0),
        'rho': rider_params.get('rho', 1.1627),  # Match run_simulation.py default
        'crr': rider_params.get('crr', 0.002),
        'g': 9.81,
        'V0': rider_params.get('v0', 5.0),
        'MIN_V': 0.1,
        'CP': rider_params.get('cp', 250),
        'W_PRIME_TOTAL': rider_params.get('w_prime', 25000),
        'drivetrain_eff': rider_params.get('drivetrain_eff', 0.98),  # Match run_simulation.py default (2% loss)
    }

    return s_grid, y_grid, CdA_grid, P_grid, theta_grid, params


def run_redistribution_optimization(input_data):
    """
    Run the PowerRedistributionOptimizer.
    """
    start_time = time_module.time()
    log("=" * 60)
    log("run_redistribution_optimization() called")

    try:
        # Extract inputs
        profile_data = input_data.get('profile', [])
        rider_params = input_data.get('rider_params', {})
        config = input_data.get('config', {})
        options = input_data.get('options', {})

        log(f"Profile data: {len(profile_data)} points")
        log(f"Rider params: {rider_params}")
        log(f"Config: {config}")
        log(f"Options: {options}")

        if not profile_data:
            log("ERROR: Missing profile")
            return {"success": False, "error": "Missing profile data"}

        # Build simulation grids
        log("Building simulation grids...")
        s_total = config.get('s_total', 895.0)
        ds = config.get('ds', 0.25)

        s_grid, y_grid, CdA_grid, P_grid, theta_grid, params = \
            build_grids_from_profile(profile_data, rider_params, s_total, ds)
        log(f"Grid size: {len(s_grid)} points")
        log(f"Power range: {P_grid.min():.0f} - {P_grid.max():.0f} W")

        # Config parameters
        opt_start_m = config.get('opt_start_m', 430.0)
        segment_length_m = config.get('segment_length_m', 50.0)
        segment_mode = config.get('segment_mode', 'fixed')
        max_adjustment_W = config.get('max_adjustment_W', 100.0)
        power_increment_W = config.get('power_increment_W', 10.0)

        # Options
        n_samples = options.get('n_samples', 500)
        stream_progress = options.get('stream_progress', False)
        effort_type = options.get('effort_type', 200)  # F50, F100, F150, or F200

        # Set global effort type for simulate_profile to use
        global EFFORT_TYPE
        EFFORT_TYPE = effort_type
        log(f"Effort type: F{effort_type}")

        # Create optimizer
        log("Creating PowerRedistributionOptimizer...")
        optimizer = PowerRedistributionOptimizer(
            simulate_func=simulate_profile,
            params=params,
            s_grid=s_grid,
            theta_grid=theta_grid,
            y_base_grid=y_grid,
            CdA_base_grid=CdA_grid,
            P_base_grid=P_grid,
            opt_start_m=opt_start_m,
            s_total=s_total,
            segment_mode=segment_mode,
            segment_length_m=segment_length_m,
            power_increment_W=power_increment_W,
            max_adjustment_W=max_adjustment_W,
        )
        log(f"Optimizer created with {len(optimizer.segments)} segments")

        # Run baseline
        log("Running baseline simulation...")
        baseline_result = optimizer.run_baseline()
        baseline_T_200 = baseline_result['T_200']
        log(f"Baseline T_200: {baseline_T_200:.3f}s")

        # Progress callback
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
                print(json.dumps(progress_data), flush=True)

        # Run optimization
        log(f"Starting random_search with n_samples={n_samples}")
        search_start = time_module.time()

        best_adjustments, best_time, best_result, was_stopped = optimizer.random_search(
            n_samples=n_samples,
            progress_callback=progress_callback if stream_progress else None,
        )

        search_elapsed = time_module.time() - search_start
        log(f"random_search completed in {search_elapsed:.2f}s, was_stopped={was_stopped}")

        if best_result is None:
            log("ERROR: No valid solution found")
            return {
                "success": False,
                "error": "No valid redistribution found. Try increasing max_adjustment_W."
            }

        # Calculate improvement
        improvement_ms = (baseline_T_200 - best_time) * 1000
        log(f"Best T_200: {best_time:.3f}s, improvement: {improvement_ms:.0f}ms")

        # Build segment summary with track section names
        segments_summary = []
        for i, segment in enumerate(optimizer.segments):
            adj = best_adjustments[i] if i < len(best_adjustments) else 0
            base_power = segment.get('base_avg_power', segment.get('base_avg_power_W', 0))
            # Get track section name at segment midpoint
            seg_mid = (segment['start_m'] + segment['end_m']) / 2
            section_name = get_section_name(seg_mid)

            segments_summary.append({
                'name': f"{int(segment['start_m'])}-{int(segment['end_m'])}m",
                'section': section_name,
                'start_m': segment['start_m'],
                'end_m': segment['end_m'],
                'base_power_W': round(base_power, 0),
                'adjustment_W': round(adj, 0),
                'new_power_W': round(base_power + adj, 0),
            })

        # Downsample profiles
        step = max(1, len(s_grid) // 200)

        # Build response
        response = {
            "success": True,
            "optimization": {
                "T_200": round(best_time, 3),
                "best_adjustments": [round(a, 1) for a in best_adjustments],
            },
            "comparison": {
                "baseline_T_200": round(baseline_T_200, 3),
                "optimized_T_200": round(best_time, 3),
                "time_saved_ms": round(improvement_ms, 1),
                "improvement_pct": round(improvement_ms / baseline_T_200 / 10, 2) if baseline_T_200 > 0 else 0,
            },
            "statistics": {
                "samples_tested": optimizer.iteration_count,
                "valid_solutions": optimizer.valid_count,
                "rejected": optimizer.rejected_count,
                "was_stopped": was_stopped,
            },
            "segments": segments_summary,
            "profiles": {
                "distance_m": s_grid[::step].tolist(),
                "baseline_speed_kph": (baseline_result['v'][::step] * 3.6).tolist(),
                "optimized_speed_kph": (best_result['v'][::step] * 3.6).tolist(),
                "baseline_power_W": P_grid[::step].tolist(),
                "optimized_power_W": optimizer.P_optimized[::step].tolist() if hasattr(optimizer, 'P_optimized') else P_grid[::step].tolist(),
            },
        }

        total_elapsed = time_module.time() - start_time
        log(f"SUCCESS: T_200={best_time:.3f}s, total time={total_elapsed:.2f}s")
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


if __name__ == "__main__":
    log("Reading input from stdin...")
    try:
        input_text = sys.stdin.read()
        log(f"Received {len(input_text)} bytes of input")
        input_data = json.loads(input_text)
        log("JSON parsed successfully")
    except json.JSONDecodeError as e:
        log(f"JSON PARSE ERROR: {e}")
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    result = run_redistribution_optimization(input_data)

    log("Writing JSON result to stdout...")
    print(json.dumps(result))
    log("Done.")
