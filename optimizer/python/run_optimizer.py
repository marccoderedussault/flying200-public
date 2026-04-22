"""
Flying 200 Optimizer Web API Wrapper

Accepts JSON input with power curves, profile, and rider parameters.
Returns optimal position pattern and performance metrics.
"""

import sys
import os
import json
import numpy as np
import pandas as pd

from sprint_optimizer import SprintOptimizer, OptimizerConfig, PowerCurve


def create_power_curve(curve_data: list, durations_data: list = None, max_duration: int = 60) -> PowerCurve:
    """
    Create a PowerCurve object from JSON data.

    Args:
        curve_data: List of {duration_s, power_W} or just power values
        durations_data: Optional list of durations (e.g., [1, 2, 3, 5, 10, 15, 20, 30, 40, 60])
        max_duration: Maximum duration to include (default 60s)

    Returns:
        PowerCurve object
    """
    if not curve_data:
        raise ValueError("Empty power curve data")

    # Handle different input formats
    if isinstance(curve_data[0], dict):
        # Format: [{duration_s: 1, power_W: 1400}, ...]
        durations = [p['duration_s'] for p in curve_data if p['duration_s'] <= max_duration]
        powers = [p['power_W'] for p in curve_data if p['duration_s'] <= max_duration]
    elif isinstance(curve_data[0], (int, float)):
        # Format: [1400, 1350, 1300, ...] with explicit durations provided
        if durations_data is not None:
            # Use explicit durations (e.g., [1, 2, 3, 5, 10, 15, 20, 30, 40, 60])
            durations = [d for d in durations_data if d <= max_duration]
            powers = [curve_data[i] for i, d in enumerate(durations_data) if d <= max_duration]
        else:
            # Legacy fallback: assume contiguous (1s, 2s, 3s, ...)
            durations = list(range(1, min(len(curve_data) + 1, max_duration + 1)))
            powers = curve_data[:max_duration]
    else:
        raise ValueError(f"Unknown power curve format: {type(curve_data[0])}")

    return PowerCurve(durations=durations, powers=powers)


def create_windup_profile(profile_data: list) -> pd.DataFrame:
    """
    Create wind-up profile DataFrame from JSON data.

    Args:
        profile_data: List of {s_m, y_m, CdA_m2, P_W}

    Returns:
        DataFrame with wind-up profile
    """
    if not profile_data:
        raise ValueError("Empty profile data")

    df = pd.DataFrame(profile_data)

    # Ensure required columns exist
    required = ['s_m', 'y_m', 'CdA_m2', 'P_W']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    return df[required].sort_values('s_m').reset_index(drop=True)


def log(msg):
    """Log to stderr for debugging (visible in server logs)"""
    print(f"[run_optimizer] {msg}", file=sys.stderr, flush=True)


