import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ============================================
# Flying 200 m model for Bromont / Atlanta 250 m track
# Base vs Modified profile comparison
#
# CSV columns:
#   s_m, y_m, CdA_m2, P_W, [optional] y_m_2, CdA_m2_2, P_W_2, comment
#
# - "base" run: uses y_m, CdA_m2, P_W
# - "mod" run:  uses y_m_2 / CdA_m2_2 / P_W_2 where non-NaN, otherwise base
# ============================================

# -------------------------
# User-tunable parameters
# -------------------------

PROFILE_CSV = "profile_f200.csv"   # input profile
POWER_CURVE_CSV = "power_curve_template.csv"  # power-duration curves

S_TOTAL = 895.0                    # [m] total effort along black line
S_200_START = S_TOTAL - 200.0      # [m] start of timed 200

DS = 0.25                           # [m] step in black-line distance

MASS = 92.0                        # [kg] rider + bike
RHO = 1.1627                       # [kg/m^3] air density
C_RR = 0.0020                      # rolling resistance
G = 9.81                           # [m/s^2]

CP = 250.0                         # [W] critical power
W_PRIME_TOTAL = 25000.0            # [J] W'
V0 = 5.0                           # [m/s] initial speed
MIN_V = 0.1                        # [m/s] min speed to avoid div-by-zero
SPRINT_DELTA_OVER_CP = 250.0       # [W] power above CP to detect sprint start
DRIVETRAIN_EFF = 0.98              # drivetrain efficiency (1.0 = 100%, 0.98 = 98%)

# -------------------------
# Track geometry — defaults are Bromont/Atlanta 250m
# These globals are recomputed per-request via apply_track_geometry()
# -------------------------

LAP_LEN = 250.0                    # [m] lap on black line
L_STRAIGHT = 59.0                  # [m] straight length
R_BEND = (LAP_LEN - 2.0 * L_STRAIGHT) / (2.0 * np.pi)   # ≈ 21.1 m
ARC_LEN = np.pi * R_BEND           # [m] bend half-circle

THETA_STRAIGHT_DEG = 12.0
THETA_BEND_DEG = 42.0
THETA_STRAIGHT = np.deg2rad(THETA_STRAIGHT_DEG)
THETA_BEND = np.deg2rad(THETA_BEND_DEG)

TRANS_LEN = ARC_LEN / 2            # [m] banking transition = half the bend (full quarter-circle)

# s=0 at back-straight pursuit line (mid back straight)
S_OFFSET = (L_STRAIGHT            # home straight
            + ARC_LEN             # bend1
            + 0.5 * L_STRAIGHT)   # half of back straight)


def apply_track_geometry(straight_m=59.0, banking_turn_deg=42.0, banking_straight_deg=12.0,
                         lap_m=250.0, s_total_m=None):
    """Recompute all track geometry globals for a given track.

    Called per-request before simulate_profile(). Mutates module globals so
    that theta_track_blackline(), in_bend_region(), classify_section_and_quarter(),
    and simulate_profile() all use the correct track.

    Args:
        straight_m: Length of each straight [m]
        banking_turn_deg: Banking angle in turns [deg]
        banking_straight_deg: Banking angle on straights [deg]
        lap_m: Lap length on black line [m] (250 standard, 333/400 for outdoor)
        s_total_m: Total effort distance [m]. Default = None → keep current S_TOTAL.
    """
    global LAP_LEN, L_STRAIGHT, R_BEND, ARC_LEN, TRANS_LEN
    global THETA_STRAIGHT_DEG, THETA_BEND_DEG, THETA_STRAIGHT, THETA_BEND
    global S_OFFSET, S_TOTAL, S_200_START
    global s_grid, theta_grid, lap_idx_arr, section_arr, quarter_arr

    # Track shape
    LAP_LEN = lap_m
    L_STRAIGHT = straight_m
    R_BEND = (LAP_LEN - 2.0 * L_STRAIGHT) / (2.0 * np.pi)
    ARC_LEN = np.pi * R_BEND
    TRANS_LEN = ARC_LEN / 2.0

    # Banking angles
    THETA_STRAIGHT_DEG = banking_straight_deg
    THETA_BEND_DEG = banking_turn_deg
    THETA_STRAIGHT = np.deg2rad(THETA_STRAIGHT_DEG)
    THETA_BEND = np.deg2rad(THETA_BEND_DEG)

    # S_OFFSET: s_eff=0 is at mid-back-straight pursuit line
    S_OFFSET = L_STRAIGHT + ARC_LEN + 0.5 * L_STRAIGHT

    # Total distance (allow override for non-standard track sizes)
    if s_total_m is not None:
        S_TOTAL = s_total_m
    S_200_START = S_TOTAL - 200.0

    # Rebuild simulation grid
    s_grid = np.arange(0.0, S_TOTAL + DS, DS)
    theta_grid = np.array([theta_track_blackline(s + S_OFFSET) for s in s_grid])

    # Rebuild section classification arrays
    _lap_idx = []
    _section = []
    _quarter = []
    for s in s_grid:
        lap_idx_val, sec, q = classify_section_and_quarter(s)
        _lap_idx.append(lap_idx_val)
        _section.append(sec)
        _quarter.append(q)
    lap_idx_arr = np.array(_lap_idx)
    section_arr = np.array(_section)
    quarter_arr = np.array(_quarter)


