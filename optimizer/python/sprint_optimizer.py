"""
Sprint Optimizer for Flying 200m
Optimizes power delivery and CdA (seated vs standing) for the sprint phase.

Constraints:
- Sprint starts at s_m = 460 (configurable)
- Binary CdA: seated (better aero) or standing (higher power)
- Minimum 3 seconds in each position before switching
- Cumulative power constraint: average power over duration <= power curve value
- Standing power uses more aggressive curve depletion
"""

import numpy as np
import pandas as pd
from itertools import product
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import time


@dataclass
class PowerCurve:
    """
    Power curve: max sustainable AVERAGE power for each duration.

    The input defines average power for each duration (e.g., "1368W for 1s" means
    the average power over any 1-second window can be 1368W).

    This class pre-computes a smooth INSTANTANEOUS power curve such that when
    you follow it, the running average at any point exactly matches the input curve.
    """
    durations: List[int]  # seconds
    powers: List[float]   # watts (average sustainable for that duration)

    def __post_init__(self):
        """Pre-compute the smooth instantaneous power curve."""
        self._compute_instant_power_curve()

    def _compute_instant_power_curve(self):
        """
        Compute a smooth instantaneous power curve that matches the input average power.

        The key insight is that the input power curve has kinks at integer seconds,
        which causes oscillations in the instantaneous power. We solve this by:
        1. Using cubic spline to create a smooth version of the average power curve
        2. Computing instantaneous power from the smoothed curve

        The formula is: P_instant(t) = d/dt[E(t)] = d/dt[avg_curve(t) * t]
                                     = avg_curve(t) + t * avg_curve'(t)
        """
        from scipy.interpolate import UnivariateSpline

        self._dt = 0.01  # Resolution for instant power lookup
        self._max_t = 35.0  # Support up to 35 seconds
        n_points = int(self._max_t / self._dt) + 1

        # Create smooth spline for the average power curve
        # Use s (smoothing) parameter to create a smoother curve
        dur_arr = np.array(self.durations, dtype=float)
        pwr_arr = np.array(self.powers, dtype=float)

        # Cubic spline with light smoothing (s=100 balances smoothness vs accuracy)
        self._avg_spline = UnivariateSpline(dur_arr, pwr_arr, k=3, s=100)

        # Pre-compute instantaneous power using the smoothed curve
        self._instant_power = np.zeros(n_points)
        self._time_grid = np.linspace(0, self._max_t, n_points)

        cumulative_energy = 0.0

        for i in range(n_points):
            t = self._time_grid[i]
            t_next = t + self._dt

            # Target cumulative energy from smoothed average power curve
            t_lookup = max(t_next, 1.0)  # Clamp to curve domain
            t_lookup = min(t_lookup, 30.0)
            avg_power_at_next = float(self._avg_spline(t_lookup))
            target_energy = avg_power_at_next * t_next

            # Required instantaneous power
            P_instant = (target_energy - cumulative_energy) / self._dt

            # Clamp to reasonable bounds
            P_instant = max(P_instant, 0)  # No negative power
            P_instant = min(P_instant, self.powers[0] * 1.1)  # Cap at 110% of 1s power

            self._instant_power[i] = P_instant
            cumulative_energy += P_instant * self._dt

    def get_instant_power(self, sprint_time: float) -> float:
        """
        Get the instantaneous power for a given time into the sprint.

        This is the power that should be applied at this instant such that
        the running average matches the power curve.
        """
        if sprint_time < 0:
            sprint_time = 0
        if sprint_time >= self._max_t:
            sprint_time = self._max_t - self._dt

        # Linear interpolation in the pre-computed array
        idx = sprint_time / self._dt
        idx_low = int(idx)
        idx_high = min(idx_low + 1, len(self._instant_power) - 1)
        frac = idx - idx_low

        return self._instant_power[idx_low] * (1 - frac) + self._instant_power[idx_high] * frac

    def get_max_power_for_duration(self, duration_s: float) -> float:
        """
        Interpolate max AVERAGE power for a given duration.
        Returns the max average power sustainable for that duration.
        """
        if duration_s <= 0:
            return self.powers[0] if self.powers else 0

        # Linear interpolation between known points
        for i in range(len(self.durations) - 1):
            if self.durations[i] <= duration_s <= self.durations[i + 1]:
                t1, t2 = self.durations[i], self.durations[i + 1]
                p1, p2 = self.powers[i], self.powers[i + 1]
                # Linear interpolation
                return p1 + (p2 - p1) * (duration_s - t1) / (t2 - t1)

        # Beyond curve - use last value
        if duration_s > self.durations[-1]:
            return self.powers[-1]

        return self.powers[0]