def run_optimization(input_data: dict) -> dict:
    """
    Run the Flying 200 optimizer.

    Args:
        input_data: Dictionary with:
            - power_curves: {seated: [...], standing: [...]}
            - profile: [{s_m, y_m, CdA_m2, P_W}, ...]
            - rider_params: {mass, rho, crr, cda_seated, cda_standing}
            - config: {sprint_start, s_total, ...} (optional)
            - options: {use_smart_patterns, sample_size, verbose} (optional)

    Returns:
        Dictionary with optimization results
    """
    try:
        log("=" * 50)
        log("Starting optimization...")

        # Extract power curves
        power_curves = input_data.get('power_curves', {})
        durations_data = power_curves.get('durations', None)
        seated_data = power_curves.get('seated', [])
        standing_data = power_curves.get('standing', [])

        log(f"Power curve durations: {durations_data}")
        log(f"Seated data length: {len(seated_data) if seated_data else 0}")
        log(f"Standing data length: {len(standing_data) if standing_data else 0}")

        if not seated_data or not standing_data:
            log("ERROR: Missing seated or standing power curve")
            return {"success": False, "error": "Missing seated or standing power curve"}

        seated_curve = create_power_curve(seated_data, durations_data)
        standing_curve = create_power_curve(standing_data, durations_data)

        log(f"Created seated curve: {len(seated_curve.durations)} points, powers: {seated_curve.powers[:5]}...")
        log(f"Created standing curve: {len(standing_curve.durations)} points, powers: {standing_curve.powers[:5]}...")

        # Extract profile
        profile_data = input_data.get('profile', [])
        log(f"Profile data: {len(profile_data)} points")
        if not profile_data:
            log("ERROR: Missing wind-up profile")
            return {"success": False, "error": "Missing wind-up profile"}

        windup_profile = create_windup_profile(profile_data)
        log(f"Windup profile: {len(windup_profile)} rows, s_m range: {windup_profile['s_m'].min()}-{windup_profile['s_m'].max()}")
        log(f"Windup profile P_W range: {windup_profile['P_W'].min()}-{windup_profile['P_W'].max()}")

        # Extract rider parameters
        rider = input_data.get('rider_params', {})
        config_overrides = input_data.get('config', {})

        log(f"Rider params: mass={rider.get('mass')}, cda_seated={rider.get('cda_seated')}, cda_standing={rider.get('cda_standing')}")

        # Build optimizer config
        config = OptimizerConfig(
            mass=rider.get('mass', 92.0),
            rho=rider.get('rho', 1.18),
            c_rr=rider.get('crr', 0.002),
            cda_seated=rider.get('cda_seated', 0.24),
            cda_standing=rider.get('cda_standing', 0.38),
            sprint_start_s=config_overrides.get('sprint_start', 460.0),
            s_total=config_overrides.get('s_total', 895.0),
            ds=config_overrides.get('ds', 0.25),
            min_position_hold_s=config_overrides.get('min_hold_s', 3.0),
            seated_zone_before_finish=config_overrides.get('seated_zone', 230.0),
            min_power_pct=config_overrides.get('min_power_pct', 0.9),  # 90% of baseline floor
        )
        log(f"Config: sprint_start_s={config.sprint_start_s}, s_total={config.s_total}")

        # Create optimizer
        log("Creating SprintOptimizer...")
        optimizer = SprintOptimizer(
            config=config,
            seated_power_curve=seated_curve,
            standing_power_curve=standing_curve,
            windup_profile=windup_profile
        )
        log("SprintOptimizer created successfully")

        # Run optimization
        options = input_data.get('options', {})
        use_smart = options.get('use_smart_patterns', True)
        sample_size = options.get('sample_size', None)
        sprint_duration = options.get('sprint_duration', 30)
        stream_progress = options.get('stream_progress', False)

        log(f"Options: use_smart={use_smart}, sample_size={sample_size}, sprint_duration={sprint_duration}")

        # Progress callback for streaming
        def progress_callback(current, total, best_time, pattern_desc):
            if stream_progress:
                progress_msg = json.dumps({
                    "type": "progress",
                    "current": current,
                    "total": total,
                    "best_time": round(best_time, 3) if best_time else None,
                    "pattern": pattern_desc[:50] if pattern_desc else None
                })
                print(progress_msg, flush=True)
                sys.stdout.flush()

        log("Starting optimizer.optimize()...")
        import time
        start_time = time.time()

        result = optimizer.optimize(
            use_smart_patterns=use_smart,
            sprint_duration_s=sprint_duration,
            power_strategy='power_curve',  # Use power curves to determine available power at each position
            sample_size=sample_size,
            verbose=False,
            progress_callback=progress_callback if stream_progress else None
        )

        elapsed = time.time() - start_time
        log(f"optimizer.optimize() completed in {elapsed:.2f}s")

        # Check for valid result
        if result is None:
            log("ERROR: Optimizer returned None")
            return {"success": False, "error": "Optimizer returned no result"}

        log(f"Result keys: {list(result.keys())}")
        log(f"num_patterns: {result.get('num_patterns', 'N/A')}")
        log(f"elapsed_time: {result.get('elapsed_time', 'N/A')}")

        if 'best_result' not in result:
            log(f"ERROR: No best_result in result")
            return {
                "success": False,
                "error": f"No best_result in optimizer output. Keys: {list(result.keys()) if isinstance(result, dict) else 'not a dict'}"
            }

        # Extract best result
        best = result['best_result']

        if best is None:
            log("ERROR: best_result is None - no valid patterns found")
            log(f"This usually means all patterns violated power constraints")
            return {"success": False, "error": "best_result is None - no valid patterns found (power constraints too strict?)"}

        log(f"Best result T_200: {best.get('T_200', 'N/A')}")

        # Calculate 50m splits
        s_grid = optimizer.s_grid
        t_array = best['t']
        v_array = best['v']

        s_200_start = config.s_total - 200.0
        splits = []
        for i in range(4):
            s_start = s_200_start + i * 50
            s_end = s_start + 50
            t_start = np.interp(s_start, s_grid, t_array)
            t_end = np.interp(s_end, s_grid, t_array)
            splits.append({
                'segment': f'{i*50}-{(i+1)*50}m',
                'time_s': round(t_end - t_start, 3),
                'avg_speed_kph': round(50 / (t_end - t_start) * 3.6, 1)
            })

        # Build response
        response = {
            "success": True,
            "optimization": {
                "T_200": round(best['T_200'], 3),
                "T_sprint": round(best['T_sprint'], 3),
                "v_200_entry_kph": round(best['v_200_entry'] * 3.6, 2),
                "v_200_exit_kph": round(best['v_200_exit'] * 3.6, 2),
                "pattern_description": best['pattern_description'],
                "splits": splits,
                "energy": {
                    "standing_kJ": round(best['sprint_energy_standing'] / 1000, 2),
                    "seated_kJ": round(best['sprint_energy_seated'] / 1000, 2),
                }
            },
            "metadata": {
                "patterns_tested": result['num_patterns'],
                "elapsed_s": round(result['elapsed_time'], 2),
            }
        }

        # Add speed/power profiles (downsampled for web)
        step = max(1, len(s_grid) // 200)  # Max 200 points
        response["profiles"] = {
            "distance_m": s_grid[::step].tolist(),
            "speed_kph": (v_array[::step] * 3.6).tolist(),
            "power_W": best['p_actual'][::step].tolist(),
            "cda_m2": best['cda_actual'][::step].tolist(),
            "is_standing": best['is_standing'][::step].tolist(),
        }

        # Add position timeline
        is_standing = best['is_standing']
        timeline = []
        current_state = None
        state_start_s = 0

        for i, standing in enumerate(is_standing):
            t_i = t_array[i]
            if standing != current_state:
                if current_state is not None:
                    timeline.append({
                        'position': 'standing' if current_state else 'seated',
                        'start_s': round(state_start_s, 2),
                        'end_s': round(t_i, 2),
                        'duration_s': round(t_i - state_start_s, 2)
                    })
                current_state = standing
                state_start_s = t_i

        # Add final segment
        if current_state is not None:
            timeline.append({
                'position': 'standing' if current_state else 'seated',
                'start_s': round(state_start_s, 2),
                'end_s': round(t_array[-1], 2),
                'duration_s': round(t_array[-1] - state_start_s, 2)
            })

        response["position_timeline"] = timeline

        # Add validation info
        response["validation"] = {
            "is_valid": best.get('is_valid', True),
            "violations": [
                {
                    "time_s": round(v[0], 2),
                    "power_W": round(v[1], 0),
                    "limit_W": round(v[2], 0),
                    "excess_W": round(v[3], 0),
                    "type": v[4] if len(v) > 4 else 'unknown'
                }
                for v in best.get('violations', [])
            ] if best.get('violations') else []
        }

        log(f"SUCCESS: T_200={response['optimization']['T_200']}")
        log("=" * 50)
        return response

    except Exception as e:
        import traceback
        log(f"EXCEPTION: {e}")
        log(traceback.format_exc())
        log("=" * 50)
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def run_baseline_comparison(input_data: dict) -> dict:
    """
    Run optimizer and compare against all-seated baseline.
    """
    try:
        # Run optimization
        opt_result = run_optimization(input_data)

        if not opt_result.get('success'):
            return opt_result

        # Run baseline (all seated) simulation
        # Modify input to force all-seated pattern
        baseline_input = input_data.copy()
        baseline_input['options'] = baseline_input.get('options', {}).copy()
        baseline_input['options']['force_all_seated'] = True

        # For baseline, we use the same optimizer but with a single all-seated pattern
        power_curves = input_data.get('power_curves', {})
        durations_data = power_curves.get('durations', None)
        seated_data = power_curves.get('seated', [])
        standing_data = power_curves.get('standing', [])

        seated_curve = create_power_curve(seated_data, durations_data)
        standing_curve = create_power_curve(standing_data, durations_data)

        profile_data = input_data.get('profile', [])
        windup_profile = create_windup_profile(profile_data)

        rider = input_data.get('rider_params', {})
        config_overrides = input_data.get('config', {})

        config = OptimizerConfig(
            mass=rider.get('mass', 92.0),
            rho=rider.get('rho', 1.18),
            c_rr=rider.get('crr', 0.002),
            cda_seated=rider.get('cda_seated', 0.24),
            cda_standing=rider.get('cda_standing', 0.38),
            sprint_start_s=config_overrides.get('sprint_start', 460.0),
            s_total=config_overrides.get('s_total', 895.0),
        )

        optimizer = SprintOptimizer(
            config=config,
            seated_power_curve=seated_curve,
            standing_power_curve=standing_curve,
            windup_profile=windup_profile
        )

        # Simulate all-seated baseline
        all_seated_pattern = [False] * 30  # 30 seconds all seated
        baseline_result = optimizer._simulate_sprint(all_seated_pattern, power_strategy='power_curve')

        baseline_T_200 = baseline_result['T_200']
        optimized_T_200 = opt_result['optimization']['T_200']
        time_saved = baseline_T_200 - optimized_T_200

        opt_result['comparison'] = {
            'baseline_T_200': round(baseline_T_200, 3),
            'optimized_T_200': round(optimized_T_200, 3),
            'time_saved_s': round(time_saved, 3),
            'improvement_pct': round(time_saved / baseline_T_200 * 100, 2) if baseline_T_200 > 0 else 0
        }

        # Add baseline profiles for charting comparison
        s_grid = optimizer.s_grid
        baseline_v = baseline_result['v']
        baseline_p = baseline_result['p_actual']
        step = max(1, len(s_grid) // 200)  # Max 200 points

        opt_result['baseline_profiles'] = {
            'distance_m': s_grid[::step].tolist(),
            'speed_kph': (baseline_v[::step] * 3.6).tolist(),
            'power_W': baseline_p[::step].tolist(),
        }

        # Also add baseline entry/exit speeds
        s_200_start = config.s_total - 200.0
        v_200_entry_idx = np.argmin(np.abs(s_grid - s_200_start))
        opt_result['comparison']['baseline_v_200_entry_kph'] = round(baseline_v[v_200_entry_idx] * 3.6, 2)
        opt_result['comparison']['baseline_v_200_exit_kph'] = round(baseline_v[-1] * 3.6, 2)

        return opt_result

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


if __name__ == "__main__":
    # Read input from stdin
    try:
        input_text = sys.stdin.read()
        input_data = json.loads(input_text)
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    # Determine action
    action = input_data.get('action', 'optimize')

    if action == 'optimize':
        result = run_optimization(input_data)
    elif action == 'compare':
        result = run_baseline_comparison(input_data)
    else:
        result = {"success": False, "error": f"Unknown action: {action}"}

    # Output result
    print(json.dumps(result))