def theta_bend_with_transition(s_in_bend: float) -> float:
    """Banking angle in a bend, including entry/exit transitions."""
    if TRANS_LEN > 0.0:
        if s_in_bend < TRANS_LEN:
            f = s_in_bend / TRANS_LEN
            return THETA_STRAIGHT + f * (THETA_BEND - THETA_STRAIGHT)
        elif s_in_bend > ARC_LEN - TRANS_LEN:
            f = (ARC_LEN - s_in_bend) / TRANS_LEN
            return THETA_STRAIGHT + f * (THETA_BEND - THETA_STRAIGHT)
        else:
            return THETA_BEND
    else:
        return THETA_BEND


def theta_track_blackline(s_global: float) -> float:
    """Banking angle theta(s_global) [rad] at global black-line distance.

    Banking transitions from 12 deg at bend entry/exit to 42 deg at the apex.
    Uses the original transition model based on distance traveled into the bend.
    """
    s_mod = s_global % LAP_LEN

    # [0, L_STRAIGHT) : HomeStraight
    # [L_STRAIGHT, L_STRAIGHT+ARC_LEN) : Bend1/Right curve (Turn1/Turn2)
    # [L_STRAIGHT+ARC_LEN, L_STRAIGHT+ARC_LEN+L_STRAIGHT) : BackStraight
    # [..] : Bend2/Left curve (Turn3/Turn4)
    if s_mod < L_STRAIGHT:
        return THETA_STRAIGHT
    elif s_mod < L_STRAIGHT + ARC_LEN:
        s_in_bend = s_mod - L_STRAIGHT
        return theta_bend_with_transition(s_in_bend)
    elif s_mod < L_STRAIGHT + ARC_LEN + L_STRAIGHT:
        return THETA_STRAIGHT
    else:
        s_in_bend = s_mod - (L_STRAIGHT + ARC_LEN + L_STRAIGHT)
        return theta_bend_with_transition(s_in_bend)


def in_bend_region(s_global: float) -> bool:
    """True if s_global lies in a bend region."""
    s_mod = s_global % LAP_LEN
    if s_mod < L_STRAIGHT:
        return False
    elif s_mod < L_STRAIGHT + ARC_LEN:
        return True
    elif s_mod < L_STRAIGHT + ARC_LEN + L_STRAIGHT:
        return False
    else:
        return True