@dataclass
class OptimizerConfig:
    """Configuration for the optimizer"""
    sprint_start_s: float = 460.0       # Distance where sprint/optimization begins
    s_total: float = 895.0              # Total effort distance
    ds: float = 0.25                    # Grid step size
    min_position_hold_s: float = 3.0    # Minimum seconds in seated/standing

    # Constraint: must be seated for final timed section + buffer before it
    # 200m timed + 30m buffer = 230m before finish must be seated
    seated_zone_before_finish: float = 230.0  # Distance before finish that MUST be seated

    # Power drop limit: max allowed drop from previous block's power (e.g., 0.15 = 15%)
    # This prevents unrealistic power drops to 0 between position changes
    max_power_drop_fraction: float = 0.15

    # Pattern time resolution: granularity for position patterns (0.5 = half-second, 1.0 = full second)
    pattern_time_resolution: float = 0.5

    # Minimum power floor as fraction of baseline profile power (e.g., 0.9 = 90%)
    # Prevents optimizer from outputting unrealistically low power
    min_power_pct: float = 0.9

    # Rider parameters
    mass: float = 92.0
    rho: float = 1.18
    c_rr: float = 0.002
    g: float = 9.81

    # CdA values
    cda_seated: float = 0.24
    cda_standing: float = 0.38

    # Track geometry
    lap_len: float = 250.0
    l_straight: float = 59.0
    theta_straight_deg: float = 12.0
    theta_bend_deg: float = 42.0
    trans_len: float = 5.0


