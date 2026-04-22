"""
Greedy Position + Power Optimizer for Flying 200m

Two-phase approach:
  Phase 1 (Seed): Deterministic position analysis using net propulsive force
                   at actual speeds. Finds low-hanging fruit quickly.
  Phase 2 (Local search): Systematic perturbation of position + power per
                          segment, hill-climbing until no single change improves time.

All candidates validated against power curve constraints before simulation.
"""

import sys
import json
import time as time_module
import numpy as np
from scipy.interpolate import interp1d

# Reuse physics and grid-building from existing codebase
import flying200_model as model
from run_energy_optimizer import (
    build_grids_from_profile,
    apply_cda_bend_factor,
    calculate_effort_time,
    build_power_curve_dict,
    get_section_name,
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg):
    print(f"[greedy_optimizer] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Simulation wrapper (same as run_energy_optimizer but self-contained)
# ---------------------------------------------------------------------------

EFFORT_TYPE = 200


def simulate(y_grid, CdA_grid, P_grid, params, s_grid):
    """Run simulation through flying200_model."""
    model.MASS = params.get('mass', 92.0)
    model.RHO = params.get('rho', 1.1627)
    model.C_RR = params.get('crr', 0.002)
    model.CP = params.get('CP', 250.0)
    model.W_PRIME_TOTAL = params.get('W_PRIME_TOTAL', 25000.0)
    model.V0 = params.get('V0', 5.0)
    model.MIN_V = params.get('MIN_V', 0.1)
    model.DRIVETRAIN_EFF = params.get('drivetrain_eff', 0.98)

    result = model.simulate_profile(
        y_grid=y_grid,
        CdA_grid=CdA_grid,
        P_grid=P_grid,
        label="greedy"
    )

    if EFFORT_TYPE != 200:
        result['T_200'] = calculate_effort_time(result, EFFORT_TYPE)

    return result


# ---------------------------------------------------------------------------
# Power curve helpers
# ---------------------------------------------------------------------------

def make_interpolator(curve_dict):
    if not curve_dict:
        return None
    durations = sorted(curve_dict.keys())
    powers = [curve_dict[d] for d in durations]
    return interp1d(durations, powers, kind='linear',
                    fill_value=(powers[0], powers[-1]),
                    bounds_error=False)


def get_max_power(interp, elapsed_s):
    if interp is None:
        return 1500.0
    return float(interp(max(1.0, elapsed_s)))


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------

def build_segments(opt_start_m, timed_start_m, segment_length_m):
    """Build list of optimisation segments (opt zone only, pre-timed)."""
    segments = []
    s = opt_start_m
    seg_idx = 0
    while s < timed_start_m:
        seg_end = min(s + segment_length_m, timed_start_m)
        segments.append({
            'start_m': s,
            'end_m': seg_end,
            'length_m': seg_end - s,
            'name': f"seg_{seg_idx}",
        })
        s = seg_end
        seg_idx += 1
    return segments


# ---------------------------------------------------------------------------
# Phase 1a – Standing cutoff
# ---------------------------------------------------------------------------

def compute_standing_cutoff(seated_interp, standing_interp, params,
                            cda_seated, cda_standing):
    """Find elapsed time after which standing never helps."""
    rho = params.get('rho', 1.1627)
    drivetrain_eff = params.get('drivetrain_eff', 0.98)
    delta_cda = cda_standing - cda_seated
    if delta_cda <= 0:
        return None  # standing is not worse aero – no cutoff

    v_min = 11.0  # most favourable speed for standing

    for t_10 in range(10, 600):  # 1.0s to 60.0s in 0.1s steps
        t = t_10 / 10.0
        p_stand = get_max_power(standing_interp, t)
        p_seat = get_max_power(seated_interp, t)
        delta_P = p_stand - p_seat
        if delta_P <= 0:
            return t  # no power advantage → never stand

        extra_thrust = delta_P * drivetrain_eff / v_min
        extra_drag = 0.5 * rho * delta_cda * v_min ** 2
        if extra_drag >= extra_thrust:
            return t

    return None  # standing could help for entire effort


# ---------------------------------------------------------------------------
# Phase 1b – Per-segment F_net analysis
# ---------------------------------------------------------------------------

def analyze_segments_fnet(segments, s_grid, P_base_grid,
                          CdA_profile_grid, CdA_seated_grid, CdA_standing_grid,
                          baseline_result, params,
                          seated_interp, standing_interp,
                          T_cutoff):
    """For each segment compute F_net standing vs seated.  Returns list of dicts."""
    rho = params.get('rho', 1.1627)
    crr = params.get('crr', 0.002)
    mass = params.get('mass', 92.0)
    g = 9.81
    drivetrain_eff = params.get('drivetrain_eff', 0.98)

    v_arr = baseline_result['v']
    opt_start_m = segments[0]['start_m']

    # Estimate elapsed time at each segment midpoint
    avg_speed = 16.0  # rough
    elapsed = 0.0

    diagnostics = []

    for seg in segments:
        seg_mask = (s_grid >= seg['start_m']) & (s_grid < seg['end_m'])
        mid = (seg['start_m'] + seg['end_m']) / 2.0
        v_seg = float(np.interp(mid, s_grid, v_arr))
        if v_seg < 1.0:
            v_seg = 12.0

        seg_duration = seg['length_m'] / v_seg
        elapsed += seg_duration

        # Current position from profile CdA
        cda_prof = float(CdA_profile_grid[seg_mask].mean()) if seg_mask.any() else float(CdA_seated_grid[0])
        cda_seat = float(CdA_seated_grid[seg_mask].mean()) if seg_mask.any() else float(CdA_seated_grid[0])
        cda_stand = float(CdA_standing_grid[seg_mask].mean()) if seg_mask.any() else float(CdA_standing_grid[0])
        current_pos = 'standing' if cda_prof > cda_seat * 1.01 else 'seated'

        P_baseline = float(P_base_grid[seg_mask].mean()) if seg_mask.any() else 0.0

        # Power available at each position (capped by curve at elapsed time)
        ceil_seat = get_max_power(seated_interp, elapsed)
        ceil_stand = get_max_power(standing_interp, elapsed)
        P_seat = min(P_baseline, ceil_seat)
        P_stand = min(P_baseline, ceil_stand)

        # Net propulsive force
        F_net_stand = (P_stand * drivetrain_eff / v_seg) - 0.5 * rho * cda_stand * v_seg ** 2 - crr * mass * g
        F_net_seat = (P_seat * drivetrain_eff / v_seg) - 0.5 * rho * cda_seat * v_seg ** 2 - crr * mass * g

        # Recommendation
        if T_cutoff is not None and elapsed > T_cutoff:
            recommended = 'seated'
        elif F_net_seat >= F_net_stand:
            recommended = 'seated'
        else:
            recommended = 'standing'

        flip = recommended != current_pos

        diagnostics.append({
            'segment': f"{int(seg['start_m'])}-{int(seg['end_m'])}m",
            'start_m': seg['start_m'],
            'end_m': seg['end_m'],
            'v_kph': round(v_seg * 3.6, 1),
            'elapsed_s': round(elapsed, 2),
            'current_position': current_pos,
            'P_baseline': round(P_baseline, 0),
            'P_standing': round(P_stand, 0),
            'P_seated': round(P_seat, 0),
            'cda_standing': round(cda_stand, 4),
            'cda_seated': round(cda_seat, 4),
            'F_net_standing': round(F_net_stand, 1),
            'F_net_seated': round(F_net_seat, 1),
            'recommended': recommended,
            'flip': flip,
        })

    return diagnostics


# ---------------------------------------------------------------------------
# Phase 1c – Seed position sweep
# ---------------------------------------------------------------------------

def seed_position_sweep(segments, seg_diags, s_grid, y_grid,
                        P_base_grid, CdA_profile_grid,
                        CdA_seated_grid, CdA_standing_grid,
                        params, baseline_T):
    """Test position-only flips with baseline power.  Returns best (positions, CdA_grid, T, result)."""
    n = len(segments)
    best_T = baseline_T
    best_positions = [d['current_position'] for d in seg_diags]
    best_cda = CdA_profile_grid.copy()
    best_result = None
    tests_run = 0

    def _try(positions, label):
        nonlocal best_T, best_positions, best_cda, best_result, tests_run
        tests_run += 1
        cda = CdA_profile_grid.copy()
        for i, seg in enumerate(segments):
            mask = (s_grid >= seg['start_m']) & (s_grid < seg['end_m'])
            if positions[i] == 'standing':
                cda[mask] = CdA_standing_grid[mask]
            else:
                cda[mask] = CdA_seated_grid[mask]
        try:
            res = simulate(y_grid, cda, P_base_grid, params, s_grid)
            t = res.get('T_200', float('inf'))
            if t < best_T:
                best_T = t
                best_positions = list(positions)
                best_cda = cda.copy()
                best_result = res
                log(f"  Seed [{label}] NEW BEST: {t:.3f}s (Δ={round((baseline_T - t)*1000, 1)}ms)")
            return t
        except Exception as e:
            log(f"  Seed [{label}] ERROR: {e}")
            return float('inf')

    current_positions = [d['current_position'] for d in seg_diags]
    recommended_positions = [d['recommended'] for d in seg_diags]

    # 1. All-seated
    _try(['seated'] * n, 'all_seated')

    # 2. All F_net-recommended
    if recommended_positions != current_positions:
        _try(recommended_positions, 'all_recommended')

    # 3. Individual flips
    for i in range(n):
        if seg_diags[i]['flip']:
            pos = list(current_positions)
            pos[i] = seg_diags[i]['recommended']
            _try(pos, f"flip_{int(segments[i]['start_m'])}")

    # 4. Progressive accumulation (sort by abs F_net improvement)
    flip_indices = [i for i in range(n) if seg_diags[i]['flip']]
    if len(flip_indices) > 1:
        flip_indices_sorted = sorted(
            flip_indices,
            key=lambda i: abs(seg_diags[i]['F_net_seated'] - seg_diags[i]['F_net_standing']),
            reverse=True
        )
        pos = list(current_positions)
        for k, idx in enumerate(flip_indices_sorted):
            pos[idx] = seg_diags[idx]['recommended']
            if k > 0:  # k=0 is just a single flip, already tested
                _try(list(pos), f"progressive_{k+1}")

    # 5. Inverse progressive (start from all-recommended, un-flip one at a time)
    if len(flip_indices) > 2:
        for idx in flip_indices_sorted:
            pos = list(recommended_positions)
            pos[idx] = current_positions[idx]  # revert this one
            _try(pos, f"inv_progressive_{int(segments[idx]['start_m'])}")

    # 6. All-standing within cutoff region
    all_stand = [d['recommended'] if d['recommended'] == 'standing' else 'standing'
                 for d in seg_diags]
    # Only test if cutoff allows some standing
    has_cutoff_standing = any(
        d['elapsed_s'] <= (seg_diags[0].get('elapsed_s', 0) + 20)
        for d in seg_diags
    )
    if has_cutoff_standing:
        _try(all_stand, 'all_standing_cutoff')

    log(f"  Seed: {tests_run} tests, best={best_T:.3f}s")
    return best_positions, best_cda, best_T, best_result, tests_run


# ---------------------------------------------------------------------------
# Phase 2 – Local search
# ---------------------------------------------------------------------------

def validate_power_curve(seg_powers, seg_positions, seg_durations,
                         seated_interp, standing_interp, buffer=1.02):
    """Check power curve constraints.  Returns True if valid.

    Two constraints enforced:
      1. Per-segment instantaneous cap: a segment's power cannot exceed the
         power curve ceiling at the *segment's own duration*.  E.g. a ~3s
         segment is capped at the 3-second max, not the elapsed-time max.
         Banking headroom from earlier segments preserves energy (handled
         by the cumulative check) but does NOT raise the instantaneous cap.
      2. Cumulative running-average: total energy / elapsed time must stay
         within the curve ceiling at the current elapsed time.  This is
         what allows banked headroom to be spent — the rider can sustain
         power closer to max for longer, but never above the instantaneous
         cap for the segment duration.
    """
    cumulative_energy = 0.0
    elapsed = 0.0
    for i in range(len(seg_powers)):
        elapsed += seg_durations[i]
        cumulative_energy += seg_powers[i] * seg_durations[i]
        if elapsed <= 0:
            continue
        interp = standing_interp if seg_positions[i] == 'standing' else seated_interp

        # 1. Per-segment instantaneous power cap (based on segment duration)
        seg_ceiling = get_max_power(interp, seg_durations[i])
        if seg_powers[i] > seg_ceiling * buffer:
            return False

        # 2. Cumulative running-average constraint (based on elapsed time)
        elapsed_ceiling = get_max_power(interp, elapsed)
        running_avg = cumulative_energy / elapsed
        if running_avg > elapsed_ceiling * buffer:
            return False
    return True


def local_search(segments, s_grid, y_grid, P_base_grid,
                 CdA_seated_grid, CdA_standing_grid,
                 params, seated_interp, standing_interp,
                 seed_positions, seed_T, seed_result,
                 baseline_result, T_cutoff,
                 min_power_pct, wall_limit_s=18.0):
    """Iteratively perturb position + power per segment to minimise time."""
    wall_start = time_module.monotonic()
    n = len(segments)

    # Current state: per-segment power and position
    # Start from baseline power (what the rider actually did)
    seg_powers = []
    seg_durations = []
    v_arr = (seed_result or baseline_result)['v']
    for seg in segments:
        mask = (s_grid >= seg['start_m']) & (s_grid < seg['end_m'])
        seg_powers.append(float(P_base_grid[mask].mean()) if mask.any() else 0.0)
        mid = (seg['start_m'] + seg['end_m']) / 2.0
        v = float(np.interp(mid, s_grid, v_arr))
        seg_durations.append(seg['length_m'] / max(v, 1.0))

    current_positions = list(seed_positions)
    current_T = seed_T
    current_result = seed_result
    total_energy = sum(p * d for p, d in zip(seg_powers, seg_durations))

    sims_run = 0
    improvements = 0
    skipped_constraint = 0

    # Compute per-segment power floors and ceilings
    # Ceiling = power curve at the segment's own duration (instantaneous cap)
    def get_floors_ceilings(positions):
        floors = []
        ceilings = []
        for i, seg in enumerate(segments):
            floor_p = P_base_grid[
                (s_grid >= seg['start_m']) & (s_grid < seg['end_m'])
            ].mean() * min_power_pct if min_power_pct > 0 else 0.0
            interp = standing_interp if positions[i] == 'standing' else seated_interp
            ceil_p = get_max_power(interp, seg_durations[i])
            floors.append(float(floor_p))
            ceilings.append(float(ceil_p))
        return floors, ceilings

    def build_and_simulate(positions, powers):
        """Build grids from per-segment positions + powers, simulate."""
        P_grid = P_base_grid.copy()
        CdA_grid = CdA_seated_grid.copy()  # default
        for i, seg in enumerate(segments):
            mask = (s_grid >= seg['start_m']) & (s_grid < seg['end_m'])
            P_grid[mask] = powers[i]
            if positions[i] == 'standing':
                CdA_grid[mask] = CdA_standing_grid[mask]
            else:
                CdA_grid[mask] = CdA_seated_grid[mask]
        return simulate(y_grid, CdA_grid, P_grid, params, s_grid)

    # Power deltas to try (coarse first, then fine)
    deltas = [100, 50, 25, 10, -10, -25, -50, -100]

    log(f"  Local search: {n} segments, energy={total_energy:.0f}J, seed_T={seed_T:.3f}s")

    # Log floors/ceilings vs baseline for diagnostics
    _dbg_floors, _dbg_ceilings = get_floors_ceilings(current_positions)
    for i in range(n):
        log(f"    seg {i}: P={seg_powers[i]:.0f}W  floor={_dbg_floors[i]:.0f}  "
            f"ceil={_dbg_ceilings[i]:.0f}  dur={seg_durations[i]:.2f}s  pos={current_positions[i]}")

    improved = True
    iteration = 0
    while improved:
        improved = False
        iteration += 1
        if time_module.monotonic() - wall_start > wall_limit_s:
            log(f"  Wall-clock limit reached ({wall_limit_s}s)")
            break

        for seg_i in range(n):
            if time_module.monotonic() - wall_start > wall_limit_s:
                break

            # Positions to try for this segment
            pos_options = ['seated']
            if T_cutoff is None or sum(seg_durations[:seg_i + 1]) <= T_cutoff:
                pos_options.append('standing')

            for pos in pos_options:
                for delta in deltas:
                    if time_module.monotonic() - wall_start > wall_limit_s:
                        break

                    new_power = seg_powers[seg_i] + delta

                    # Quick bounds check
                    floors, ceilings = get_floors_ceilings(
                        [pos if j == seg_i else current_positions[j] for j in range(n)]
                    )
                    if new_power < floors[seg_i] or new_power > ceilings[seg_i]:
                        continue

                    # Redistribute delta across other segments (proportional to duration)
                    other_total_dur = sum(seg_durations[j] for j in range(n) if j != seg_i)
                    if other_total_dur <= 0:
                        continue
                    energy_shift = delta * seg_durations[seg_i]  # extra Joules in seg_i
                    new_powers = list(seg_powers)
                    new_powers[seg_i] = new_power
                    new_positions = list(current_positions)
                    new_positions[seg_i] = pos

                    # Spread -energy_shift across others proportionally
                    # Enforce both floor and ceiling per segment
                    valid_redistribution = True
                    for j in range(n):
                        if j == seg_i:
                            continue
                        share = (seg_durations[j] / other_total_dur) * energy_shift
                        adj_power = seg_powers[j] - share / seg_durations[j]
                        if adj_power < floors[j] * 0.98 or adj_power > ceilings[j]:
                            valid_redistribution = False
                            break
                        new_powers[j] = adj_power

                    if not valid_redistribution:
                        continue

                    # Validate cumulative power curve
                    if not validate_power_curve(new_powers, new_positions,
                                               seg_durations, seated_interp,
                                               standing_interp):
                        skipped_constraint += 1
                        continue

                    # Simulate
                    try:
                        res = build_and_simulate(new_positions, new_powers)
                        sims_run += 1
                        t = res.get('T_200', float('inf'))
                        if t < current_T:
                            current_T = t
                            seg_powers = new_powers
                            current_positions = new_positions
                            current_result = res
                            improvements += 1
                            improved = True
                            log(f"  Iter {iteration} seg {seg_i} pos={pos} Δ={delta:+d}W → {t:.3f}s "
                                f"(Δ={round((seed_T - t)*1000, 1)}ms from seed)")

                            # Update durations from new speeds
                            v_arr = res['v']
                            for k, seg in enumerate(segments):
                                mid = (seg['start_m'] + seg['end_m']) / 2.0
                                v = float(np.interp(mid, s_grid, v_arr))
                                seg_durations[k] = seg['length_m'] / max(v, 1.0)
                            break  # restart deltas for this segment
                    except Exception:
                        continue

                if improved:
                    break  # restart positions for this segment

    elapsed_s = time_module.monotonic() - wall_start
    log(f"  Local search done: {sims_run} sims, {improvements} improvements, "
        f"{skipped_constraint} skipped (constraint), {elapsed_s:.1f}s wall")

    return current_positions, seg_powers, current_T, current_result, {
        'sims_run': sims_run,
        'improvements': improvements,
        'skipped_constraint': skipped_constraint,
        'iterations': iteration,
        'wall_time_s': round(elapsed_s, 1),
    }


# ---------------------------------------------------------------------------
# Main entry – orchestrate phases, build response
# ---------------------------------------------------------------------------

def run_greedy_optimization(input_data):
    start_time = time_module.time()
    log("=" * 60)
    log("run_greedy_optimization() called")

    try:
        power_curves = input_data.get('power_curves', {})
        profile_data = input_data.get('profile', [])
        rider_params = input_data.get('rider_params', {})
        config = input_data.get('config', {})
        options = input_data.get('options', {})

        # Validate
        if not power_curves.get('seated') or not power_curves.get('standing'):
            return {"success": False, "error": "Missing seated or standing power curve"}
        if not profile_data:
            return {"success": False, "error": "Missing wind-up profile"}

        # Build power curve dicts
        durations_data = power_curves.get('durations', None)
        seated_curve = build_power_curve_dict(power_curves['seated'], durations_data)
        standing_curve = build_power_curve_dict(power_curves['standing'], durations_data)
        seated_interp = make_interpolator(seated_curve)
        standing_interp = make_interpolator(standing_curve)
        log(f"Power curves: seated {sorted(seated_curve.keys())}, standing {sorted(standing_curve.keys())}")

        # Build grids
        s_total = config.get('s_total', 895.0)
        s_grid, y_grid, CdA_profile_grid, CdA_seated_grid, CdA_standing_grid, P_base_grid, theta_grid, params = \
            build_grids_from_profile(profile_data, rider_params, s_total, config.get('ds', 0.25))

        # Apply bend factor
        cda_bend_factor = params.get('cda_bend_factor', 1.0)
        CdA_profile_grid = apply_cda_bend_factor(CdA_profile_grid, s_grid, cda_bend_factor)
        CdA_seated_grid = apply_cda_bend_factor(CdA_seated_grid, s_grid, cda_bend_factor)
        CdA_standing_grid = apply_cda_bend_factor(CdA_standing_grid, s_grid, cda_bend_factor)

        # Config
        opt_start_m = config.get('opt_start_m', 480.0)
        timed_start_m = config.get('timed_start_m', 695.0)
        segment_length_m = config.get('segment_length_m', 50.0)
        min_power_pct = config.get('min_power_pct', 0.8)

        # Effort type
        global EFFORT_TYPE
        effort_type = options.get('effort_type', 200)
        EFFORT_TYPE = effort_type
        log(f"Effort type: F{effort_type}")

        # Build segments
        segments = build_segments(opt_start_m, timed_start_m, segment_length_m)
        log(f"Segments: {len(segments)} from {opt_start_m}m to {timed_start_m}m")

        # Baseline simulation with profile CdA
        log("Running baseline simulation...")
        baseline_result = simulate(y_grid, CdA_profile_grid, P_base_grid, params, s_grid)
        baseline_T = calculate_effort_time(baseline_result, effort_type)
        log(f"Baseline F{effort_type}: {baseline_T:.3f}s")

        # Use frontend-provided baseline if available
        provided_baseline = options.get('baseline_T_200')
        display_baseline = provided_baseline if provided_baseline is not None else baseline_T

        # ----- PHASE 1a: Standing cutoff -----
        cda_seated_val = float(CdA_seated_grid[0])
        cda_standing_val = float(CdA_standing_grid[0])
        T_cutoff = compute_standing_cutoff(
            seated_interp, standing_interp, params,
            cda_seated_val, cda_standing_val
        )
        log(f"Standing cutoff: {T_cutoff:.1f}s" if T_cutoff else "Standing cutoff: None (viable entire effort)")

        # ----- PHASE 1b: F_net analysis -----
        log("Phase 1b: F_net analysis...")
        seg_diags = analyze_segments_fnet(
            segments, s_grid, P_base_grid,
            CdA_profile_grid, CdA_seated_grid, CdA_standing_grid,
            baseline_result, params,
            seated_interp, standing_interp, T_cutoff
        )
        for d in seg_diags:
            log(f"  {d['segment']}: v={d['v_kph']}kph pos={d['current_position']} "
                f"F_net stand={d['F_net_standing']:.0f} seat={d['F_net_seated']:.0f} "
                f"→ {d['recommended']}{' FLIP' if d['flip'] else ''}")

        # ----- PHASE 1c: Seed position sweep -----
        log("Phase 1c: Seed position sweep...")
        seed_positions, seed_cda, seed_T, seed_result, seed_tests = seed_position_sweep(
            segments, seg_diags, s_grid, y_grid,
            P_base_grid, CdA_profile_grid,
            CdA_seated_grid, CdA_standing_grid,
            params, baseline_T
        )
        seed_improved = seed_result is not None
        if not seed_improved:
            seed_T = baseline_T
            seed_result = baseline_result
            seed_positions = [d['current_position'] for d in seg_diags]
        log(f"Seed result: {seed_T:.3f}s ({'improved' if seed_improved else 'no improvement'})")

        # ----- PHASE 2: Local search -----
        log("Phase 2: Local search...")
        final_positions, final_powers, final_T, final_result, search_stats = local_search(
            segments, s_grid, y_grid, P_base_grid,
            CdA_seated_grid, CdA_standing_grid,
            params, seated_interp, standing_interp,
            seed_positions, seed_T, seed_result,
            baseline_result, T_cutoff, min_power_pct,
            wall_limit_s=18.0,
        )
        log(f"Final: {final_T:.3f}s (seed was {seed_T:.3f}s, baseline was {baseline_T:.3f}s)")

        # ----- Check if we actually improved -----
        if final_T >= baseline_T:
            log("No improvement found over baseline")
            return {
                "success": False,
                "error": f"No improvement found over baseline ({baseline_T:.3f}s). "
                         f"Seed tested {seed_tests} positions, local search ran {search_stats['sims_run']} sims.",
                "baseline_T_200": round(baseline_T, 3),
                "greedy_diagnostics": {
                    "T_cutoff_s": round(T_cutoff, 1) if T_cutoff else None,
                    "per_segment": seg_diags,
                    "search_stats": search_stats,
                },
            }

        # ----- PHASE 3: Build response -----
        time_saved_ms = round((baseline_T - final_T) * 1000, 1)
        improvement_pct = round((baseline_T - final_T) / baseline_T * 100, 2) if baseline_T > 0 else 0

        # Build final power and CdA grids for profiles output
        P_final = P_base_grid.copy()
        CdA_final = CdA_seated_grid.copy()
        for i, seg in enumerate(segments):
            mask = (s_grid >= seg['start_m']) & (s_grid < seg['end_m'])
            P_final[mask] = final_powers[i]
            if final_positions[i] == 'standing':
                CdA_final[mask] = CdA_standing_grid[mask]
            else:
                CdA_final[mask] = CdA_seated_grid[mask]

        # Segments summary
        segments_summary = []
        total_energy = sum(final_powers[i] * segments[i]['length_m'] / max(
            float(np.interp((segments[i]['start_m'] + segments[i]['end_m']) / 2, s_grid, final_result['v'])), 1.0
        ) for i in range(len(segments)))

        for i, seg in enumerate(segments):
            mid = (seg['start_m'] + seg['end_m']) / 2.0
            v = float(np.interp(mid, s_grid, final_result['v']))
            seg_dur = seg['length_m'] / max(v, 1.0)
            seg_energy = final_powers[i] * seg_dur
            pct = (seg_energy / total_energy * 100) if total_energy > 0 else 0
            segments_summary.append({
                'start_m': seg['start_m'],
                'end_m': seg['end_m'],
                'name': f"{int(seg['start_m'])}-{int(seg['end_m'])}m",
                'section': get_section_name(mid),
                'energy_pct': round(pct, 1),
                'energy_J': round(seg_energy, 0),
                'position': final_positions[i],
                'power_W': round(final_powers[i], 0),
            })

        # Downsample profiles for web
        step = max(1, len(s_grid) // 400)

        response = {
            "success": True,
            "optimizer_method": "greedy",
            "optimization": {
                "T_200_discrete": round(final_T, 3),
                "T_200_smoothed": round(final_T, 3),  # no smoothing needed – power is continuous
                "smoothing_penalty_ms": 0,
                "best_allocation": [1.0 / len(segments)] * len(segments),  # uniform (not used)
                "best_positions": final_positions,
                "iterations_used": search_stats['iterations'],
            },
            "comparison": {
                "baseline_T_200": round(baseline_T, 3),
                "optimized_T_200": round(final_T, 3),
                "time_saved_ms": time_saved_ms,
                "improvement_pct": improvement_pct,
                "baseline_v_200_entry_kph": round(float(np.interp(timed_start_m, s_grid, baseline_result['v'])) * 3.6, 2),
                "baseline_v_200_exit_kph": round(float(baseline_result['v'][-1]) * 3.6, 2),
                "optimized_v_200_entry_kph": round(float(np.interp(timed_start_m, s_grid, final_result['v'])) * 3.6, 2),
                "optimized_v_200_exit_kph": round(float(final_result['v'][-1]) * 3.6, 2),
                "frontend_baseline_T_200": round(display_baseline, 3) if provided_baseline else None,
            },
            "statistics": {
                "samples_tested": seed_tests + search_stats['sims_run'],
                "valid_combinations": search_stats['improvements'] + (1 if seed_improved else 0),
                "rejected_violations": search_stats['skipped_constraint'],
                "was_stopped": False,
            },
            "profiles": {
                "distance_m": s_grid[::step].tolist(),
                "baseline_speed_kph": (baseline_result['v'][::step] * 3.6).tolist(),
                "optimized_speed_kph": (final_result['v'][::step] * 3.6).tolist(),
                "baseline_power_W": P_base_grid[::step].tolist(),
                "P_discrete": P_final[::step].tolist(),
                "P_smooth": P_final[::step].tolist(),
                "CdA": CdA_final[::step].tolist(),
                "baseline_CdA": CdA_seated_grid[::step].tolist(),
            },
            "markers": {
                "timed_start_m": timed_start_m,
                "timed_end_m": s_total,
                "opt_start_m": opt_start_m,
            },
            "segments": segments_summary,
            "greedy_diagnostics": {
                "T_cutoff_s": round(T_cutoff, 1) if T_cutoff else None,
                "per_segment": seg_diags,
                "seed_tests": seed_tests,
                "seed_improved": seed_improved,
                "seed_T": round(seed_T, 3),
                "search_stats": search_stats,
            },
        }

        total_elapsed = time_module.time() - start_time
        log(f"SUCCESS: {final_T:.3f}s, saved {time_saved_ms}ms, wall={total_elapsed:.1f}s")
        log("=" * 60)
        return response

    except Exception as e:
        import traceback
        log(f"EXCEPTION: {e}")
        log(traceback.format_exc())
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


# ---------------------------------------------------------------------------
# stdin/stdout interface
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log("Reading input from stdin...")
    try:
        input_text = sys.stdin.read()
        log(f"Received {len(input_text)} bytes")
        input_data = json.loads(input_text)
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    result = run_greedy_optimization(input_data)
    print(json.dumps(result))
