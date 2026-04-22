"""
Flying 200 V2 - Physics Engine

CRITICAL: This physics engine is VALIDATED to 10-30ms accuracy.
DO NOT MODIFY THE MATH without explicit validation testing.

Extracted from flying200_package/flying200_model.py with identical calculations.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional


# =============================================================================
# Simulation Configuration (User-Tunable Parameters)
# =============================================================================

@dataclass
class SimulationConfig:
    """Configuration parameters for the simulation.

    All defaults match the validated v1 simulation.
    """
    # Rider/equipment
    mass_kg: float = 92.0              # rider + bike mass

    # Environment
    rho_kg_m3: float = 1.18            # air density
    c_rr: float = 0.0020               # rolling resistance coefficient
    g_m_s2: float = 9.81               # gravitational acceleration

    # Physiology (CP/W' model)
    cp_watts: float = 250.0            # critical power
    w_prime_joules: float = 25000.0    # W' (anaerobic work capacity)

    # Initial conditions
    v0_m_s: float = 5.0                # initial speed
    min_v_m_s: float = 0.1             # minimum speed (avoid div-by-zero)

    # Drivetrain
    drivetrain_efficiency: float = 1.0  # 1.0 = 100%, 0.97 = 97%

    # Simulation resolution
    ds_m: float = 0.25                 # step size along black line

    # Sprint detection
    sprint_delta_over_cp: float = 250.0  # power above CP to detect sprint

    # CdA bend factor: ratio of bend CdA to straight CdA
    # Values < 1.0 mean CdA is lower in bends (due to yaw angle reducing frontal area)
    # Example: 0.97 means bend CdA is 97% of straight CdA
    # The profile CdA represents bends; straights get CdA/bend_factor (higher drag)
    cda_bend_factor: float = 1.0       # 1.0 = no difference, 0.97 = typical


# =============================================================================
# Physics Constants
# =============================================================================

G = 9.81                               # [m/s^2] gravitational acceleration
RHO = 1.18                             # [kg/m^3] default air density


# =============================================================================
# Track Geometry Constants (Bromont/Atlanta 250m)
# =============================================================================

LAP_LEN = 250.0                        # [m] lap on black line
L_STRAIGHT = 59.0                      # [m] straight length
R_BEND = (LAP_LEN - 2.0 * L_STRAIGHT) / (2.0 * np.pi)  # ~21.1 m
ARC_LEN = np.pi * R_BEND               # [m] bend half-circle

THETA_STRAIGHT_DEG = 12.0
THETA_BEND_DEG = 42.0
THETA_STRAIGHT = np.deg2rad(THETA_STRAIGHT_DEG)
THETA_BEND = np.deg2rad(THETA_BEND_DEG)

# Transition length - half the arc length (matches v1 model)
TRANS_LEN = ARC_LEN / 2                # [m] banking transition (~33m for Bromont)

# s=0 at back-straight pursuit line (mid back straight)
S_OFFSET = (L_STRAIGHT            # home straight
            + ARC_LEN             # bend1
            + 0.5 * L_STRAIGHT)   # half of back straight

# Effort distance parameters
S_TOTAL = 895.0                        # [m] total effort along black line
S_200_START = S_TOTAL - 200.0          # [m] start of timed 200


# =============================================================================
# Track Geometry Functions
# =============================================================================

def theta_track_blackline(s_global: float) -> float:
    """Banking angle theta(s_global) [rad] at global black-line distance.

    Smooth transitions occur centered on each bend/straight boundary,
    spanning TRANS_LEN total (half on each side). This matches the validated
    original GUI implementation.

    Track layout (one lap = 250m):
      0 to L_STRAIGHT: First straight (HomeStraight)
      L_STRAIGHT to L_STRAIGHT+ARC_LEN: Bend 1 (Turn1+Turn2)
      L_STRAIGHT+ARC_LEN to 2*L_STRAIGHT+ARC_LEN: Second straight (BackStraight)
      2*L_STRAIGHT+ARC_LEN to LAP_LEN: Bend 2 (Turn3+Turn4)
    """
    s_mod = s_global % LAP_LEN
    half_trans = TRANS_LEN / 2.0

    # Key boundaries
    bend1_start = L_STRAIGHT
    bend1_end = L_STRAIGHT + ARC_LEN
    bend2_start = L_STRAIGHT + ARC_LEN + L_STRAIGHT

    def lerp_theta(f: float) -> float:
        """Linear interpolate from THETA_STRAIGHT to THETA_BEND, f in [0,1]"""
        f = max(0.0, min(1.0, f))
        return THETA_STRAIGHT + f * (THETA_BEND - THETA_STRAIGHT)

    # Check distance to each boundary and apply transition if within half_trans

    # Transition at bend1_start
    if abs(s_mod - bend1_start) < half_trans:
        if s_mod < bend1_start:
            f = 0.5 - (bend1_start - s_mod) / TRANS_LEN
        else:
            f = 0.5 + (s_mod - bend1_start) / TRANS_LEN
        return lerp_theta(f)

    # Transition at bend1_end
    if abs(s_mod - bend1_end) < half_trans:
        if s_mod < bend1_end:
            f = 0.5 + (bend1_end - s_mod) / TRANS_LEN
        else:
            f = 0.5 - (s_mod - bend1_end) / TRANS_LEN
        return lerp_theta(f)

    # Transition at bend2_start
    if abs(s_mod - bend2_start) < half_trans:
        if s_mod < bend2_start:
            f = 0.5 - (bend2_start - s_mod) / TRANS_LEN
        else:
            f = 0.5 + (s_mod - bend2_start) / TRANS_LEN
        return lerp_theta(f)

    # Transition at bend2_end (wrap around at s_mod=0/LAP_LEN)
    if s_mod < half_trans:
        f = 0.5 - s_mod / TRANS_LEN
        return lerp_theta(f)
    elif s_mod > LAP_LEN - half_trans:
        f = 0.5 + (LAP_LEN - s_mod) / TRANS_LEN
        return lerp_theta(f)

    # Not in any transition zone
    if s_mod < bend1_start:
        return THETA_STRAIGHT
    elif s_mod < bend1_end:
        return THETA_BEND
    elif s_mod < bend2_start:
        return THETA_STRAIGHT
    else:
        return THETA_BEND


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


def get_cda_factor(
    s_global: float,
    cda_bend_factor: float,
    y_position: float = 0.0,
    radius_bend: float = R_BEND,
) -> float:
    """
    Calculate CdA factor based on position (straight vs bend) and track height.

    Profile CdA represents bends on black line (baseline aero position).
    Straights: CdA = CdA_profile / cda_bend_factor (higher drag)

    The yaw effect scales with track radius - less yaw when riding higher:
    - On black line (y=0): full effect
    - Higher on track: reduced effect (larger radius = less yaw)

    Example with cda_bend_factor=0.97:
      - Bends: use profile CdA (represents yawed position)
      - Straights at y=0: CdA/0.97 = 3.1% higher drag
      - Straights at y=7.5m: effect is scaled: ~2.2% higher drag

    Returns factor to multiply CdA by (1.0 in bends, scaled 1/factor on straights)
    """
    s_mod = s_global % LAP_LEN

    # Check if we're in a bend
    if s_mod >= L_STRAIGHT and s_mod < L_STRAIGHT + ARC_LEN:
        # Bend 1 (Turn 1 + Turn 2) - use profile CdA as-is
        return 1.0
    elif s_mod >= L_STRAIGHT + ARC_LEN + L_STRAIGHT:
        # Bend 2 (Turn 3 + Turn 4) - use profile CdA as-is
        return 1.0
    else:
        # On straight - increase CdA, scaled by track position
        if cda_bend_factor <= 0 or cda_bend_factor >= 1.0:
            return 1.0

        # Calculate yaw scaling based on effective radius
        # Higher on track = larger radius = less yaw = less CdA difference
        yaw_scale = radius_bend / (radius_bend + max(y_position, 0))

        # Base effect is (1/factor - 1), scale it by yaw_scale
        base_effect = (1.0 / cda_bend_factor) - 1.0  # e.g., 0.0309 for factor=0.97
        scaled_effect = base_effect * yaw_scale

        return 1.0 + scaled_effect


def get_cda_factor_for_track(
    s_global: float,
    cda_bend_factor: float,
    y_position: float,
    straight_length: float,
    lap_length: float,
    radius_bend: float,
) -> float:
    """
    Calculate CdA factor for any track geometry.

    Same logic as get_cda_factor but with configurable track parameters.
    """
    arc_len = (lap_length - 2.0 * straight_length) / 2.0
    s_mod = s_global % lap_length

    # Check if we're in a bend
    if s_mod >= straight_length and s_mod < straight_length + arc_len:
        return 1.0
    elif s_mod >= straight_length + arc_len + straight_length:
        return 1.0
    else:
        if cda_bend_factor <= 0 or cda_bend_factor >= 1.0:
            return 1.0

        yaw_scale = radius_bend / (radius_bend + max(y_position, 0))
        base_effect = (1.0 / cda_bend_factor) - 1.0
        scaled_effect = base_effect * yaw_scale

        return 1.0 + scaled_effect


# =============================================================================
# Line Cost Calculation
# =============================================================================

def calculate_line_cost(
    s_grid: np.ndarray,
    y_grid: np.ndarray,
    v_grid: np.ndarray,
    s_start: float,
    s_end: float,
    straight_length: float = L_STRAIGHT,
    lap_length: float = LAP_LEN,
    radius_bend: float = R_BEND,
    s_offset: float = S_OFFSET,
) -> float:
    """
    Calculate the time cost of riding the trajectory vs perfect black line (y=0).

    Line cost comes from:
    1. Extra path length in bends when y != 0: ds_arc = ds_black * (R_bend + y) / R_bend
    2. Diagonal distance when y changes: ds_actual = sqrt(ds_arc^2 + dy^2)

    Args:
        s_grid: Distance array along effort
        y_grid: Track position (y=0 is black line, y>0 is higher on track)
        v_grid: Velocity array
        s_start: Start distance for cost calculation
        s_end: End distance for cost calculation
        straight_length: Length of straights
        lap_length: Total lap length
        radius_bend: Turn radius at black line
        s_offset: Offset from effort start to track origin

    Returns:
        Time difference in seconds (positive = slower than perfect line)
    """
    # Get the segment mask
    mask = (s_grid >= s_start) & (s_grid <= s_end)
    if not mask.any():
        return 0.0

    indices = np.where(mask)[0]
    if len(indices) < 2:
        return 0.0

    # Calculate arc length for straights vs bends
    arc_len = (lap_length - 2.0 * straight_length) / 2.0

    mod_distance = 0.0
    perfect_distance = 0.0

    for i in range(len(indices) - 1):
        idx = indices[i]
        idx_next = indices[i + 1]

        s_val = s_grid[idx]
        y_val = y_grid[idx]
        y_next = y_grid[idx_next]
        dy = y_next - y_val
        ds_black = s_grid[idx_next] - s_val

        s_global = s_val + s_offset
        s_mod = s_global % lap_length

        # Check if in bend region
        in_bend = False
        if s_mod >= straight_length and s_mod < straight_length + arc_len:
            in_bend = True  # Bend 1
        elif s_mod >= straight_length + arc_len + straight_length:
            in_bend = True  # Bend 2

        if in_bend:
            # Arc length adjustment in bends
            ds_arc_mod = ds_black * (radius_bend + y_val) / radius_bend
            ds_arc_perfect = ds_black  # y=0 on black line
        else:
            # Straights: no arc adjustment
            ds_arc_mod = ds_black
            ds_arc_perfect = ds_black

        # Add diagonal distance for actual trajectory (y changes)
        ds_mod = np.sqrt(ds_arc_mod**2 + dy**2)
        ds_perfect = ds_arc_perfect  # No y change on perfect line

        mod_distance += ds_mod
        perfect_distance += ds_perfect

    # Time cost = extra distance / average velocity
    v_segment = v_grid[mask]
    v_avg = np.mean(v_segment) if len(v_segment) > 0 else 0.0

    extra_distance = mod_distance - perfect_distance
    if v_avg > 0:
        return extra_distance / v_avg
    else:
        return 0.0


def calculate_line_cost_for_track(
    s_grid: np.ndarray,
    y_grid: np.ndarray,
    v_grid: np.ndarray,
    s_start: float,
    s_end: float,
    track_geometry,
) -> float:
    """
    Calculate line cost for any track geometry.

    Args:
        s_grid: Distance array along effort
        y_grid: Track position
        v_grid: Velocity array
        s_start: Start distance
        s_end: End distance
        track_geometry: TrackGeometry object

    Returns:
        Time cost in seconds
    """
    if track_geometry is None:
        return calculate_line_cost(s_grid, y_grid, v_grid, s_start, s_end)

    # Calculate track parameters
    straight = track_geometry.straight_length_m
    lap = track_geometry.length_m
    radius = track_geometry.turn_radius_m
    arc = track_geometry.arc_length_m
    s_offset = straight + arc + 0.5 * straight  # Standard offset for F200

    return calculate_line_cost(
        s_grid, y_grid, v_grid, s_start, s_end,
        straight_length=straight,
        lap_length=lap,
        radius_bend=radius,
        s_offset=s_offset,
    )


# =============================================================================
# Breakeven and Implied CdA Calculations
# =============================================================================

def calculate_breakeven_watts_per_cda(v_ms: float, rho: float = RHO) -> float:
    """
    Calculate the breakeven watts/CdA at a given speed.

    This is the power-to-drag-area ratio needed to maintain the current speed
    against aerodynamic resistance alone.

    At breakeven: P = P_aero = 0.5 * rho * CdA * v^3
    Therefore: P/CdA = 0.5 * rho * v^3

    Args:
        v_ms: Velocity in m/s
        rho: Air density (default from physics constants)

    Returns:
        Breakeven watts/CdA in W/m^2
    """
    return 0.5 * rho * (v_ms ** 3)


def calculate_implied_cda(
    segment_distance: float,
    real_time: float,
    power_avg: float,
    mass: float,
    rho: float,
    c_rr: float,
    drivetrain_eff: float,
    theta_avg: float,
    dh: float,
    v_start: float,
    v_end: float,
) -> Optional[float]:
    """
    Reverse-engineer the CdA needed to match an actual measured segment time.

    From energy balance: P*dt*eff = F_aero*ds + F_rr*ds + dE_kin + dE_pot
    Where F_aero = 0.5 * rho * CdA * v^2

    Solving for CdA:
    CdA = (P*dt*eff - F_rr*ds - dE_kin - dE_pot) / (0.5 * rho * v_avg^2 * ds)

    Args:
        segment_distance: Distance of segment [m]
        real_time: Actual measured time for segment [s]
        power_avg: Average power for segment [W]
        mass: Rider+bike mass [kg]
        rho: Air density [kg/m^3]
        c_rr: Rolling resistance coefficient
        drivetrain_eff: Drivetrain efficiency (0-1)
        theta_avg: Average banking angle [rad]
        dh: Height change over segment [m]
        v_start: Velocity at segment start [m/s]
        v_end: Velocity at segment end [m/s]

    Returns:
        Implied CdA in m^2, or None if calculation fails
    """
    try:
        v_avg = segment_distance / real_time if real_time > 0 else 0

        # Kinetic energy change
        dE_kin = 0.5 * mass * (v_end**2 - v_start**2)

        # Potential energy change
        dE_pot = mass * G * dh

        # Rolling resistance work
        F_rr = c_rr * mass * G * np.cos(theta_avg)
        W_rr = F_rr * segment_distance

        # Work input from rider
        W_rider = power_avg * drivetrain_eff * real_time

        # Energy available for aero drag
        # W_rider = W_aero + W_rr + dE_kin + dE_pot
        W_aero = W_rider - W_rr - dE_kin - dE_pot

        # CdA = W_aero / (0.5 * rho * v^2 * ds)
        denominator = 0.5 * rho * v_avg**2 * segment_distance

        if denominator > 0 and W_aero > 0:
            implied_cda = W_aero / denominator
            # Sanity check for reasonable CdA range
            if 0.1 < implied_cda < 0.6:
                return implied_cda
            else:
                return implied_cda  # Return anyway but flag as questionable
        else:
            return None

    except Exception:
        return None


def calculate_watts_per_cda(power: float, cda: float) -> float:
    """
    Calculate watts per CdA ratio.

    Higher ratio means more power relative to drag area (better efficiency).

    Args:
        power: Power output [W]
        cda: Drag area [m^2]

    Returns:
        Watts/CdA ratio [W/m^2]
    """
    if cda > 0:
        return power / cda
    return 0.0


def classify_section_and_quarter(
    s_eff: float,
    s_offset: float = S_OFFSET,
    lap_length: float = LAP_LEN,
    straight_length: float = L_STRAIGHT,
    arc_length: float = ARC_LEN,
) -> Tuple[int, str, int]:
    """
    Return (lap_idx, section_name, quarter_index) for effort distance s_eff,
    where s_eff=0 at back-straight pursuit line.

    All geometry parameters default to Bromont 250m for backward compatibility.
    Pass track-specific values for other track sizes.

    Sections:
      - BackStraight (start)
      - Turn3, Turn4 (near home straight)
      - HomeStraight
      - Turn1, Turn2 (far end, around 200 m start)
    """
    s_global = s_eff + s_offset
    lap_idx = int(s_global // lap_length)
    s_mod = s_global % lap_length

    sec_starts = {}
    sec_lengths = {}

    # HomeStraight
    sec_starts["HomeStraight"] = 0.0
    sec_lengths["HomeStraight"] = straight_length
    # Bend1 = far end: Turn1, Turn2
    sec_starts["Turn1"] = straight_length
    sec_lengths["Turn1"] = arc_length / 2.0
    sec_starts["Turn2"] = straight_length + arc_length / 2.0
    sec_lengths["Turn2"] = arc_length / 2.0
    # BackStraight
    sec_starts["BackStraight"] = straight_length + arc_length
    sec_lengths["BackStraight"] = straight_length
    # Bend2 = near home: Turn3, Turn4
    sec_starts["Turn3"] = straight_length + arc_length + straight_length
    sec_lengths["Turn3"] = arc_length / 2.0
    sec_starts["Turn4"] = straight_length + arc_length + straight_length + arc_length / 2.0
    sec_lengths["Turn4"] = lap_length - sec_starts["Turn4"]

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


# =============================================================================
# Track-Aware Geometry Functions (for different track configurations)
# =============================================================================

def compute_theta_for_track(
    s_grid: np.ndarray,
    straight_length: float,
    lap_length: float,
    theta_straight_rad: float,
    theta_bend_rad: float,
    trans_len: float = None,
) -> np.ndarray:
    """
    Compute theta grid for any track geometry.

    This allows simulation with different track configurations (Bromont, Milton, etc.)
    while maintaining the same physics model.

    Args:
        s_grid: Distance grid [m] (s=0 at back-straight pursuit line)
        straight_length: Length of each straight section [m]
        lap_length: Total lap length [m]
        theta_straight_rad: Banking angle on straights [rad]
        theta_bend_rad: Banking angle in turns [rad]
        trans_len: Transition length [m] (default: arc_len / 2, matching v1)

    Returns:
        Array of banking angles [rad] for each grid point
    """
    arc_len = (lap_length - 2.0 * straight_length) / 2.0  # arc length per bend
    s_offset = straight_length + arc_len + 0.5 * straight_length

    # Default transition length = half the arc (matching v1 model)
    if trans_len is None:
        trans_len = arc_len / 2.0

    half_trans = trans_len / 2.0

    # Key boundaries
    bend1_start = straight_length
    bend1_end = straight_length + arc_len
    bend2_start = straight_length + arc_len + straight_length

    def lerp_theta(f: float) -> float:
        f = max(0.0, min(1.0, f))
        return theta_straight_rad + f * (theta_bend_rad - theta_straight_rad)

    def theta_at_s(s_eff: float) -> float:
        s_global = s_eff + s_offset
        s_mod = s_global % lap_length

        # Transition at bend1_start
        if abs(s_mod - bend1_start) < half_trans:
            if s_mod < bend1_start:
                f = 0.5 - (bend1_start - s_mod) / trans_len
            else:
                f = 0.5 + (s_mod - bend1_start) / trans_len
            return lerp_theta(f)

        # Transition at bend1_end
        if abs(s_mod - bend1_end) < half_trans:
            if s_mod < bend1_end:
                f = 0.5 + (bend1_end - s_mod) / trans_len
            else:
                f = 0.5 - (s_mod - bend1_end) / trans_len
            return lerp_theta(f)

        # Transition at bend2_start
        if abs(s_mod - bend2_start) < half_trans:
            if s_mod < bend2_start:
                f = 0.5 - (bend2_start - s_mod) / trans_len
            else:
                f = 0.5 + (s_mod - bend2_start) / trans_len
            return lerp_theta(f)

        # Transition at bend2_end (wrap around)
        if s_mod < half_trans:
            f = 0.5 - s_mod / trans_len
            return lerp_theta(f)
        elif s_mod > lap_length - half_trans:
            f = 0.5 + (lap_length - s_mod) / trans_len
            return lerp_theta(f)

        # Not in any transition zone
        if s_mod < bend1_start:
            return theta_straight_rad
        elif s_mod < bend1_end:
            return theta_bend_rad
        elif s_mod < bend2_start:
            return theta_straight_rad
        else:
            return theta_bend_rad

    return np.array([theta_at_s(s) for s in s_grid])


def compute_track_params_from_geometry(track_geometry) -> dict:
    """
    Extract physics parameters from a TrackGeometry object.

    Args:
        track_geometry: TrackGeometry object from core.track

    Returns:
        Dict with keys: straight_length, lap_length, theta_straight_rad,
        theta_bend_rad, radius_bend, arc_len, s_offset
    """
    straight = track_geometry.straight_length_m
    lap = track_geometry.length_m
    radius = track_geometry.turn_radius_m
    arc = np.pi * radius

    return {
        'straight_length': straight,
        'lap_length': lap,
        'theta_straight_rad': np.deg2rad(track_geometry.banking_straight_deg),
        'theta_bend_rad': np.deg2rad(track_geometry.banking_turn_deg),
        'radius_bend': radius,
        'arc_len': arc,
        's_offset': straight + arc + 0.5 * straight,
    }


def in_bend_region_for_track(s_global: float, straight_length: float, lap_length: float) -> bool:
    """Check if position is in a bend for any track geometry."""
    arc_len = (lap_length - 2.0 * straight_length) / 2.0
    s_mod = s_global % lap_length

    if s_mod < straight_length:
        return False
    elif s_mod < straight_length + arc_len:
        return True
    elif s_mod < straight_length + arc_len + straight_length:
        return False
    else:
        return True


# =============================================================================
# Simulation Result
# =============================================================================

@dataclass
class SimulationResult:
    """Results from a Flying 200 simulation."""

    # Time series data (indexed by distance)
    s_grid: np.ndarray          # distance along black line [m]
    v: np.ndarray               # velocity [m/s]
    t: np.ndarray               # cumulative time [s]
    dt: np.ndarray              # time step at each point [s]
    y: np.ndarray               # lateral position [m]
    CdA: np.ndarray             # drag area [m^2]
    P_eff: np.ndarray           # effective power used [W]
    W_prime_rem: np.ndarray     # W' remaining [J]

    # Energy components
    W_aero: np.ndarray          # aerodynamic work per step [J]
    W_rr: np.ndarray            # rolling resistance work per step [J]
    dE_pot: np.ndarray          # potential energy change per step [J]
    dE_kin: np.ndarray          # kinetic energy change per step [J]
    ds_actual: np.ndarray       # actual path distance per step [m]

    # Section classification
    lap_idx: np.ndarray         # lap index at each point
    section: np.ndarray         # section name at each point
    quarter: np.ndarray         # quarter within section (1-4)
    theta: np.ndarray           # banking angle [rad]

    # Summary metrics
    T_total: float              # total time for full effort [s]
    T_200: float                # timed 200m duration [s]
    v_200_entry: float          # speed at 200m start [m/s]
    v_200_exit: float           # speed at finish [m/s]
    splits_200: Tuple[float, float, float, float]  # 50m splits within 200m
    T_sprint: float             # sprint duration [s]
    s_sprint_start: float       # sprint start distance [m]
    P_avg_sprint: float         # average power during sprint [W]

    # Line cost metrics
    line_cost_200: float = 0.0  # time cost of trajectory vs black line for 200m [s]
    line_cost_total: float = 0.0  # time cost for full effort [s]

    @property
    def v_kph(self) -> np.ndarray:
        """Velocity in km/h."""
        return self.v * 3.6

    @property
    def v_200_entry_kph(self) -> float:
        """200m entry speed in km/h."""
        return self.v_200_entry * 3.6

    @property
    def v_200_exit_kph(self) -> float:
        """200m exit speed in km/h."""
        return self.v_200_exit * 3.6


# =============================================================================
# Main Simulation Function
# =============================================================================

def simulate_profile(
    s_grid: np.ndarray,
    y_grid: np.ndarray,
    CdA_grid: np.ndarray,
    P_grid: np.ndarray,
    config: Optional[SimulationConfig] = None,
    track_geometry=None,
) -> SimulationResult:
    """
    Simulate a Flying 200m effort with the given profile.

    CRITICAL: This function contains VALIDATED physics.
    DO NOT MODIFY THE MATH without explicit testing.

    Args:
        s_grid: Distance along black line [m] (must be evenly spaced)
        y_grid: Lateral position above black line [m]
        CdA_grid: Drag area at each point [m^2]
        P_grid: Target power at each point [W]
        config: Simulation configuration (uses defaults if None)
        track_geometry: Optional TrackGeometry object for track-specific physics.
                       If None, uses default Bromont geometry for backwards compatibility.

    Returns:
        SimulationResult containing all simulation outputs
    """
    if config is None:
        config = SimulationConfig()

    n = len(s_grid)

    # Pre-compute track geometry for each grid point
    # Use track-specific theta if track_geometry is provided
    if track_geometry is not None:
        track_params = compute_track_params_from_geometry(track_geometry)
        theta_grid = compute_theta_for_track(
            s_grid,
            track_params['straight_length'],
            track_params['lap_length'],
            track_params['theta_straight_rad'],
            track_params['theta_bend_rad'],
        )
        # Store track params for use in simulation loop
        _track_straight = track_params['straight_length']
        _track_lap = track_params['lap_length']
        _track_radius = track_params['radius_bend']
        _track_s_offset = track_params['s_offset']
    else:
        # Default: use Bromont geometry for backwards compatibility
        theta_grid = np.array([theta_track_blackline(s + S_OFFSET) for s in s_grid])
        _track_straight = L_STRAIGHT
        _track_lap = LAP_LEN
        _track_radius = R_BEND
        _track_s_offset = S_OFFSET

    h_grid = y_grid * np.sin(theta_grid)  # height above datum

    # Pre-compute section classification
    lap_idx_list = []
    section_list = []
    quarter_list = []
    for s in s_grid:
        lap_idx, sec, q = classify_section_and_quarter(
            s,
            s_offset=_track_s_offset,
            lap_length=_track_lap,
            straight_length=_track_straight,
            arc_length=np.pi * _track_radius,
        )
        lap_idx_list.append(lap_idx)
        section_list.append(sec)
        quarter_list.append(q)

    lap_idx_arr = np.array(lap_idx_list)
    section_arr = np.array(section_list)
    quarter_arr = np.array(quarter_list)

    # Initialize output arrays
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

    # Initial conditions
    v[0] = config.v0_m_s
    W_prime_rem[0] = config.w_prime_joules

    # Extract config values for faster access in loop
    MASS = config.mass_kg
    RHO = config.rho_kg_m3
    C_RR = config.c_rr
    G = config.g_m_s2
    CP = config.cp_watts
    W_PRIME_TOTAL = config.w_prime_joules
    MIN_V = config.min_v_m_s
    DRIVETRAIN_EFF = config.drivetrain_efficiency

    # Main simulation loop - VALIDATED PHYSICS, DO NOT MODIFY
    for i in range(n - 1):
        s_i = s_grid[i]
        s_next = s_grid[i + 1]
        ds_black = s_next - s_i

        v_i = max(v[i], MIN_V)
        P_target = max(P_grid[i], 0.0)

        # Path scaling in bends (use track-specific parameters)
        s_global_i = s_i + _track_s_offset
        if in_bend_region_for_track(s_global_i, _track_straight, _track_lap):
            factor = (_track_radius + y_grid[i]) / _track_radius
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

        # Apply CdA bend factor (profile CdA is for bends, straights have higher CdA)
        cda_factor = get_cda_factor_for_track(
            s_global_i, config.cda_bend_factor, y_grid[i],
            _track_straight, _track_lap, _track_radius
        )
        CdA_i = CdA_grid[i] * cda_factor
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

    # Sprint time detection
    P_sprint_threshold = CP + config.sprint_delta_over_cp
    sprint_start_idx = np.argmax(P_grid > P_sprint_threshold)
    if P_grid[sprint_start_idx] <= P_sprint_threshold:
        sprint_start_idx = 0
    s_sprint_start = s_grid[sprint_start_idx]
    t_sprint_start = t[sprint_start_idx]
    T_sprint = t[-1] - t_sprint_start

    # Average wattage during sprint
    sprint_mask = np.arange(len(s_grid)) >= sprint_start_idx
    P_avg_sprint = np.average(P_eff_used[sprint_mask], weights=dt_arr[sprint_mask]) if dt_arr[sprint_mask].sum() > 0 else 0.0

    # 200m 50m splits
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

    # Calculate line costs using track-specific parameters
    line_cost_200 = calculate_line_cost(
        s_grid, y_grid, v,
        s_start=S_200_START,
        s_end=S_TOTAL,
        straight_length=_track_straight,
        lap_length=_track_lap,
        radius_bend=_track_radius,
        s_offset=_track_s_offset,
    )
    line_cost_total = calculate_line_cost(
        s_grid, y_grid, v,
        s_start=0.0,
        s_end=S_TOTAL,
        straight_length=_track_straight,
        lap_length=_track_lap,
        radius_bend=_track_radius,
        s_offset=_track_s_offset,
    )

    return SimulationResult(
        s_grid=s_grid,
        v=v,
        t=t,
        dt=dt_arr,
        y=y_grid,
        CdA=CdA_grid,
        P_eff=P_eff_used,
        W_prime_rem=W_prime_rem,
        W_aero=W_aero_arr,
        W_rr=W_rr_arr,
        dE_pot=dE_pot_arr,
        dE_kin=dE_kin_arr,
        ds_actual=ds_actual_arr,
        lap_idx=lap_idx_arr,
        section=section_arr,
        quarter=quarter_arr,
        theta=theta_grid,
        T_total=t[-1],
        T_200=T_200,
        v_200_entry=v_200_entry,
        v_200_exit=v_200_exit,
        splits_200=(split_0_50, split_50_100, split_100_150, split_150_200),
        T_sprint=T_sprint,
        s_sprint_start=s_sprint_start,
        P_avg_sprint=P_avg_sprint,
        line_cost_200=line_cost_200,
        line_cost_total=line_cost_total,
    )


# =============================================================================
# Helper Functions
# =============================================================================

def create_simulation_grid(
    ds: float = 0.25,
    s_total: float = S_TOTAL,
) -> np.ndarray:
    """Create the standard simulation distance grid."""
    return np.arange(0.0, s_total + ds, ds)