class SprintOptimizer:
    """
    Optimizer for the sprint phase of a Flying 200m effort.

    Finds optimal power delivery and CdA switching strategy to minimize time.
    """

    def __init__(self, config: OptimizerConfig,
                 seated_power_curve: PowerCurve,
                 standing_power_curve: PowerCurve,
                 windup_profile: pd.DataFrame):
        """
        Initialize the optimizer.

        Args:
            config: Optimizer configuration
            seated_power_curve: Power curve when seated
            standing_power_curve: Power curve when standing
            windup_profile: DataFrame with columns [s_m, y_m, CdA_m2, P_W] for wind-up phase
        """
        self.config = config
        self.seated_curve = seated_power_curve
        self.standing_curve = standing_power_curve
        self.windup_profile = windup_profile

        # Precompute track geometry
        self.r_bend = (config.lap_len - 2.0 * config.l_straight) / (2.0 * np.pi)
        self.arc_len = np.pi * self.r_bend
        self.theta_straight = np.deg2rad(config.theta_straight_deg)
        self.theta_bend = np.deg2rad(config.theta_bend_deg)
        self.s_offset = config.l_straight + self.arc_len + 0.5 * config.l_straight

        # Build simulation grid
        self.s_grid = np.arange(0.0, config.s_total + config.ds, config.ds)
        self.theta_grid = np.array([self._theta_track(s + self.s_offset) for s in self.s_grid])

        # Find sprint start index
        self.sprint_start_idx = np.searchsorted(self.s_grid, config.sprint_start_s)

        # Interpolate wind-up profile onto grid
        self._setup_windup_grids()

    def _theta_bend_transition(self, s_in_bend: float) -> float:
        """Banking angle in bend with transition"""
        if self.config.trans_len > 0:
            if s_in_bend < self.config.trans_len:
                f = s_in_bend / self.config.trans_len
                return self.theta_straight + f * (self.theta_bend - self.theta_straight)
            elif s_in_bend > self.arc_len - self.config.trans_len:
                f = (self.arc_len - s_in_bend) / self.config.trans_len
                return self.theta_straight + f * (self.theta_bend - self.theta_straight)
        return self.theta_bend

    def _theta_track(self, s_global: float) -> float:
        """Banking angle at global position"""
        s_mod = s_global % self.config.lap_len
        if s_mod < self.config.l_straight:
            return self.theta_straight
        elif s_mod < self.config.l_straight + self.arc_len:
            return self._theta_bend_transition(s_mod - self.config.l_straight)
        elif s_mod < self.config.l_straight + self.arc_len + self.config.l_straight:
            return self.theta_straight
        else:
            return self._theta_bend_transition(s_mod - (self.config.l_straight + self.arc_len + self.config.l_straight))

    def _in_bend(self, s_global: float) -> bool:
        """Check if position is in a bend"""
        s_mod = s_global % self.config.lap_len
        if s_mod < self.config.l_straight:
            return False
        elif s_mod < self.config.l_straight + self.arc_len:
            return True
        elif s_mod < self.config.l_straight + self.arc_len + self.config.l_straight:
            return False
        return True

    def _setup_windup_grids(self):
        """Interpolate wind-up profile onto simulation grid"""
        s_break = self.windup_profile['s_m'].to_numpy()
        y_break = self.windup_profile['y_m'].to_numpy()
        cda_break = self.windup_profile['CdA_m2'].to_numpy()
        p_break = self.windup_profile['P_W'].to_numpy()

        self.y_grid = np.interp(self.s_grid, s_break, y_break)
        self.cda_windup_grid = np.interp(self.s_grid, s_break, cda_break)
        self.p_windup_grid = np.interp(self.s_grid, s_break, p_break)

    def _simulate_sprint(self,
                         position_pattern: List[bool],  # True = standing, False = seated
                         power_strategy: str = 'from_profile',
                         cda_strategy: str = 'from_pattern') -> Dict:
        """
        Simulate a sprint with given position pattern.

        Args:
            position_pattern: List of booleans for each second of sprint (True=standing)
            power_strategy:
                'from_profile' - Use power values from CSV profile (default)
                'power_curve' - Use power curve constraints
            cda_strategy:
                'from_pattern' - Use CdA based on position pattern (default)
                'from_profile' - Use CdA values from CSV profile

        Returns:
            Dictionary with simulation results
        """
        n = len(self.s_grid)
        cfg = self.config

        # Initialize arrays
        v = np.zeros(n)
        t = np.zeros(n)
        p_actual = np.zeros(n)
        cda_actual = np.zeros(n)
        is_standing = np.zeros(n, dtype=bool)

        # Run wind-up phase (before sprint start)
        v[0] = 5.0  # Initial speed

        for i in range(self.sprint_start_idx):
            s_i = self.s_grid[i]
            v_i = max(v[i], 0.1)

            # Wind-up uses profile values
            P_eff = self.p_windup_grid[i]
            CdA_i = self.cda_windup_grid[i]
            y_i = self.y_grid[i]

            p_actual[i] = P_eff
            cda_actual[i] = CdA_i

            # Physics step
            v[i + 1], dt = self._physics_step(i, v_i, P_eff, CdA_i, y_i)
            t[i + 1] = t[i] + dt

        # Sprint phase - ENERGY BUDGET APPROACH
        # Key insight: The power curve defines AVERAGE power sustainable over a duration,
        # NOT instantaneous power. So curve(t) means: average power over t seconds must be <= curve(t).
        #
        # This means: max_energy_at_time_t = curve(t) * t
        #
        # To enforce this, we track cumulative energy used and compute instantaneous power
        # such that the cumulative average never exceeds the curve.
        #
        # Additionally, we track per-block energy (resets on position change) to also
        # respect the position-specific power curve.

        sprint_start_time = t[self.sprint_start_idx]
        sprint_energy_seated = 0.0   # Energy used while seated (for reporting)
        sprint_energy_standing = 0.0  # Energy used while standing (for reporting)

        # Energy tracking
        # cumulative_energy: Total energy used in sprint (for reporting)
        # block_energy: Energy used in current position block (for block budget)
        # seated_equivalent_time: Converts actual sprint to "seated equivalent" time
        #   - 1s of seated effort = 1s of seated equivalent
        #   - 1s of standing at higher power = more than 1s of seated equivalent
        cumulative_energy = 0.0
        block_energy = 0.0
        seated_equivalent_energy = 0.0  # Track as if everything was seated-level effort

        # Per-block tracking
        current_position_start_time = sprint_start_time
        current_is_standing = position_pattern[0] if position_pattern else False
        previous_block_end_power = None  # Power at end of previous block (for drop constraint at transitions)

        for i in range(self.sprint_start_idx, n - 1):
            s_i = self.s_grid[i]
            v_i = max(v[i], 0.1)
            y_i = self.y_grid[i]

            # Determine time into sprint
            sprint_time = t[i] - sprint_start_time

            # Get position (standing/seated) for this time step
            # Pattern is indexed by time step (resolution-based), not seconds
            resolution = cfg.pattern_time_resolution
            pattern_idx = int(sprint_time / resolution)

            if pattern_idx < len(position_pattern):
                target_standing = position_pattern[pattern_idx]
            else:
                target_standing = position_pattern[-1] if position_pattern else False

            # CONSTRAINT: Must be seated in final zone (timed 200m + 30m buffer)
            seated_zone_start = cfg.s_total - cfg.seated_zone_before_finish
            if s_i >= seated_zone_start:
                target_standing = False  # Force seated in final zone

            # Check if we can switch (3 second minimum hold)
            time_in_position = t[i] - current_position_start_time
            if target_standing != current_is_standing:
                if time_in_position >= cfg.min_position_hold_s:
                    # Record power at end of previous block before switching
                    if i > self.sprint_start_idx:
                        previous_block_end_power = p_actual[i - 1]
                    # Reset block tracking for new position
                    current_is_standing = target_standing
                    current_position_start_time = t[i]
                    block_energy = 0.0  # Reset block energy on position change

            is_standing[i] = current_is_standing

            # Set CdA based on strategy
            if cda_strategy == 'from_profile':
                # Use CdA directly from CSV profile
                CdA_i = self.cda_windup_grid[i]
            else:
                # Use CdA based on position pattern
                CdA_i = cfg.cda_standing if current_is_standing else cfg.cda_seated
            cda_actual[i] = CdA_i

            # Determine power based on strategy
            if power_strategy == 'from_profile':
                # Use power directly from the CSV profile
                P_eff = self.p_windup_grid[i]
            else:
                # ENERGY BUDGET MODEL (Position-Aware)
                #
                # The power curve defines AVERAGE power sustainable over duration t.
                # Two constraints apply:
                # 1. GLOBAL: cumulative_energy <= standing_curve(t) * t (absolute max)
                # 2. POSITION: Also respect current position's curve
                #
                # For mixed patterns, after switching from standing to seated,
                # the position curve applies to time-in-current-position, but the
                # global budget still uses total sprint time.

                # Estimate dt for this step
                ds_step = self.s_grid[i + 1] - self.s_grid[i] if i + 1 < len(self.s_grid) else cfg.ds
                dt_est = ds_step / max(v_i, 1.0)

                sprint_time_next = sprint_time + dt_est
                sprint_time_next = max(sprint_time_next, 0.001)

                # Time in current position block
                time_in_block = t[i] - current_position_start_time
                time_in_block_next = time_in_block + dt_est

                # GLOBAL BUDGET: Standing curve is absolute max (never exceed)
                if sprint_time_next <= 30.0:
                    standing_max_avg = self.standing_curve.get_max_power_for_duration(sprint_time_next)
                else:
                    curve_30 = self.standing_curve.get_max_power_for_duration(30.0)
                    standing_max_avg = curve_30 * (30.0 / sprint_time_next) ** 0.05

                max_global_energy = standing_max_avg * sprint_time_next
                global_budget_power = (max_global_energy - cumulative_energy) / dt_est if dt_est > 0 else 0
                global_budget_power = max(global_budget_power, 0)

                # POSITION BUDGET: Also respect current position's curve for time in block
                if current_is_standing:
                    position_curve = self.standing_curve
                else:
                    position_curve = self.seated_curve

                time_in_block_clamped = min(time_in_block_next, 30.0)
                position_max_avg = position_curve.get_max_power_for_duration(max(time_in_block_clamped, 0.1))
                max_block_energy = position_max_avg * time_in_block_next
                position_budget_power = (max_block_energy - block_energy) / dt_est if dt_est > 0 else 0
                position_budget_power = max(position_budget_power, 0)

                # Use the minimum of both budgets - this is the PRIMARY constraint
                budget_power = min(global_budget_power, position_budget_power)

                # The budget power is the power that exactly meets the constraint
                # We use it directly (not the pre-computed instant curve) to ensure
                # the average never exceeds the curve, even with variable timesteps
                P_eff = budget_power

                # Cap at 1s power for current position (absolute instantaneous max)
                P_max_instant = position_curve.powers[0]
                P_eff = min(P_eff, P_max_instant)

                # Apply floor constraint: minimum power as percentage of baseline profile
                # This prevents unrealistically low power outputs
                baseline_power = self.p_windup_grid[i]
                min_power = baseline_power * cfg.min_power_pct
                P_eff = max(P_eff, min_power)

                P_eff = max(P_eff, 0)  # No negative power

            p_actual[i] = P_eff

            # Physics step
            v[i + 1], dt = self._physics_step(i, v_i, P_eff, CdA_i, y_i)
            t[i + 1] = t[i] + dt

            # Update energy tracking (for energy budget and reporting)
            energy_used = P_eff * dt
            cumulative_energy += energy_used
            block_energy += energy_used
            seated_equivalent_energy += energy_used  # Actual energy used adds to fatigue
            if current_is_standing:
                sprint_energy_standing += energy_used
            else:
                sprint_energy_seated += energy_used

        # Copy last values
        p_actual[-1] = p_actual[-2]
        cda_actual[-1] = cda_actual[-2]
        is_standing[-1] = is_standing[-2]

        # Calculate 200m time
        s_200_start = cfg.s_total - 200.0
        t_200_start = np.interp(s_200_start, self.s_grid, t)
        t_200_end = t[-1]
        T_200 = t_200_end - t_200_start

        return {
            'v': v,
            't': t,
            'p_actual': p_actual,
            'cda_actual': cda_actual,
            'is_standing': is_standing,
            'T_total': t[-1],
            'T_200': T_200,
            'T_sprint': t[-1] - sprint_start_time,
            'v_200_entry': np.interp(s_200_start, self.s_grid, v),
            'v_200_exit': v[-1],
            'sprint_energy_standing': sprint_energy_standing,
            'sprint_energy_seated': sprint_energy_seated,
            'position_pattern': position_pattern,
        }

    def _physics_step(self, i: int, v_i: float, P_eff: float, CdA_i: float, y_i: float) -> Tuple[float, float]:
        """
        Single physics step.
        Returns (v_next, dt)
        """
        cfg = self.config
        s_i = self.s_grid[i]
        s_next = self.s_grid[i + 1]
        ds_black = s_next - s_i

        # Path scaling in bends
        s_global_i = s_i + self.s_offset
        if self._in_bend(s_global_i):
            factor = (self.r_bend + y_i) / self.r_bend
        else:
            factor = 1.0

        ds_actual = ds_black * factor
        dt = ds_actual / v_i

        theta_i = self.theta_grid[i]

        # Forces
        F_aero = 0.5 * cfg.rho * CdA_i * v_i**2
        F_rr = cfg.c_rr * cfg.mass * cfg.g * np.cos(theta_i)

        # Height change
        h_i = y_i * np.sin(theta_i)
        h_next = self.y_grid[i + 1] * np.sin(self.theta_grid[i + 1]) if i + 1 < len(self.y_grid) else h_i
        dh = h_next - h_i
        dE_pot = cfg.mass * cfg.g * dh

        # Energy balance
        W_rider = P_eff * dt
        W_resist = (F_aero + F_rr) * ds_actual
        dE_kin = W_rider - W_resist - dE_pot

        E_kin_i = 0.5 * cfg.mass * v_i**2
        E_kin_next = max(E_kin_i + dE_kin, 0.0)
        v_next = np.sqrt(2.0 * E_kin_next / cfg.mass)

        return v_next, dt

    def validate_power_sequence(self, t: np.ndarray, p_actual: np.ndarray,
                                 check_interval: float = 1.0) -> Tuple[bool, List]:
        """
        Validate that the power sequence respects cumulative power curve constraints.

        Two constraints are checked:
        1. Peak power: No instantaneous power can exceed the 1-second max
        2. Running average: At any point t seconds into sprint, avg power must not
           exceed the power curve limit for duration t

        Args:
            t: Time array from simulation
            p_actual: Power array from simulation
            check_interval: How often to check constraints (seconds)

        Returns:
            (is_valid, violations) where violations is list of (time, avg_power, limit, excess)
        """
        violations = []
        cfg = self.config

        # Find sprint start
        sprint_start_time = t[self.sprint_start_idx]

        # Calculate dt array for sprint phase
        sprint_t = t[self.sprint_start_idx:]
        sprint_p = p_actual[self.sprint_start_idx:]

        if len(sprint_t) < 2:
            return True, []

        dt_arr = np.diff(sprint_t)
        p_arr = sprint_p[:-1]  # Power for each interval

        cumulative_time = 0.0
        cumulative_energy = 0.0
        last_check_time = 0.0

        # 1s max power from standing curve (absolute ceiling)
        peak_power = self.standing_curve.powers[0]

        for i, (power, dt) in enumerate(zip(p_arr, dt_arr)):
            # Check 1: Peak power constraint
            if power > peak_power * 1.01:  # 1% tolerance
                excess = power - peak_power
                violations.append((cumulative_time, power, peak_power, excess, 'peak'))

            cumulative_energy += power * dt
            cumulative_time += dt

            # Check 2: Running average at specified intervals
            if cumulative_time - last_check_time >= check_interval:
                # Get the max average power allowed for this duration
                if cumulative_time <= 30.0:
                    max_power_at_duration = self.standing_curve.get_max_power_for_duration(cumulative_time)
                else:
                    # Extrapolate beyond 30s
                    curve_30 = self.standing_curve.get_max_power_for_duration(30.0)
                    max_power_at_duration = curve_30 * (30.0 / cumulative_time) ** 0.05

                avg_power = cumulative_energy / cumulative_time

                if avg_power > max_power_at_duration * 1.01:  # 1% tolerance
                    excess = avg_power - max_power_at_duration
                    violations.append((cumulative_time, avg_power, max_power_at_duration, excess, 'avg'))

                last_check_time = cumulative_time

        # Check if any violations are critical (> 3% over)
        is_valid = all(v[3] / v[2] < 0.03 for v in violations) if violations else True

        return is_valid, violations

    def generate_position_patterns(self, sprint_duration_s: int = 30) -> List[List[bool]]:
        """
        Generate all valid position patterns respecting 3-second minimum hold.

        Returns list of patterns where True = standing, False = seated.
        """
        patterns = []

        # We'll generate patterns by specifying transition points
        # Minimum 3 seconds between transitions
        # Start with either seated or standing

        def generate_recursive(current_pattern: List[bool],
                              current_second: int,
                              current_state: bool,
                              state_start: int):
            """Recursively generate patterns"""
            if current_second >= sprint_duration_s:
                patterns.append(current_pattern.copy())
                return

            time_in_state = current_second - state_start

            # Option 1: Stay in current state
            current_pattern.append(current_state)
            generate_recursive(current_pattern, current_second + 1, current_state, state_start)
            current_pattern.pop()

            # Option 2: Switch state (if allowed)
            if time_in_state >= 3:
                current_pattern.append(not current_state)
                generate_recursive(current_pattern, current_second + 1, not current_state, current_second)
                current_pattern.pop()

        # Start standing
        generate_recursive([True], 1, True, 0)
        # Start seated
        generate_recursive([False], 1, False, 0)

        return patterns

    def _calculate_variable_phase_duration(self) -> float:
        """Calculate how many seconds the variable phase lasts.

        The variable phase is from sprint start to the seated zone.
        After that, position is forced to seated.
        """
        cfg = self.config
        seated_zone_start = cfg.s_total - cfg.seated_zone_before_finish

        # Use the initialized grids and a simple simulation to estimate timing
        # This is approximate - based on typical speeds through the variable zone
        variable_distance = seated_zone_start - cfg.sprint_start_s  # 665 - 460 = 205m

        # Estimate average speed through variable zone (~55-65 km/h = 15-18 m/s)
        # Use conservative estimate (faster = less time = shorter variable phase)
        avg_speed = 14.0  # m/s (about 50 km/h - conservative)
        variable_time = variable_distance / avg_speed

        return variable_time

    def generate_smart_patterns(self, sprint_duration_s: float = 30.0, max_transitions: int = 6) -> List[List[bool]]:
        """
        Generate ALL valid position patterns respecting minimum hold constraint.

        OPTIMIZATION: Only generates patterns for the "variable phase" (sprint start to
        seated zone), then pads with seated for the rest. Patterns after the seated zone
        don't matter since position is forced to seated anyway.

        Patterns are generated at the configured time resolution (e.g., 0.5s intervals).

        Args:
            sprint_duration_s: Total sprint duration in seconds
            max_transitions: Maximum number of position changes allowed
        """
        cfg = self.config
        resolution = cfg.pattern_time_resolution  # e.g., 0.5 for half-second steps
        min_hold_steps = int(cfg.min_position_hold_s / resolution)  # Min steps to hold

        # Calculate steps for variable phase and total
        variable_phase_s = self._calculate_variable_phase_duration()
        variable_phase_s = min(variable_phase_s, sprint_duration_s)
        variable_steps = int(np.ceil(variable_phase_s / resolution))
        total_steps = int(sprint_duration_s / resolution)
        forced_seated_steps = total_steps - variable_steps

        patterns = []

        def generate_recursive(current_pattern: List[bool],
                               remaining_steps: int,
                               current_state: bool,  # True = standing
                               transitions_used: int):
            """
            Recursively build patterns by choosing segment durations.

            Args:
                current_pattern: Pattern built so far (each element = 1 time step)
                remaining_steps: Steps left to fill in variable phase
                current_state: Current position (True=standing, False=seated)
                transitions_used: Number of transitions already used
            """
            if remaining_steps == 0:
                # Complete pattern for variable phase, pad with seated
                full_pattern = current_pattern + [False] * forced_seated_steps
                patterns.append(full_pattern)
                return

            if remaining_steps < 0:
                return  # Invalid

            # Option 1: Stay in current state for remaining duration (end variable phase)
            if remaining_steps >= min_hold_steps:
                pattern_end = current_pattern + [current_state] * remaining_steps + [False] * forced_seated_steps
                patterns.append(pattern_end)

            # Option 2: Stay in current state for min_hold to (remaining - min_hold) steps, then switch
            if transitions_used < max_transitions:
                # We need at least min_hold for current segment AND min_hold for next segment
                max_current_steps = remaining_steps - min_hold_steps

                for duration_steps in range(min_hold_steps, max_current_steps + 1):
                    new_pattern = current_pattern + [current_state] * duration_steps
                    new_remaining = remaining_steps - duration_steps
                    generate_recursive(new_pattern, new_remaining, not current_state, transitions_used + 1)

        # Start with standing
        generate_recursive([], variable_steps, True, 0)

        # Start with seated
        generate_recursive([], variable_steps, False, 0)

        # Remove duplicates (shouldn't be any but just in case)
        unique_patterns = []
        seen = set()
        for p in patterns:
            key = tuple(p)
            if key not in seen:
                seen.add(key)
                unique_patterns.append(p)

        return unique_patterns

    def optimize(self, use_smart_patterns: bool = True,
                 sprint_duration_s: int = 30,
                 power_strategy: str = 'power_curve',
                 sample_size: Optional[int] = None,
                 verbose: bool = True,
                 progress_callback: Optional[callable] = None) -> Dict:
        """
        Run the optimization to find best position pattern.

        Args:
            use_smart_patterns: If True, use reduced pattern set for faster optimization
            sprint_duration_s: Duration of sprint phase in seconds
            power_strategy: 'power_curve' to use input power curves, 'from_profile' to use CSV power
            sample_size: If set, randomly sample this many patterns instead of testing all
            verbose: Print progress
            progress_callback: Optional callback(current, total, best_time, pattern_desc) for progress updates

        Returns:
            Dictionary with best result and all tested results
        """
        import random
        start_time = time.time()

        # Generate patterns
        if use_smart_patterns:
            patterns = self.generate_smart_patterns(sprint_duration_s)
        else:
            patterns = self.generate_position_patterns(sprint_duration_s)

        total_patterns = len(patterns)

        # Random sampling if requested
        if sample_size and sample_size < len(patterns):
            patterns = random.sample(patterns, sample_size)

        if verbose:
            if sample_size:
                print(f"Testing {len(patterns)} random patterns (from {total_patterns} total)...")
            else:
                print(f"Testing {len(patterns)} position patterns...")
            print(f"Power strategy: {power_strategy}")

        results = []
        best_result = None
        best_time = float('inf')

        valid_count = 0
        for i, pattern in enumerate(patterns):
            result = self._simulate_sprint(pattern, power_strategy=power_strategy)
            result['pattern_idx'] = i
            # Use actual executed pattern (accounts for seated zone override)
            result['pattern_description'] = self._describe_actual_pattern(result['is_standing'], result['t'])

            # Validate power sequence against cumulative constraints
            is_valid, violations = self.validate_power_sequence(result['t'], result['p_actual'])
            result['is_valid'] = is_valid
            result['violations'] = violations

            results.append(result)

            # Only consider valid patterns for best result
            if is_valid and result['T_200'] < best_time:
                best_time = result['T_200']
                best_result = result
                valid_count += 1
            elif is_valid:
                valid_count += 1

            # Call progress callback if provided
            if progress_callback and (i + 1) % 10 == 0:
                progress_callback(i + 1, len(patterns), best_time, best_result['pattern_description'] if best_result else None)

            if verbose and (i + 1) % 50 == 0:
                print(f"  Tested {i + 1}/{len(patterns)}, valid: {valid_count}, best 200m time: {best_time:.3f}s")

        elapsed = time.time() - start_time

        if verbose:
            print(f"\nOptimization complete in {elapsed:.2f}s")
            print(f"Best 200m time: {best_time:.3f}s")
            print(f"Best pattern: {best_result['pattern_description']}")

        return {
            'best_result': best_result,
            'all_results': results,
            'elapsed_time': elapsed,
            'num_patterns': len(patterns),
        }

    def _describe_pattern(self, pattern: List[bool]) -> str:
        """Create human-readable description of a position pattern (input pattern)"""
        if not pattern:
            return "Empty"

        resolution = self.config.pattern_time_resolution

        # Find transitions
        transitions = []
        current = pattern[0]
        start = 0

        for i, val in enumerate(pattern):
            if val != current:
                start_time = start * resolution
                end_time = i * resolution
                transitions.append((start_time, end_time, 'Standing' if current else 'Seated'))
                current = val
                start = i
        # Add final segment
        start_time = start * resolution
        end_time = len(pattern) * resolution
        transitions.append((start_time, end_time, 'Standing' if current else 'Seated'))

        # Format with appropriate precision (no decimals if integer, otherwise 1 decimal)
        def fmt(x):
            return f"{x:.0f}" if x == int(x) else f"{x:.1f}"

        parts = [f"{t[2]}({fmt(t[0])}-{fmt(t[1])}s)" for t in transitions]
        return " -> ".join(parts)

    def _describe_actual_pattern(self, is_standing: np.ndarray, t: np.ndarray) -> str:
        """Create human-readable description of the ACTUAL executed pattern

        This accounts for seated zone overrides and min hold constraints.
        """
        cfg = self.config
        sprint_start_time = t[self.sprint_start_idx]

        # Find transitions in actual is_standing array (sprint phase only)
        transitions = []
        current = is_standing[self.sprint_start_idx]
        start_time = 0.0

        for i in range(self.sprint_start_idx, len(is_standing)):
            time_into_sprint = t[i] - sprint_start_time
            if is_standing[i] != current:
                transitions.append((start_time, time_into_sprint, 'Standing' if current else 'Seated'))
                current = is_standing[i]
                start_time = time_into_sprint

        # Add final segment
        final_time = t[-1] - sprint_start_time
        transitions.append((start_time, final_time, 'Standing' if current else 'Seated'))

        # Format with rounded times
        parts = [f"{t[2]}({t[0]:.0f}-{t[1]:.0f}s)" for t in transitions]
        return " -> ".join(parts)