def classify_section_and_quarter(s_eff: float):
    """
    Return (lap_idx, section_name, quarter_index) for effort distance s_eff,
    where s_eff=0 at back-straight pursuit line.

    Sections (your nomenclature):
      - BackStraight (start)
      - Turn3, Turn4 (near home straight)
      - HomeStraight
      - Turn1, Turn2 (far end, around 200 m start)
    """
    s_global = s_eff + S_OFFSET
    lap_idx = int(s_global // LAP_LEN)
    s_mod = s_global % LAP_LEN

    sec_starts = {}
    sec_lengths = {}

    # HomeStraight
    sec_starts["HomeStraight"] = 0.0
    sec_lengths["HomeStraight"] = L_STRAIGHT
    # Bend1 = far end: Turn1, Turn2
    sec_starts["Turn1"] = L_STRAIGHT
    sec_lengths["Turn1"] = ARC_LEN / 2.0
    sec_starts["Turn2"] = L_STRAIGHT + ARC_LEN / 2.0
    sec_lengths["Turn2"] = ARC_LEN / 2.0
    # BackStraight
    sec_starts["BackStraight"] = L_STRAIGHT + ARC_LEN
    sec_lengths["BackStraight"] = L_STRAIGHT
    # Bend2 = near home: Turn3, Turn4
    sec_starts["Turn3"] = L_STRAIGHT + ARC_LEN + L_STRAIGHT
    sec_lengths["Turn3"] = ARC_LEN / 2.0
    sec_starts["Turn4"] = L_STRAIGHT + ARC_LEN + L_STRAIGHT + ARC_LEN / 2.0
    sec_lengths["Turn4"] = LAP_LEN - sec_starts["Turn4"]

    # Find section
    if s_mod < sec_starts["Turn1"]:
        sec = "HomeStraight"
    elif s_mod < sec_starts["Turn2"]:
        sec = "Turn1"
    elif s_mod < sec_starts["BackStraight"]:
        sec = "Turn2"
    elif s_mod < sec_starts["Turn3"]:
        sec = "BackStraight"
    elif s_mod < sec_starts["Turn4"]:
        sec = "Turn3"
    else:
        sec = "Turn4"

    start = sec_starts[sec]
    length = sec_lengths[sec]
    s_local = s_mod - start
    frac = max(0.0, min(0.9999, s_local / max(length, 1e-6)))
    quarter = int(frac * 4) + 1  # 1..4

    return lap_idx, sec, quarter


# -------------------------
# Load power curves (seated & standing)
# -------------------------

def load_power_curves(csv_path=POWER_CURVE_CSV):
    """
    Load power-duration curves from CSV with columns:
      duration_s, seated_W, standing_W

    Returns:
        dict with keys 'duration_s', 'seated_W', 'standing_W' as numpy arrays
    """
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    required = ["duration_s", "seated_W", "standing_W"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Required column '{col}' not found in {csv_path}")

    df = df.dropna(subset=required).sort_values("duration_s").reset_index(drop=True)

    return {
        "duration_s": df["duration_s"].to_numpy(),
        "seated_W": df["seated_W"].to_numpy(),
        "standing_W": df["standing_W"].to_numpy(),
    }


def get_power_at_duration(power_curves, duration_s, position="seated"):
    """
    Interpolate power at a given duration from power curves.

    Args:
        power_curves: dict from load_power_curves()
        duration_s: duration in seconds
        position: "seated" or "standing"

    Returns:
        interpolated power in watts
    """
    durations = power_curves["duration_s"]
    if position == "seated":
        powers = power_curves["seated_W"]
    elif position == "standing":
        powers = power_curves["standing_W"]
    else:
        raise ValueError(f"Unknown position '{position}', use 'seated' or 'standing'")

    return np.interp(duration_s, durations, powers)


# Load power curves by default
POWER_CURVES = load_power_curves()

# -------------------------
# Load profile
# -------------------------

profile = pd.read_csv(PROFILE_CSV)
profile.columns = profile.columns.str.strip()  # handle any accidental whitespace in headers

required_cols = ["s_m", "y_m", "CdA_m2", "P_W"]
for col in required_cols:
    if col not in profile.columns:
        raise ValueError(f"Required column '{col}' not found in {PROFILE_CSV}")

profile = profile.sort_values("s_m").reset_index(drop=True)

s_break = profile["s_m"].to_numpy()
y_break = profile["y_m"].to_numpy()
CdA_break = profile["CdA_m2"].to_numpy()
P_break = profile["P_W"].to_numpy()

def get_optional_col(name):
    return profile[name].to_numpy() if name in profile.columns else np.full(len(profile), np.nan)

y2_break = get_optional_col("y_m_2")
CdA2_break = get_optional_col("CdA_m2_2")
P2_break = get_optional_col("P_W_2")

# -------------------------
# Helper for NaN-safe override interpolation
# -------------------------

def interp_override(s_grid, s_break, override_break):
    """
    Interpolate an override column (which may contain NaNs) onto s_grid.
    - Uses only points where override_break is not NaN.
    - Returns NaN everywhere if there are no valid override points.
    - Only interpolates within contiguous segments of defined overrides.
    - Gaps between override segments are left as NaN (fall back to base).
    """
    mask = ~np.isnan(override_break)
    if mask.sum() == 0:
        # no overrides at all
        return np.full_like(s_grid, np.nan, dtype=float)

    result = np.full_like(s_grid, np.nan, dtype=float)
    s_valid = s_break[mask]
    vals_valid = override_break[mask]

    if mask.sum() == 1:
        # only one override point: apply only at grid points near it
        tol = (s_grid[1] - s_grid[0]) / 2 if len(s_grid) > 1 else 0.25
        close_mask = np.abs(s_grid - s_valid[0]) <= tol
        result[close_mask] = vals_valid[0]
        return result

    # Find contiguous segments in the override data
    # A gap exists if the distance between consecutive override points exceeds
    # the typical spacing in s_break (use median spacing as threshold)
    s_break_spacing = np.diff(s_break)
    typical_spacing = np.median(s_break_spacing[s_break_spacing > 0])
    gap_threshold = typical_spacing * 1.5  # allow some tolerance

    # Find segment boundaries (indices where gaps occur)
    valid_indices = np.where(mask)[0]
    s_at_valid = s_break[valid_indices]
    gaps = np.diff(s_at_valid) > gap_threshold
    segment_starts = [0] + list(np.where(gaps)[0] + 1)
    segment_ends = list(np.where(gaps)[0] + 1) + [len(valid_indices)]

    # Interpolate within each contiguous segment
    for seg_start, seg_end in zip(segment_starts, segment_ends):
        seg_indices = valid_indices[seg_start:seg_end]
        seg_s = s_break[seg_indices]
        seg_vals = override_break[seg_indices]

        if len(seg_s) == 1:
            # Single point segment: apply at nearby grid points
            tol = (s_grid[1] - s_grid[0]) / 2 if len(s_grid) > 1 else 0.25
            close_mask = np.abs(s_grid - seg_s[0]) <= tol
            result[close_mask] = seg_vals[0]
        else:
            # Multi-point segment: interpolate within range
            in_range = (s_grid >= seg_s.min()) & (s_grid <= seg_s.max())
            result[in_range] = np.interp(s_grid[in_range], seg_s, seg_vals)

    return result

# -------------------------
# Build sim grid & geometry (shared)
# -------------------------

s_grid = np.arange(0.0, S_TOTAL + DS, DS)
theta_grid = np.array([theta_track_blackline(s + S_OFFSET) for s in s_grid])

lap_idx_list = []
section_list = []
quarter_list = []
for s in s_grid:
    lap_idx, sec, q = classify_section_and_quarter(s)
    lap_idx_list.append(lap_idx)
    section_list.append(sec)
    quarter_list.append(q)

lap_idx_arr = np.array(lap_idx_list)
section_arr = np.array(section_list)
quarter_arr = np.array(quarter_list)

# -------------------------
# Build base and modified grids
# -------------------------

# Base (from original columns)
y_base_grid = np.interp(s_grid, s_break, y_break)
CdA_base_grid = np.interp(s_grid, s_break, CdA_break)
P_base_grid = np.interp(s_grid, s_break, P_break)

# Raw overrides (interpolated, ignoring NaNs in the break arrays)
y2_raw_grid = interp_override(s_grid, s_break, y2_break)
CdA2_raw_grid = interp_override(s_grid, s_break, CdA2_break)
P2_raw_grid   = interp_override(s_grid, s_break, P2_break)

# Modified = override where non-NaN, otherwise base
y_mod_grid = np.where(np.isnan(y2_raw_grid), y_base_grid, y2_raw_grid)
CdA_mod_grid = np.where(np.isnan(CdA2_raw_grid), CdA_base_grid, CdA2_raw_grid)
P_mod_grid = np.where(np.isnan(P2_raw_grid), P_base_grid, P2_raw_grid)

# -------------------------
# Helper: simulate a given (y, CdA, P) profile
# -------------------------

def simulate_profile(y_grid, CdA_grid, P_grid, label="base"):
    n = len(s_grid)

    h_grid = y_grid * np.sin(theta_grid)

    v = np.zeros(n)
    t = np.zeros(n)
    dt_arr = np.zeros(n)
    W_prime_rem = np.zeros(n)
    P_eff_used = np.zeros(n)

    F_aero_arr = np.zeros(n)
    F_rr_arr = np.zeros(n)
    W_aero_arr = np.zeros(n)
    W_rr_arr = np.zeros(n)
    dE_pot_arr = np.zeros(n)
    dE_kin_arr = np.zeros(n)
    ds_actual_arr = np.zeros(n)

    v[0] = V0
    W_prime_rem[0] = W_PRIME_TOTAL

    for i in range(n - 1):
        s_i = s_grid[i]
        s_next = s_grid[i + 1]
        ds_black = s_next - s_i

        v_i = max(v[i], MIN_V)
        P_target = max(P_grid[i], 0.0)

        # Path scaling in bends
        s_global_i = s_i + S_OFFSET
        if in_bend_region(s_global_i):
            factor = (R_BEND + y_grid[i]) / R_BEND
        else:
            factor = 1.0

        ds_arc = ds_black * factor

        # Add diagonal distance when y changes (triangular distance)
        dy = y_grid[i + 1] - y_grid[i]
        ds_actual = np.sqrt(ds_arc**2 + dy**2)
        dt = ds_actual / v_i

        # CP / W' logic with reconstitution
        if P_target <= CP:
            P_eff = P_target
            # W' reconstitutes when below CP (simple linear model)
            # Reconstitution rate: (CP - P) * dt worth of W' recovered
            # But don't exceed W_PRIME_TOTAL
            dW_prime = -(CP - P_target) * dt  # negative = recovery
        elif W_prime_rem[i] <= 0.0:
            # W' exhausted, can only output CP
            P_eff = CP
            dW_prime = 0.0
        else:
            max_above_CP = W_prime_rem[i] / dt
            P_above_CP = min(P_target - CP, max_above_CP)
            P_eff = CP + P_above_CP
            dW_prime = P_above_CP * dt

        CdA_i = CdA_grid[i]
        theta_i = theta_grid[i]

        F_aero = 0.5 * RHO * CdA_i * v_i**2
        F_rr = C_RR * MASS * G * np.cos(theta_i)

        dh = h_grid[i + 1] - h_grid[i]
        dE_pot = MASS * G * dh

        W_rider = P_eff * DRIVETRAIN_EFF * dt
        W_resist = (F_aero + F_rr) * ds_actual

        dE_kin = W_rider - W_resist - dE_pot
        E_kin_i = 0.5 * MASS * v_i**2
        E_kin_next = max(E_kin_i + dE_kin, 0.0)

        v_next = np.sqrt(2.0 * E_kin_next / MASS)

        v[i + 1] = v_next
        t[i + 1] = t[i] + dt
        dt_arr[i] = dt
        W_prime_rem[i + 1] = min(max(W_prime_rem[i] - dW_prime, 0.0), W_PRIME_TOTAL)
        P_eff_used[i] = P_eff

        F_aero_arr[i] = F_aero
        F_rr_arr[i] = F_rr
        W_aero_arr[i] = F_aero * ds_actual
        W_rr_arr[i] = F_rr * ds_actual
        dE_pot_arr[i] = dE_pot
        dE_kin_arr[i] = dE_kin
        ds_actual_arr[i] = ds_actual

    # Last index copy
    dt_arr[-1] = dt_arr[-2]
    P_eff_used[-1] = P_eff_used[-2]
    F_aero_arr[-1] = F_aero_arr[-2]
    F_rr_arr[-1] = F_rr_arr[-2]
    W_aero_arr[-1] = W_aero_arr[-2]
    W_rr_arr[-1] = W_rr_arr[-2]
    dE_pot_arr[-1] = dE_pot_arr[-2]
    dE_kin_arr[-1] = dE_kin_arr[-2]
    ds_actual_arr[-1] = ds_actual_arr[-2]

    # Timed 200 metrics
    t_200_start = np.interp(S_200_START, s_grid, t)
    t_200_end = np.interp(S_TOTAL, s_grid, t)
    T_200 = t_200_end - t_200_start

    v_200_entry = np.interp(S_200_START, s_grid, v)
    v_200_exit = np.interp(S_TOTAL, s_grid, v)

    # Sprint time: from first significant power increase to finish
    # Detect sprint start as first point where power exceeds CP + SPRINT_DELTA_OVER_CP
    P_sprint_threshold = CP + SPRINT_DELTA_OVER_CP
    sprint_start_idx = np.argmax(P_grid > P_sprint_threshold)
    if P_grid[sprint_start_idx] <= P_sprint_threshold:
        # No significant increase found, use start
        sprint_start_idx = 0
    s_sprint_start = s_grid[sprint_start_idx]
    t_sprint_start = t[sprint_start_idx]
    T_sprint = t[-1] - t_sprint_start

    # Average wattage during sprint
    sprint_mask = np.arange(len(s_grid)) >= sprint_start_idx
    P_avg_sprint = np.average(P_eff_used[sprint_mask], weights=dt_arr[sprint_mask]) if dt_arr[sprint_mask].sum() > 0 else 0.0

    # 200 m 50m splits
    s_0 = S_200_START
    s_50 = S_200_START + 50.0
    s_100 = S_200_START + 100.0
    s_150 = S_200_START + 150.0
    s_200 = S_200_START + 200.0

    t_0 = np.interp(s_0, s_grid, t)
    t_50 = np.interp(s_50, s_grid, t)
    t_100 = np.interp(s_100, s_grid, t)
    t_150 = np.interp(s_150, s_grid, t)
    t_200 = np.interp(s_200, s_grid, t)

    split_0_50 = t_50 - t_0
    split_50_100 = t_100 - t_50
    split_100_150 = t_150 - t_100
    split_150_200 = t_200 - t_150

    result = {
        "label": label,
        "v": v,
        "t": t,
        "dt": dt_arr,
        "W_prime_rem": W_prime_rem,
        "P_eff": P_eff_used,
        "W_aero": W_aero_arr,
        "W_rr": W_rr_arr,
        "dE_pot": dE_pot_arr,
        "dE_kin": dE_kin_arr,
        "ds_actual": ds_actual_arr,
        "y": y_grid,
        "CdA": CdA_grid,
        "T_total": t[-1],
        "T_200": T_200,
        "v_200_entry": v_200_entry,
        "v_200_exit": v_200_exit,
        "splits_200": (split_0_50, split_50_100, split_100_150, split_150_200),
        "T_sprint": T_sprint,
        "s_sprint_start": s_sprint_start,
        "P_avg_sprint": P_avg_sprint,
        "P_sprint_threshold": P_sprint_threshold,
    }

    return result


# -------------------------
# Run both simulations (only when executed directly)
# -------------------------

# -------------------------
# Save detailed outputs
# -------------------------

def save_output_csv(res, filename, s_grid, lap_idx_arr, section_arr, quarter_arr, theta_grid):
    out_df = pd.DataFrame({
        "s_m": s_grid,
        "lap_idx": lap_idx_arr,
        "section": section_arr,
        "quarter_of_section": quarter_arr,
        "t_s": res["t"],
        "dt_s": res["dt"],
        "v_mps": res["v"],
        "v_kph": res["v"] * 3.6,
        "y_m": res["y"],
        "theta_deg": np.rad2deg(theta_grid),
        "CdA_m2": res["CdA"],
        "P_eff_W": res["P_eff"],
        "W_prime_remaining_J": res["W_prime_rem"],
        "F_aero_N": res["W_aero"] / np.maximum(res["ds_actual"], 1e-9),
        "F_rr_N": res["W_rr"] / np.maximum(res["ds_actual"], 1e-9),
        "W_aero_J": res["W_aero"],
        "W_rr_J": res["W_rr"],
        "dE_pot_J": res["dE_pot"],
        "dE_kin_J": res["dE_kin"],
        "ds_actual_m": res["ds_actual"],
    })
    out_df.to_csv(filename, index=False)

# ============================================
# Segment Diagnostics (base vs mod)
# ============================================

def segment_stats(res, s_start, s_end):
    mask = (s_grid >= s_start) & (s_grid <= s_end)
    if not mask.any():
        return None
    ds_actual = res["ds_actual"][mask].sum()
    dE_pot = res["dE_pot"][mask].sum()
    W_aero = res["W_aero"][mask].sum()
    W_rr = res["W_rr"][mask].sum()
    dt = res["dt"][mask].sum()
    s_black = s_grid[mask][-1] - s_grid[mask][0]
    v_avg_black = s_black / dt if dt > 0 else 0.0
    v_avg_actual = ds_actual / dt if dt > 0 else 0.0
    return {
        "dt": dt,
        "ds_actual": ds_actual,
        "s_black": s_black,
        "dE_pot": dE_pot,
        "W_aero": W_aero,
        "W_rr": W_rr,
        "v_avg_black": v_avg_black,
        "v_avg_actual": v_avg_actual,
    }

def print_segment_compare(name, s_start, s_end):
    b = segment_stats(base_res, s_start, s_end)
    m = segment_stats(mod_res, s_start, s_end)
    if b is None or m is None:
        print(f"[{name}] segment has no points")
        return

    print(f"--- Segment: {name} (s={s_start:.1f}->{s_end:.1f}) ---")
    print("          base        mod        diff(mod-base)")
    print(f"time[s]   {b['dt']:7.4f}   {m['dt']:7.4f}   {m['dt']-b['dt']:8.4f}")
    print(f"path[m]   {b['ds_actual']:7.3f}   {m['ds_actual']:7.3f}   {m['ds_actual']-b['ds_actual']:8.3f}")
    print(f"W_aero[J] {b['W_aero']:7.1f}   {m['W_aero']:7.1f}   {m['W_aero']-b['W_aero']:8.1f}")
    print(f"W_rr[J]   {b['W_rr']:7.1f}   {m['W_rr']:7.1f}   {m['W_rr']-b['W_rr']:8.1f}")
    print(f"dE_pot[J] {b['dE_pot']:7.1f}   {m['dE_pot']:7.1f}   {m['dE_pot']-b['dE_pot']:8.1f}")
    print(f"v_avg[kph]{b['v_avg_actual']*3.6:7.2f}   {m['v_avg_actual']*3.6:7.2f}   { (m['v_avg_actual']-b['v_avg_actual'])*3.6:8.2f}")
    print()

SEGMENTS = [
    ("example_530_610", 530.0, 610.0),
    ("last_lap", S_TOTAL - 250.0, S_TOTAL),
    ("timed_200", S_200_START, S_TOTAL),
    ("last_100", S_TOTAL - 100.0, S_TOTAL),
    ("last_50", S_TOTAL - 50.0, S_TOTAL),
]

# ============================================
# Per-lap / per-section summary (base vs mod)
# ============================================

def per_section(res, lap_idx_arr, section_arr):
    df = pd.DataFrame({
        "lap_idx": lap_idx_arr,
        "section": section_arr,
        "dt_s": res["dt"],
        "ds_actual_m": res["ds_actual"],
        "W_aero_J": res["W_aero"],
        "W_rr_J": res["W_rr"],
        "dE_pot_J": res["dE_pot"],
        "v_mps": res["v"],
    })
    agg = df.groupby(["lap_idx", "section"]).agg(
        time_s=("dt_s", "sum"),
        path_m=("ds_actual_m", "sum"),
        W_aero_J=("W_aero_J", "sum"),
        W_rr_J=("W_rr_J", "sum"),
        dE_pot_J=("dE_pot_J", "sum"),
        v_mean_mps=("v_mps", "mean"),
    ).reset_index()
    return agg

# ============================================
# Overall Summary & 200 m splits
# ============================================

def print_overall(res, name):
    T_total = res["T_total"]
    T_200 = res["T_200"]
    T_sprint = res["T_sprint"]
    s_sprint_start = res["s_sprint_start"]
    P_avg_sprint = res["P_avg_sprint"]
    P_sprint_threshold = res["P_sprint_threshold"]
    v_in = res["v_200_entry"]
    v_out = res["v_200_exit"]
    s_total_actual = res["ds_actual"].sum()
    s0_50, s50_100, s100_150, s150_200 = res["splits_200"]

    print(f"[{name}]")
    print(f"  Total time (0–{S_TOTAL:.1f} m)    : {T_total:.3f} s")
    print(f"  Sprint detection (CP+{SPRINT_DELTA_OVER_CP:.0f}W)     : {CP:.0f} + {SPRINT_DELTA_OVER_CP:.0f} = {P_sprint_threshold:.0f} W")
    print(f"  Sprint time (from {s_sprint_start:.1f} m)    : {T_sprint:.3f} s")
    print(f"  200 m time                        : {T_200:.3f} s")
    print(f"  Avg power during sprint           : {P_avg_sprint:.0f} W")
    print(f"  Entry speed at 200 m              : {v_in:.2f} m/s ({v_in*3.6:.1f} km/h)")
    print(f"  Exit  speed at 200 m              : {v_out:.2f} m/s ({v_out*3.6:.1f} km/h)")
    print(f"  Total actual path length          : {s_total_actual:.1f} m")
    print(f"  200 m splits:")
    print(f"    0–50   : {s0_50:.3f} s")
    print(f"    50–100 : {s50_100:.3f} s")
    print(f"    100–150: {s100_150:.3f} s")
    print(f"    150–200: {s150_200:.3f} s")
    print(f"  W' remaining at finish            : {res['W_prime_rem'][-1]:.0f} J\n")


# ============================================
# Speed Gain/Loss Visualization (BASE vs MOD)
# ============================================

def plot_speed_comparison():
    """
    Create a visualization showing speed gain/loss between BASE and MOD
    at different track markers/sections.
    """
    fig, axes = plt.subplots(3, 1, figsize=(14, 14))
    fig.subplots_adjust(hspace=0.35)

    # ---- Plot 1: Speed profiles over distance ----
    ax1 = axes[0]
    v_base_kph = base_res["v"] * 3.6
    v_mod_kph = mod_res["v"] * 3.6

    ax1.plot(s_grid, v_base_kph, 'b-', linewidth=1.5, label='BASE', alpha=0.8)
    ax1.plot(s_grid, v_mod_kph, 'r-', linewidth=1.5, label='MOD', alpha=0.8)

    # Shade track sections
    section_colors = {
        'BackStraight': '#E8F5E9',
        'Turn3': '#FFF3E0',
        'Turn4': '#FFF3E0',
        'HomeStraight': '#E3F2FD',
        'Turn1': '#FCE4EC',
        'Turn2': '#FCE4EC',
    }

    # Add section shading
    prev_section = None
    section_start = 0
    for i, sec in enumerate(section_arr):
        if sec != prev_section:
            if prev_section is not None:
                ax1.axvspan(section_start, s_grid[i-1], alpha=0.3,
                           color=section_colors.get(prev_section, '#EEEEEE'))
            section_start = s_grid[i]
            prev_section = sec
    # Final section
    ax1.axvspan(section_start, s_grid[-1], alpha=0.3,
               color=section_colors.get(prev_section, '#EEEEEE'))

    # Mark 200m start
    ax1.axvline(S_200_START, color='green', linestyle='--', linewidth=2, label='200m Start')

    ax1.set_xlabel('Distance along black line (m)')
    ax1.set_ylabel('Speed (km/h)')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, S_TOTAL)

    # ---- Plot 2: Speed difference (MOD - BASE) over distance ----
    ax2 = axes[1]
    v_diff_kph = v_mod_kph - v_base_kph

    # Color based on gain (green) or loss (red)
    ax2.fill_between(s_grid, v_diff_kph, 0,
                     where=(v_diff_kph >= 0),
                     color='green', alpha=0.5, label='Speed Gain (MOD faster)')
    ax2.fill_between(s_grid, v_diff_kph, 0,
                     where=(v_diff_kph < 0),
                     color='red', alpha=0.5, label='Speed Loss (MOD slower)')
    ax2.axhline(0, color='black', linewidth=1)
    ax2.axvline(S_200_START, color='green', linestyle='--', linewidth=2)

    ax2.set_xlabel('Distance along black line (m)')
    ax2.set_ylabel('Speed Difference (km/h)')
    ax2.legend(loc='upper left')
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(0, S_TOTAL)

    # ---- Plot 3: Bar chart of speed gain/loss by section ----
    ax3 = axes[2]

    # Calculate average speed difference per section, ordered by distance
    # Build section data directly from simulation grid to ensure correct order
    section_data = []

    # Get unique (lap, section) pairs in order of appearance
    seen = set()
    ordered_sections = []
    for i, (lap, sec) in enumerate(zip(lap_idx_arr, section_arr)):
        key = (lap, sec)
        if key not in seen:
            seen.add(key)
            ordered_sections.append(key)

    for lap, sec in ordered_sections:
        row = merged[(merged['lap_idx'] == lap) & (merged['section'] == sec)]
        if not row.empty:
            row = row.iloc[0]
            v_diff = (row['v_mean_mps_mod'] - row['v_mean_mps_base']) * 3.6
            section_data.append({
                'label': f"L{int(lap)}-{sec}",
                'v_diff': v_diff,
                'lap': int(lap),
                'section': sec
            })

    labels = [d['label'] for d in section_data]
    v_diffs = [d['v_diff'] for d in section_data]
    colors = ['green' if v >= 0 else 'red' for v in v_diffs]

    bars = ax3.bar(range(len(labels)), v_diffs, color=colors, alpha=0.7, edgecolor='black')
    ax3.axhline(0, color='black', linewidth=1)
    ax3.set_xticks(range(len(labels)))
    ax3.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
    ax3.set_xlabel('Lap - Section')
    ax3.set_ylabel('Avg Speed Diff (km/h)')
    ax3.grid(True, alpha=0.3, axis='y')

    # Add value labels on bars
    for bar, val in zip(bars, v_diffs):
        height = bar.get_height()
        ax3.annotate(f'{val:.2f}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3 if height >= 0 else -10),
                    textcoords="offset points",
                    ha='center', va='bottom' if height >= 0 else 'top',
                    fontsize=7)

    # Add legend
    gain_patch = mpatches.Patch(color='green', alpha=0.7, label='MOD faster')
    loss_patch = mpatches.Patch(color='red', alpha=0.7, label='MOD slower')
    ax3.legend(handles=[gain_patch, loss_patch], loc='upper right')

    plt.savefig('speed_comparison_chart.png', dpi=150, bbox_inches='tight')
    print("\n=== Speed Comparison Chart Saved ========================")
    print("Chart saved to: speed_comparison_chart.png")
    print("=========================================================")
    plt.show()


# ============================================
# Main execution block (only runs when script is executed directly)
# ============================================

if __name__ == "__main__":
    # Run both simulations
    base_res = simulate_profile(y_base_grid, CdA_base_grid, P_base_grid, label="base")
    mod_res = simulate_profile(y_mod_grid, CdA_mod_grid, P_mod_grid, label="mod")

    # Save output CSVs
    save_output_csv(base_res, "f200_simulation_output_base.csv", s_grid, lap_idx_arr, section_arr, quarter_arr, theta_grid)
    save_output_csv(mod_res, "f200_simulation_output_mod.csv", s_grid, lap_idx_arr, section_arr, quarter_arr, theta_grid)

    # Print segment diagnostics
    print("\n=== Segment Diagnostics (base vs modified) ==============")
    for name, s_start, s_end in SEGMENTS:
        b = segment_stats(base_res, s_start, s_end)
        m = segment_stats(mod_res, s_start, s_end)
        if b is None or m is None:
            print(f"[{name}] segment has no points")
            continue
        print(f"--- Segment: {name} (s={s_start:.1f}->{s_end:.1f}) ---")
        print("          base        mod        diff(mod-base)")
        print(f"time[s]   {b['dt']:7.4f}   {m['dt']:7.4f}   {m['dt']-b['dt']:8.4f}")
        print(f"path[m]   {b['ds_actual']:7.3f}   {m['ds_actual']:7.3f}   {m['ds_actual']-b['ds_actual']:8.3f}")
        print(f"W_aero[J] {b['W_aero']:7.1f}   {m['W_aero']:7.1f}   {m['W_aero']-b['W_aero']:8.1f}")
        print(f"W_rr[J]   {b['W_rr']:7.1f}   {m['W_rr']:7.1f}   {m['W_rr']-b['W_rr']:8.1f}")
        print(f"dE_pot[J] {b['dE_pot']:7.1f}   {m['dE_pot']:7.1f}   {m['dE_pot']-b['dE_pot']:8.1f}")
        print(f"v_avg[kph]{b['v_avg_actual']*3.6:7.2f}   {m['v_avg_actual']*3.6:7.2f}   { (m['v_avg_actual']-b['v_avg_actual'])*3.6:8.2f}")
        print()
    print("=========================================================\n")

    # Per-section summary
    base_agg = per_section(base_res, lap_idx_arr, section_arr)
    mod_agg = per_section(mod_res, lap_idx_arr, section_arr)

    merged = pd.merge(
        base_agg, mod_agg,
        on=["lap_idx", "section"],
        suffixes=("_base", "_mod"),
        how="outer",
    ).fillna(0.0)

    section_order = ["BackStraight", "Turn3", "Turn4", "HomeStraight", "Turn1", "Turn2"]
    merged["section_order"] = merged["section"].apply(
        lambda s: section_order.index(s) if s in section_order else 999
    )
    merged = merged.sort_values(["lap_idx", "section_order"])

    print("=== Per-lap / Per-section Summary (base vs mod) =========")
    print("lap  section       time_b  time_m  dT     v_b    v_m   dv   W_aero_b  W_aero_m  dW_aero")
    for _, row in merged.iterrows():
        tb = row["time_s_base"]
        tm = row["time_s_mod"]
        vb = row["v_mean_mps_base"] * 3.6
        vm = row["v_mean_mps_mod"] * 3.6
        Wab = row["W_aero_J_base"] / 1000.0
        Wam = row["W_aero_J_mod"] / 1000.0
        print(f"{int(row['lap_idx']):3d}  {row['section']:<12s} "
              f"{tb:6.3f} {tm:6.3f} {tm-tb:6.3f} "
              f"{vb:6.1f} {vm:6.1f} {vm-vb:5.2f} "
              f"{Wab:9.3f} {Wam:9.3f} {Wam-Wab:8.3f}")
    print("=========================================================\n")

    # Overall summary
    print("=== Overall Summary =====================================")
    print_overall(base_res, "BASE")
    print_overall(mod_res, "MODIFIED")

    print("=== Differences (MOD - BASE) ============================")
    print(f"dTotal time  : {mod_res['T_total'] - base_res['T_total']:.4f} s")
    print(f"dSprint time : {mod_res['T_sprint'] - base_res['T_sprint']:.4f} s")
    print(f"d200 m time  : {mod_res['T_200'] - base_res['T_200']:.4f} s")
    print(f"dAvg power   : {mod_res['P_avg_sprint'] - base_res['P_avg_sprint']:.0f} W")
    s0_50_b, s50_100_b, s100_150_b, s150_200_b = base_res["splits_200"]
    s0_50_m, s50_100_m, s100_150_m, s150_200_m = mod_res["splits_200"]
    print(f"d0-50        : {s0_50_m - s0_50_b:.4f} s")
    print(f"d50-100      : {s50_100_m - s50_100_b:.4f} s")
    print(f"d100-150     : {s100_150_m - s100_150_b:.4f} s")
    print(f"d150-200     : {s150_200_m - s150_200_b:.4f} s")
    print("=========================================================")

    # Generate the visualization
    plot_speed_comparison()