def create_test_power_curves() -> Tuple[PowerCurve, PowerCurve]:
    """Create power curves from real data"""
    durations = list(range(1, 31))  # 1-30 seconds

    # Seated power curve - extracted from FIT file indices 2582-2606 and 2977-3001
    seated_powers = [
        1368, 1249, 1198, 1183, 1164, 1146, 1126, 1117, 1105, 1100,  # 1-10s
        1089, 1072, 1058, 1045, 1028, 1015, 1002, 997, 986, 971,     # 11-20s
        957, 947, 935, 923, 912, 900, 888, 877, 865, 853             # 21-30s
    ]

    # Standing power curve - real data provided by user
    # Raw data: 1s=1514, 2s=1443, 3s=1434, 4s=1411, 5s=1373, 6s=1353, 7s=1324,
    #           8s=1294, 9s=1260, 10s=1227, 11s=1182, 12s=1131, 13s=1125, 14s=1104,
    #           15s=1081, 20s=1000, 25s=931, 30s=887
    # Interpolated for 16-19s, 21-24s, 26-29s
    standing_powers = [
        1514, 1443, 1434, 1411, 1373, 1353, 1324, 1294, 1260, 1227,  # 1-10s
        1182, 1131, 1125, 1104, 1081,                                 # 11-15s
        1065, 1049, 1032, 1016, 1000,                                 # 16-20s (interpolated 16-19)
        986, 972, 958, 945, 931,                                      # 21-25s (interpolated 21-24)
        922, 913, 904, 896, 887                                       # 26-30s (interpolated 26-29)
    ]

    return (
        PowerCurve(durations=durations, powers=seated_powers),
        PowerCurve(durations=durations, powers=standing_powers)
    )


if __name__ == "__main__":
    # Test the optimizer
    print("=" * 60)
    print("Sprint Optimizer Test")
    print("=" * 60)

    # Create test power curves
    seated_curve, standing_curve = create_test_power_curves()

    print("\nSeated Power Curve:")
    for d, p in zip(seated_curve.durations, seated_curve.powers):
        print(f"  {d:2d}s: {p:.0f}W")

    print("\nStanding Power Curve:")
    for d, p in zip(standing_curve.durations, standing_curve.powers):
        print(f"  {d:2d}s: {p:.0f}W")

    # Load wind-up profile
    try:
        windup_profile = pd.read_csv("profile_f200.csv")
        print(f"\nLoaded wind-up profile with {len(windup_profile)} rows")
    except FileNotFoundError:
        print("\nNo profile_f200.csv found, creating dummy profile")
        # Create dummy profile
        s_vals = np.arange(0, 900, 10)
        windup_profile = pd.DataFrame({
            's_m': s_vals,
            'y_m': np.full_like(s_vals, 5.0, dtype=float),
            'CdA_m2': np.full_like(s_vals, 0.24, dtype=float),
            'P_W': np.where(s_vals < 460, 200, 1000),
        })

    # Create optimizer
    config = OptimizerConfig()
    optimizer = SprintOptimizer(
        config=config,
        seated_power_curve=seated_curve,
        standing_power_curve=standing_curve,
        windup_profile=windup_profile
    )

    # Run optimization
    print("\n" + "=" * 60)
    print("Running Optimization...")
    print("=" * 60)

    result = optimizer.optimize(use_smart_patterns=True, power_strategy='power_curve', verbose=True)

    # Print top 5 results
    print("\n" + "=" * 60)
    print("Top 5 Results:")
    print("=" * 60)

    sorted_results = sorted(result['all_results'], key=lambda x: x['T_200'])
    for i, r in enumerate(sorted_results[:5]):
        print(f"{i+1}. T_200={r['T_200']:.3f}s | {r['pattern_description']}")
