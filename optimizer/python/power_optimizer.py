"""
Power Optimizer Module for Flying 200m Simulation

This module provides optimization capabilities to find the optimal power delivery
strategy over the final ~30 seconds of a Flying 200m effort, subject to power
curve constraints.

The optimizer uses random sampling to explore power multipliers for each
track section that minimize total time while respecting physiological limits.
"""

import time as _time

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from scipy.optimize import minimize


class PowerCurveConstraint:
    """
    Manages power curve constraints and validates power delivery sequences.

    The key constraint is: at any point t seconds into the effort, the average
    power from the start to that point must not exceed the power curve limit
    for duration t.
    """

    def __init__(self, power_curve_dict, check_interval=1.0):
        """
        Args:
            power_curve_dict: Dict mapping duration (seconds) to max power (watts)
                             e.g., {1: 1500, 2: 1400, 5: 1200, 10: 1000, 30: 800}
            check_interval: How often to check constraints (seconds)
        """
        self.power_curve = power_curve_dict
        self.check_interval = check_interval

        # Store the absolute peak power (1s max) - no instantaneous power can exceed this
        self.peak_power = power_curve_dict.get(1, float('inf')) if power_curve_dict else float('inf')

        # Create interpolator for any duration
        if power_curve_dict:
            durations = sorted(power_curve_dict.keys())
            powers = [power_curve_dict[d] for d in durations]
            # Extrapolate beyond 30s using the 30s value
            self.interpolator = interp1d(
                durations, powers,
                kind='linear',
                fill_value=(powers[0], powers[-1]),  # Extrapolate with edge values
                bounds_error=False
            )
        else:
            self.interpolator = None

    def get_max_power_for_duration(self, duration_s):
        """Get the maximum sustainable power for a given duration."""
        if self.interpolator is None:
            return float('inf')
        return float(self.interpolator(duration_s))

    def validate_power_sequence(self, power_array, dt_array):
        """
        Validate that a power sequence respects the power curve constraints.

        Two constraints are checked:
        1. Peak power: No instantaneous power can exceed the 1-second max (absolute ceiling)
        2. Running average: At any point t seconds into the effort, the average power
           from the start to that point must not exceed the power curve limit for duration t.

        Args:
            power_array: Array of power values (W) at each time step
            dt_array: Array of time deltas (s) for each step

        Returns:
            (is_valid, violations) where violations is a list of
            (time, avg_power, limit, excess, violation_type) tuples
        """
        if self.interpolator is None:
            return True, []

        violations = []
        cumulative_time = 0.0
        cumulative_energy = 0.0
        last_check_time = 0.0

        for i, (power, dt) in enumerate(zip(power_array, dt_array)):
            # Check 1: Peak power constraint - no power can exceed 1s max (absolute ceiling)
            if power > self.peak_power:
                excess = power - self.peak_power
                violations.append((cumulative_time, power, self.peak_power, excess, 'peak'))

            cumulative_energy += power * dt
            cumulative_time += dt

            # Check 2: Running average at specified intervals
            if cumulative_time - last_check_time >= self.check_interval:
                # Get the max average power allowed for this duration
                max_power_at_duration = self.get_max_power_for_duration(cumulative_time)

                # Running average constraint: avg power from start to now must be <= power curve
                avg_power = cumulative_energy / cumulative_time
                if avg_power > max_power_at_duration:
                    excess = avg_power - max_power_at_duration
                    violations.append((cumulative_time, avg_power, max_power_at_duration, excess, 'avg'))

                last_check_time = cumulative_time

        # Final check on running average
        if cumulative_time > 0:
            max_power_at_duration = self.get_max_power_for_duration(cumulative_time)
            avg_power = cumulative_energy / cumulative_time
            if avg_power > max_power_at_duration:
                excess = avg_power - max_power_at_duration
                if not violations or violations[-1][0] != cumulative_time:
                    violations.append((cumulative_time, avg_power, max_power_at_duration, excess, 'avg'))

        return len(violations) == 0, violations


class SectionDefinition:
    """Represents a track section for optimization."""

    def __init__(self, name, start_s, end_s, base_power):
        self.name = name
        self.start_s = start_s
        self.end_s = end_s
        self.base_power = base_power
        self.power_mult = 1.0  # Default multiplier

    def get_power(self):
        """Get the adjusted power for this section."""
        return self.base_power * self.power_mult

    def __repr__(self):
        return f"Section({self.name}, {self.start_s:.0f}-{self.end_s:.0f}m, base={self.base_power:.0f}W, mult={self.power_mult:.2f})"


def parse_sections_from_profile(profile_df, start_s=480.0):
    """
    Parse unique sections from the profile CSV starting from a given distance.

    Args:
        profile_df: DataFrame with columns s_m, P_W, comment
        start_s: Starting distance for optimization (default 480m)

    Returns:
        List of SectionDefinition objects
    """
    # Filter to rows at or after start_s
    df = profile_df[profile_df['s_m'] >= start_s].copy()

    if 'comment' not in df.columns:
        raise ValueError("Profile CSV must have a 'comment' column for section parsing")

    sections = []
    current_section = None
    section_rows = []

    for _, row in df.iterrows():
        comment = str(row['comment']).strip()

        # Extract section name (e.g., "Lap2_BackStraight" from "Lap2_BackStraight_1of4")
        parts = comment.rsplit('_', 1)
        if len(parts) == 2 and 'of' in parts[1]:
            section_name = parts[0]
        else:
            section_name = comment

        if section_name != current_section:
            # Save previous section
            if current_section is not None and section_rows:
                start = section_rows[0]['s_m']
                end = section_rows[-1]['s_m']
                avg_power = np.mean([r['P_W'] for r in section_rows])
                sections.append(SectionDefinition(current_section, start, end, avg_power))

            # Start new section
            current_section = section_name
            section_rows = [row]
        else:
            section_rows.append(row)

    # Don't forget the last section
    if current_section is not None and section_rows:
        start = section_rows[0]['s_m']
        end = section_rows[-1]['s_m']
        avg_power = np.mean([r['P_W'] for r in section_rows])
        sections.append(SectionDefinition(current_section, start, end, avg_power))

    return sections


class PowerOptimizer:
    """
    Optimizer that finds the best power distribution across sections
    to minimize time while respecting power curve constraints.
    """

    def __init__(self, simulate_func, params, s_grid, theta_grid,
                 y_base_grid, CdA_base_grid, P_base_grid,
                 power_curve_dict, check_interval=1.0):
        """
        Args:
            simulate_func: The simulation function (simulate_profile method)
            params: Simulation parameters dict
            s_grid: Distance grid array
            theta_grid: Track angle grid array
            y_base_grid: Track position (y) grid array
            CdA_base_grid: Aerodynamic drag grid array
            P_base_grid: Base power grid array
            power_curve_dict: Power curve constraint dict
            check_interval: Constraint check interval in seconds
        """
        self.simulate_func = simulate_func
        self.params = params
        self.s_grid = s_grid
        self.theta_grid = theta_grid
        self.y_base_grid = y_base_grid
        self.CdA_base_grid = CdA_base_grid
        self.P_base_grid = P_base_grid.copy()

        self.constraint = PowerCurveConstraint(power_curve_dict, check_interval)
        self.sections = []
        self.opt_start_s = 480.0

        # Results storage
        self.best_result = None
        self.best_multipliers = None
        self.best_time = float('inf')
        self.iteration_count = 0
        self.valid_count = 0

    def set_sections(self, sections):
        """Set the sections to optimize."""
        self.sections = sections
        self.opt_start_s = sections[0].start_s if sections else 480.0

    def apply_multipliers(self, multipliers):
        """
        Apply power multipliers to the base power grid.

        Args:
            multipliers: Dict mapping section name to multiplier

        Returns:
            Modified power grid
        """
        P_grid = self.P_base_grid.copy()

        for section in self.sections:
            mult = multipliers.get(section.name, 1.0)
            mask = (self.s_grid >= section.start_s) & (self.s_grid <= section.end_s)
            P_grid[mask] = P_grid[mask] * mult

        return P_grid

    def run_simulation_with_multipliers(self, multipliers):
        """
        Run simulation with given power multipliers.

        Returns:
            (result_dict, is_valid, violations)
        """
        P_grid = self.apply_multipliers(multipliers)

        # Run simulation
        result = self.simulate_func(
            self.y_base_grid,
            self.CdA_base_grid,
            P_grid,
            self.params,
            self.s_grid,
            self.theta_grid,
            label="opt"
        )

        # Extract power and time arrays from optimization start point
        opt_start_idx = np.searchsorted(self.s_grid, self.opt_start_s)
        P_eff = result['P_eff'][opt_start_idx:]
        dt = result['dt'][opt_start_idx:]

        # Validate against power curve
        is_valid, violations = self.constraint.validate_power_sequence(P_eff, dt)

        return result, is_valid, violations

    def random_search(self, n_samples=1000, mult_values=None,
                       progress_callback=None, stop_check=None, resume=False,
                       new_best_callback=None):
        """
        Perform random sampling search over power multipliers.

        Args:
            n_samples: Number of random samples to try
            mult_values: Array of discrete multiplier values to choose from
            progress_callback: Optional callback function(iteration, total, current_best_time)
            stop_check: Optional callable that returns True if we should stop
            resume: If True, don't reset best results (continue from previous state)
            new_best_callback: Optional callback when a new best solution is found

        Returns:
            (best_multipliers, best_time, best_result, was_stopped)
        """
        if mult_values is None:
            mult_values = np.array([0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25])

        section_names = [s.name for s in self.sections]
        n_sections = len(section_names)

        # Only reset state if not resuming
        if not resume:
            self.best_time = float('inf')
            self.best_multipliers = None
            self.best_result = None
            self.iteration_count = 0
            self.valid_count = 0

        start_iteration = self.iteration_count
        was_stopped = False

        for i in range(n_samples):
            # Check if we should stop
            if stop_check and stop_check():
                was_stopped = True
                break

            self.iteration_count += 1

            # Randomly select from discrete multiplier values for each section
            random_mults = np.random.choice(mult_values, n_sections)
            multipliers = dict(zip(section_names, random_mults))

            # Run simulation
            result, is_valid, violations = self.run_simulation_with_multipliers(multipliers)

            if is_valid:
                self.valid_count += 1
                t_200 = result['T_200']

                if t_200 < self.best_time:
                    self.best_time = t_200
                    self.best_multipliers = multipliers.copy()
                    self.best_result = result

                    # New best found callback
                    if new_best_callback:
                        new_best_callback(self.best_time, self.best_multipliers)

            # Progress callback
            if progress_callback:
                progress_callback(self.iteration_count, start_iteration + n_samples, self.best_time)

        return self.best_multipliers, self.best_time, self.best_result, was_stopped

    def get_optimization_summary(self):
        """Get a summary of the optimization results."""
        if self.best_multipliers is None:
            return "No optimization run yet"

        lines = [
            f"Optimization Summary",
            f"=" * 40,
            f"Iterations: {self.iteration_count}",
            f"Valid combinations: {self.valid_count}",
            f"Best 200m time: {self.best_time:.3f}s",
            f"",
            f"Optimal Power Multipliers:",
        ]

        for section in self.sections:
            mult = self.best_multipliers.get(section.name, 1.0)
            adj_power = section.base_power * mult
            lines.append(f"  {section.name}: {mult:.2f}x ({adj_power:.0f}W)")

        return "\n".join(lines)


def create_optimized_profile(profile_df, sections, multipliers, output_path=None):
    """
    Create a new profile CSV with optimized power values.

    Args:
        profile_df: Original profile DataFrame
        sections: List of SectionDefinition objects
        multipliers: Dict mapping section name to multiplier
        output_path: Optional path to save the CSV

    Returns:
        Modified DataFrame
    """
    df = profile_df.copy()

    # Add multiplier column (default 1.0 for rows not in optimization range)
    df['multiplier'] = 1.0

    for section in sections:
        mult = multipliers.get(section.name, 1.0)
        mask = (df['s_m'] >= section.start_s) & (df['s_m'] <= section.end_s)
        df.loc[mask, 'P_W'] = df.loc[mask, 'P_W'] * mult
        df.loc[mask, 'multiplier'] = mult

    if output_path:
        df.to_csv(output_path, index=False)

    return df


# ============================================
# Energy-Budget Based Optimizer
# ============================================

class PositionConstraints:
    """
    Manages rider position (standing/seated) constraints for optimization.

    Rules:
    - Rider can stand from opt_start until transition_m
    - Rider must be seated from transition_m onwards
    - Timed section (695-895m) is ALWAYS seated regardless of transition_m
    - Minimum standing distance enforced to prevent silly sit-stand-sit patterns
    """

    def __init__(self, opt_start_m=480.0, transition_m=600.0, min_standing_m=50.0,
                 timed_start_m=695.0):
        """
        Args:
            opt_start_m: Where optimization starts (default 480m)
            transition_m: Distance at which rider sits down
            min_standing_m: Minimum distance rider must stand if they stand at all
            timed_start_m: Start of timed 200m section (always seated from here)
        """
        self.opt_start_m = opt_start_m
        self.transition_m = transition_m
        self.min_standing_m = min_standing_m
        self.timed_start_m = timed_start_m

    def get_position(self, s_m):
        """
        Returns 'standing' or 'seated' for given distance.

        Args:
            s_m: Distance in meters from start

        Returns:
            'standing' or 'seated'
        """
        # Timed section: always seated
        if s_m >= self.timed_start_m:
            return 'seated'
        # Before transition: standing
        if s_m < self.transition_m:
            return 'standing'
        # After transition: seated
        return 'seated'

    def validate_transition(self, transition_m):
        """
        Ensure transition point respects constraints.

        Args:
            transition_m: Proposed transition distance

        Returns:
            (is_valid, error_message or None)
        """
        standing_distance = transition_m - self.opt_start_m

        if standing_distance < self.min_standing_m:
            return False, f"Must stand for at least {self.min_standing_m}m (currently {standing_distance:.0f}m)"
        if transition_m > self.timed_start_m:
            return False, f"Must be seated by timed section ({self.timed_start_m}m)"
        return True, None

    def get_valid_transition_range(self):
        """
        Get the valid range for transition point.

        Returns:
            (min_transition_m, max_transition_m)
        """
        min_trans = self.opt_start_m + self.min_standing_m
        max_trans = self.timed_start_m
        return min_trans, max_trans


def calculate_permutations(opt_start_m, timed_start_m, segment_length_m,
                           min_standing_m, energy_levels):
    """
    Calculate total permutations for the optimization.

    This helps users understand the search space size before running.

    Args:
        opt_start_m: Where optimization starts (e.g., 480m)
        timed_start_m: Start of timed section (695m, always seated)
        segment_length_m: Length of each segment (e.g., 50m)
        min_standing_m: Minimum standing distance (e.g., 50m)
        energy_levels: Number of discrete energy allocation levels (e.g., 10)

    Returns:
        dict with:
            n_segments: Number of segments
            n_transition_options: Number of transition point options
            n_energy_combos: Energy distribution combinations per transition
            total_permutations: Total iterations needed
            estimated_time_s: Rough time estimate (assuming ~1ms per sim)
    """
    from math import comb

    # Total distance to optimize: from opt_start to end of timed section
    total_distance = timed_start_m + 200.0 - opt_start_m  # 695 + 200 - 480 = 415m
    n_segments = int(np.ceil(total_distance / segment_length_m))

    # Transition point options
    # Can transition anywhere from (opt_start + min_standing) to timed_start
    min_trans = opt_start_m + min_standing_m
    transition_range = timed_start_m - min_trans
    n_transition_options = max(1, int(transition_range / segment_length_m) + 1)

    # Energy distribution combinations
    # This is the "stars and bars" problem: distribute energy_levels units among n_segments
    # where each segment gets 0 to energy_levels units and sum = energy_levels
    # Formula: C(n_segments + energy_levels - 1, energy_levels - 1)
    # But we need sum = energy_levels (not <= energy_levels), so it's:
    # C(n_segments + energy_levels - 1, n_segments - 1)
    if n_segments > 0 and energy_levels > 0:
        n_energy_combos = comb(n_segments + energy_levels - 1, n_segments - 1)
    else:
        n_energy_combos = 1

    # Total permutations
    total = n_transition_options * n_energy_combos

    # Time estimate: ~1ms per simulation (rough)
    estimated_time_s = total * 0.001

    return {
        'n_segments': n_segments,
        'n_transition_options': n_transition_options,
        'n_energy_combos': n_energy_combos,
        'total_permutations': total,
        'estimated_time_s': estimated_time_s
    }


def format_permutation_estimate(perm_info):
    """
    Format permutation info for GUI display.

    Args:
        perm_info: Dict from calculate_permutations()

    Returns:
        Human-readable string
    """
    total = perm_info['total_permutations']
    time_s = perm_info['estimated_time_s']

    # Format time
    if time_s < 60:
        time_str = f"{time_s:.0f}s"
    elif time_s < 3600:
        time_str = f"{time_s/60:.1f} min"
    else:
        time_str = f"{time_s/3600:.1f} hours"

    # Format total
    if total < 1000:
        total_str = str(total)
    elif total < 1_000_000:
        total_str = f"{total/1000:.1f}K"
    else:
        total_str = f"{total/1_000_000:.1f}M"

    return f"{total_str} permutations (~{time_str})"


class EnergyBudgetOptimizer:
    """
    Optimizer that finds the best energy distribution across segments
    to minimize 200m time, given a fixed energy budget.

    Key concept: Instead of multiplying recorded power values, we allocate
    a fixed energy budget (Joules) across segments. The optimizer finds
    the distribution that minimizes time while respecting power curve ceilings.

    Advantages:
    - No constraint violations (can't overspend budget)
    - Position-aware (uses correct power curve for standing vs seated)
    - Physically intuitive (how to spend X Joules?)
    """

    def __init__(self, simulate_func, params, s_grid, theta_grid,
                 y_base_grid, CdA_standing_grid, CdA_seated_grid,
                 P_base_grid,
                 power_curve_seated, power_curve_standing,
                 total_energy_budget_J,
                 opt_start_m=480.0, timed_start_m=695.0,
                 segment_length_m=50.0, min_standing_m=50.0,
                 min_power_pct=0.3, timed_mode='FLATOUT',
                 max_transition_watts=150.0, constraint_buffer_pct=0.02,
                 gravity_aware_position=False,
                 CdA_profile_grid=None):
        """
        Args:
            simulate_func: Function to run simulation (y, CdA, P, params, s_grid, theta_grid, label)
            params: Simulation parameters dict
            s_grid: Distance grid array
            theta_grid: Track banking angle array
            y_base_grid: Rider lateral position array
            CdA_standing_grid: CdA values for standing position
            CdA_seated_grid: CdA values for seated position
            P_base_grid: Base power profile (used for pre-optimization distances)
            power_curve_seated: {duration_s: max_watts} for seated
            power_curve_standing: {duration_s: max_watts} for standing
            total_energy_budget_J: Total Joules to allocate (e.g., W')
            opt_start_m: Where optimization starts
            timed_start_m: Start of timed 200m section
            segment_length_m: Length of each optimization segment
            min_standing_m: Minimum standing distance
            min_power_pct: Minimum power as fraction of baseline (0.3 = 30%)
            timed_mode: 'FLATOUT' = max power curve from 200m line, 'OPT' = optimize allocation
            max_transition_watts: Max power jump from baseline at opt start (default 150W)
            constraint_buffer_pct: Buffer percentage to relax floor/ceiling constraints (0.02 = 2%)
            gravity_aware_position: If True, use gravity-aware position decision that accounts
                for track slope (dh/ds) when evaluating standing vs seated efficiency.
        """
        self.simulate_func = simulate_func
        self.params = params
        self.s_grid = s_grid
        self.theta_grid = theta_grid
        self.y_base_grid = y_base_grid
        self.CdA_standing_grid = CdA_standing_grid
        self.CdA_seated_grid = CdA_seated_grid
        self.CdA_profile_grid = CdA_profile_grid  # User's actual CdA (mixed standing/seated from segment positions)
        self.P_base_grid = P_base_grid
        self.total_energy_budget_J = total_energy_budget_J
        self.opt_start_m = opt_start_m
        self.timed_start_m = timed_start_m
        self.segment_length_m = segment_length_m
        self.min_standing_m = min_standing_m
        self.min_power_pct = min_power_pct
        self.timed_mode = timed_mode  # 'FLATOUT' or 'OPT'
        self.max_transition_watts = max_transition_watts
        self.constraint_buffer_pct = constraint_buffer_pct
        self.gravity_aware_position = gravity_aware_position

        # Create power curve interpolators
        self.power_curve_seated = power_curve_seated
        self.power_curve_standing = power_curve_standing
        self._setup_power_interpolators()

        # Build segments
        self.segments = self._build_segments()

        # Results storage
        self.best_time = float('inf')
        self.best_allocation = None
        self.best_transition_m = None
        self.best_result = None
        self.best_positions = None  # List of 'standing'/'seated' per segment
        self.best_iterations_used = 0  # How many iterations to converge
        self.iteration_count = 0
        self.valid_count = 0
        self.rejected_count = 0  # Track allocations rejected due to constraint violations

    def _setup_power_interpolators(self):
        """Create interpolators for power curves."""
        def make_interpolator(curve_dict):
            if not curve_dict:
                return None
            durations = sorted(curve_dict.keys())
            powers = [curve_dict[d] for d in durations]
            return interp1d(durations, powers, kind='linear',
                           fill_value=(powers[0], powers[-1]),
                           bounds_error=False)

        self.seated_interp = make_interpolator(self.power_curve_seated)
        self.standing_interp = make_interpolator(self.power_curve_standing)

    def get_max_power(self, elapsed_time_s, position):
        """
        Get maximum power at given elapsed time and position.

        Args:
            elapsed_time_s: Time since sprint start
            position: 'standing' or 'seated'

        Returns:
            Max power in watts
        """
        if position == 'standing' and self.standing_interp is not None:
            return float(self.standing_interp(elapsed_time_s))
        elif self.seated_interp is not None:
            return float(self.seated_interp(elapsed_time_s))
        else:
            return 1500.0  # Fallback

    def _build_segments(self):
        """
        Build list of segments for optimization.

        In FLATOUT mode: only segments from opt_start to timed_start (695m)
        In OPT mode: segments from opt_start to end of timed section (895m)

        Returns:
            List of dicts: [{'start_m', 'end_m', 'name'}, ...]
        """
        segments = []
        s = self.opt_start_m

        # In FLATOUT mode, only optimize up to timed section start
        # The timed section will use max power curve automatically
        if self.timed_mode == 'FLATOUT':
            end_m = self.timed_start_m  # Stop at 695m
        else:
            end_m = self.timed_start_m + 200.0  # End of timed section (895m)

        seg_idx = 0
        while s < end_m:
            seg_end = min(s + self.segment_length_m, end_m)
            segments.append({
                'start_m': s,
                'end_m': seg_end,
                'name': f"seg_{seg_idx}",
                'length_m': seg_end - s
            })
            s = seg_end
            seg_idx += 1

        return segments

    def allocate_energy(self, fractions):
        """
        Convert fraction allocation to Joules per segment.

        The allocation works in two parts:
        1. Each segment gets a guaranteed "floor" energy based on min_power_pct
        2. The remaining "discretionary" budget is distributed according to fractions

        This ensures the energy budget is properly respected even when the floor kicks in.

        Args:
            fractions: List of fractions (must sum to 1.0) for discretionary energy

        Returns:
            List of Joules per segment
        """
        # Calculate floor energy for each segment
        # Floor = min_power_pct × baseline_power × estimated_duration
        avg_speed_estimate = 17.0  # m/s (same estimate used in build_power_grid)

        floor_energies = []
        for segment in self.segments:
            length_m = segment['length_m']
            seg_duration_est = length_m / avg_speed_estimate

            # Get baseline power for this segment
            seg_mask = (self.s_grid >= segment['start_m']) & (self.s_grid < segment['end_m'])
            baseline_power = self.P_base_grid[seg_mask].mean() if seg_mask.any() else 0.0

            # Floor energy = min power × duration
            floor_power = baseline_power * self.min_power_pct
            floor_energy = floor_power * seg_duration_est
            floor_energies.append(floor_energy)

        total_floor_energy = sum(floor_energies)

        # Discretionary energy = total budget - floor requirements
        discretionary_energy = max(0, self.total_energy_budget_J - total_floor_energy)

        # Allocate: floor + fraction of discretionary
        allocations = []
        for i, frac in enumerate(fractions):
            seg_energy = floor_energies[i] + (frac * discretionary_energy)
            allocations.append(seg_energy)

        return allocations

    def build_power_grid(self, energy_allocation, transition_m, speed_profile=None,
                         force_positions=None):
        """
        Build power grid from energy allocation and transition point.

        For each segment:
        1. Determine position (standing/seated based on power gain vs drag penalty)
        2. Calculate average power = energy_J / estimated_duration_s
        3. Cap by power curve at elapsed time
        4. Assign CdA based on position

        Args:
            energy_allocation: List of Joules per segment
            transition_m: Where rider transitions to seated (legacy, not used when speed_profile provided)
            speed_profile: Optional dict with 's' and 'v' arrays from previous simulation.
                          If None, uses hardcoded speed estimates (first iteration).
            force_positions: Optional list of 'seated'/'standing' per segment.
                           If provided, overrides the automatic position decision.

        Returns:
            (P_grid, CdA_grid, is_valid) - power and CdA arrays for simulation, plus validity flag.
            is_valid is False if any segment has floor > ceiling (impossible allocation).
        """
        P_grid = np.zeros_like(self.s_grid)
        CdA_grid = np.zeros_like(self.s_grid)
        is_valid = True  # Track if allocation is possible

        # Create speed interpolator if speed profile provided from previous iteration
        speed_interp = None
        if speed_profile is not None:
            speed_interp = interp1d(
                speed_profile['s'], speed_profile['v'],
                kind='linear', bounds_error=False,
                fill_value=(speed_profile['v'][0], speed_profile['v'][-1])
            )

        # Calculate CdA ratio - standing is only worth it if power gain exceeds drag penalty
        cda_standing = self.CdA_standing_grid[0]  # Constant values
        cda_seated = self.CdA_seated_grid[0]
        cda_ratio = cda_standing / cda_seated if cda_seated > 0 else 1.0

        elapsed_time = 0.0
        cumulative_energy = 0.0  # Track energy spent from sprint start

        # Track actual positions chosen for each segment
        segment_positions = []

        for seg_idx, segment in enumerate(self.segments):
            start_m = segment['start_m']
            end_m = segment['end_m']
            length_m = segment['length_m']
            seg_mask = (self.s_grid >= start_m) & (self.s_grid < end_m)

            # Calculate segment duration using actual speeds from speed profile
            # This is critical for accurate power curve constraint enforcement
            if speed_interp is not None:
                # Use actual speed at segment midpoint for duration estimate
                seg_midpoint = start_m + length_m / 2.0
                v_segment = float(speed_interp(seg_midpoint))
                if v_segment > 0:
                    seg_duration_est = length_m / v_segment
                else:
                    seg_duration_est = length_m / 15.0  # Fallback
            else:
                # No speed profile - use distance-based estimates
                if start_m < 550:
                    v_estimate = 14.0  # Early acceleration
                elif start_m < 700:
                    v_estimate = 17.0  # Peak speed zone
                else:
                    v_estimate = 16.5  # Timed section
                seg_duration_est = length_m / v_estimate

            time_at_seg_end = elapsed_time + seg_duration_est

            # Calculate average power from energy allocation
            energy_J = energy_allocation[seg_idx]
            if seg_duration_est > 0:
                avg_power = energy_J / seg_duration_est
            else:
                avg_power = 0.0

            # === FLATOUT MODE FOR TIMED SECTION ===
            # In FLATOUT mode, from the timed section (200m line) onwards,
            # rider goes max effort using whatever power curve allows.
            # This is more realistic - no rider can finely modulate power in the last 200m.
            in_timed_section = start_m >= self.timed_start_m
            use_flatout = (self.timed_mode == 'FLATOUT') and in_timed_section

            # === POSITION DECISION ===
            # If force_positions is provided, skip the automatic decision.
            if force_positions is not None and seg_idx < len(force_positions):
                position = force_positions[seg_idx]
            else:
                # Automatic position decision based on power/drag trade-off.
                # Get air density from params
                rho = self.params.get('rho', 1.225)
                mass = self.params.get('mass', 92.0)
                G = 9.81

                # Estimate speed at this point
                if speed_interp is not None:
                    seg_midpoint = start_m + length_m / 2.0
                    v_estimate = float(speed_interp(seg_midpoint))
                else:
                    if start_m < 550:
                        v_estimate = 14.0
                    elif start_m < 700:
                        v_estimate = 17.0
                    else:
                        v_estimate = 16.5

                # Get power limits for both positions at this elapsed time
                seated_max = self.get_max_power(time_at_seg_end, 'seated')
                standing_max = self.get_max_power(time_at_seg_end, 'standing')

                # Calculate extra power from standing
                extra_power = standing_max - seated_max

                # Calculate extra drag from standing at current speed estimate
                delta_cda = cda_standing - cda_seated
                extra_drag = 0.5 * rho * delta_cda * (v_estimate ** 3)

                if self.gravity_aware_position:
                    # === GRAVITY-AWARE POSITION DECISION ===
                    seg_mid_idx = np.searchsorted(self.s_grid, start_m + length_m / 2.0)
                    seg_mid_idx = min(seg_mid_idx, len(self.theta_grid) - 1)
                    theta = self.theta_grid[seg_mid_idx]
                    sin_grade = np.sin(theta) if abs(theta) > 1e-6 else 0.0
                    P_gravity = -mass * G * v_estimate * sin_grade
                    crr = self.params.get('crr', 0.002)
                    drivetrain_eff = self.params.get('drivetrain_eff', 1.0)
                    F_rr = crr * mass * G

                    P_rider_standing = min(avg_power, standing_max)
                    P_rider_seated = min(avg_power, seated_max)

                    F_net_standing = ((P_rider_standing * drivetrain_eff + P_gravity) / max(v_estimate, 1.0)
                                      - 0.5 * rho * cda_standing * v_estimate**2 - F_rr)
                    F_net_seated = ((P_rider_seated * drivetrain_eff + P_gravity) / max(v_estimate, 1.0)
                                    - 0.5 * rho * cda_seated * v_estimate**2 - F_rr)

                    cost_standing = max(P_rider_standing * seg_duration_est, 1.0)
                    cost_seated = max(P_rider_seated * seg_duration_est, 1.0)

                    eff_standing = F_net_standing / cost_standing
                    eff_seated = F_net_seated / cost_seated

                    if eff_standing > eff_seated:
                        position = 'standing'
                    else:
                        position = 'seated'
                else:
                    # === LEGACY POSITION DECISION ===
                    if extra_power > extra_drag:
                        position = 'standing'
                    else:
                        position = 'seated'

            segment_positions.append(position)

            # Get CdA for chosen position
            if position == 'standing':
                CdA_grid[seg_mask] = self.CdA_standing_grid[seg_mask]
            else:
                CdA_grid[seg_mask] = self.CdA_seated_grid[seg_mask]

            # === POWER CURVE CONSTRAINTS ===
            # The power curve represents maximum AVERAGE power sustainable for a given duration.
            # Key insight: curve(D) = max average power you can hold for D seconds FROM START.
            #
            # For a segment from T to T+d seconds:
            # - The average power for this segment is constrained by curve(T+d)
            # - NOT curve(d), because you've already been working for T seconds
            #
            # Example: At T=10s, doing a 3s segment:
            # - curve(3s) = 1198W is IRRELEVANT - that's for fresh start
            # - curve(13s) = 1058W is the relevant limit
            # - The segment average can't exceed ~1058W
            #
            # Constraint 1: Segment end time limit (PRIMARY CONSTRAINT)
            # At elapsed time T+d, the power curve value represents max sustainable.
            # The segment average can't exceed this because you're that fatigued by segment end.
            segment_end_limit = self.get_max_power(max(1.0, time_at_seg_end), position)

            # Constraint 2: Cumulative energy constraint
            # The running average from 0 to T+d can't exceed curve(T+d).
            # This ensures total energy budget is valid.
            # (cumulative_energy + seg_energy) / time_at_seg_end <= curve(time_at_seg_end)
            #
            # In FLATOUT mode, the timed section will output at the curve level.
            # To avoid cumulative violations, the pre-timed running average must be
            # BELOW the curve, leaving headroom. Use 98% of curve as target.
            if self.timed_mode == 'FLATOUT' and not in_timed_section:
                # Leave 1% headroom below curve for pre-timed section
                # The timed section will use a scaled curve that respects the
                # cumulative constraint, so we don't need large headroom here.
                cumulative_target = segment_end_limit * 0.99
                # Also cap segment end limit at 99% to ensure headroom is actually used
                segment_end_limit_capped = segment_end_limit * 0.99
            else:
                cumulative_target = segment_end_limit
                segment_end_limit_capped = segment_end_limit

            max_seg_energy = cumulative_target * time_at_seg_end - cumulative_energy
            cumulative_power_limit = max_seg_energy / seg_duration_est if seg_duration_est > 0 else float('inf')

            # Take the most restrictive constraint
            # For FLATOUT pre-timed: use capped segment limit to ensure headroom
            max_power = min(segment_end_limit_capped, cumulative_power_limit)

            # CRITICAL: max_power can never be negative - physics constraint
            # If cumulative_power_limit is negative, it means cumulative energy already
            # exceeds what the power curve allows. This allocation is problematic.
            if max_power < 0:
                # Cumulative constraint is severely violated
                # Clamp to a minimum reasonable value and mark solution questionable
                max_power = segment_end_limit_capped * 0.5  # Use half the curve limit
                is_valid = False  # This allocation violates constraints

            # Calculate minimum power floor as percentage of baseline
            # Fixed gear bike cannot produce 0 power while moving
            # Use MEAN baseline within segment (max was too strict and caused no solutions)
            baseline_power_avg = self.P_base_grid[seg_mask].mean() if seg_mask.any() else 0.0
            # Apply constraint buffer to relax floor (subtract buffer to make floor lower)
            min_power_raw = baseline_power_avg * self.min_power_pct * (1.0 - self.constraint_buffer_pct)

            # Apply constraint buffer to relax ceiling (add buffer to make ceiling higher)
            buffered_max_power = max_power * (1.0 + self.constraint_buffer_pct)

            # CRITICAL: Floor cannot exceed ceiling (power curve limit)
            # When baseline FIT file power exceeds what the power curve allows,
            # we must respect the power curve as the physical limit.
            # The floor is just a preference; the ceiling is a hard physics constraint.
            min_power = min(min_power_raw, buffered_max_power) if buffered_max_power > 0 else 0.0

            # Apply constraints (using buffered values for more forgiving optimization)
            # Since we capped min_power at buffered_max_power, we shouldn't have floor > ceiling
            if min_power > buffered_max_power:
                # This shouldn't happen after the cap above, but handle gracefully
                capped_power = buffered_max_power  # Ceiling wins - physics trumps policy
            elif use_flatout:
                # FLATOUT mode: use max power curve value (rider goes all-out)
                # In timed section, ignore energy allocation and just use ceiling
                capped_power = max(min_power, buffered_max_power)
            else:
                capped_power = max(min_power, min(avg_power, buffered_max_power))

            # === TRANSITION CONSTRAINT ===
            # For the first segment, limit how much power can jump from baseline
            # This prevents aggressive step changes at the optimization zone start
            if seg_idx == 0 and self.max_transition_watts is not None:
                # Get baseline power at start of first segment
                baseline_at_start = self.P_base_grid[seg_mask].mean() if seg_mask.any() else capped_power
                max_allowed_power = baseline_at_start + self.max_transition_watts
                min_allowed_power = baseline_at_start - self.max_transition_watts
                # Clamp power within transition bounds
                capped_power = max(min_allowed_power, min(capped_power, max_allowed_power))
                # But still respect floor constraint
                capped_power = max(min_power, capped_power)

            # Assign power to grid
            P_grid[seg_mask] = capped_power

            # Update cumulative tracking
            actual_energy = capped_power * seg_duration_est
            cumulative_energy += actual_energy
            elapsed_time += seg_duration_est

            # === RUNNING AVERAGE VALIDATION ===
            # After assigning power, verify the running average doesn't exceed the power curve.
            # The power curve represents max AVERAGE power from start to elapsed_time.
            # If running_avg > curve(elapsed_time), this allocation is IMPOSSIBLE.
            #
            # In FLATOUT mode, we skip this validation for pre-timed segments because:
            # 1. The timed section will use max power curve
            # 2. The combined average will be checked implicitly by the simulation
            # 3. We want to allow flexibility in pre-timed energy distribution
            #
            # When speed_profile is available, elapsed times are accurate so use tight tolerance.
            # Otherwise use looser tolerance for first-pass estimation.
            if elapsed_time > 0 and self.timed_mode != 'FLATOUT':
                running_avg = cumulative_energy / elapsed_time
                curve_limit = self.get_max_power(max(1.0, elapsed_time), position)
                tolerance = 1.01 if speed_interp is not None else 1.05
                if running_avg > curve_limit * tolerance:
                    # Running average exceeds power curve - allocation is invalid
                    is_valid = False

        # Store positions for later use (e.g., in results display)
        self._last_segment_positions = segment_positions

        # Handle points before opt_start - use base profile values
        pre_opt_mask = self.s_grid < self.opt_start_m
        P_grid[pre_opt_mask] = self.P_base_grid[pre_opt_mask]
        CdA_grid[pre_opt_mask] = self.CdA_seated_grid[pre_opt_mask]

        # === RAMP-UP TRANSITION ZONE ===
        # Create a smooth linear ramp from baseline to first segment power
        # This prevents aggressive step changes at the optimization start
        ramp_distance = 25.0  # meters over which to ramp up
        if len(self.segments) > 0:
            first_seg = self.segments[0]
            first_seg_mask = (self.s_grid >= first_seg['start_m']) & (self.s_grid < first_seg['end_m'])
            if first_seg_mask.any():
                first_seg_power = P_grid[first_seg_mask][0]  # Power assigned to first segment

                # Get baseline power just before opt start
                pre_opt_idx = np.searchsorted(self.s_grid, self.opt_start_m) - 1
                if pre_opt_idx >= 0:
                    baseline_power_at_start = self.P_base_grid[pre_opt_idx]
                else:
                    baseline_power_at_start = first_seg_power

                # Apply linear ramp within the first segment
                ramp_end = min(first_seg['start_m'] + ramp_distance, first_seg['end_m'])
                ramp_mask = (self.s_grid >= first_seg['start_m']) & (self.s_grid < ramp_end)

                if ramp_mask.any():
                    ramp_s = self.s_grid[ramp_mask]
                    # Linear interpolation from baseline to first segment power
                    ramp_progress = (ramp_s - first_seg['start_m']) / ramp_distance
                    ramp_progress = np.clip(ramp_progress, 0, 1)
                    ramp_power = baseline_power_at_start + ramp_progress * (first_seg_power - baseline_power_at_start)
                    P_grid[ramp_mask] = ramp_power

        # === FLATOUT MODE: Fill timed section with max power curve ===
        # In FLATOUT mode, segments only cover up to timed_start (695m).
        # We need to fill the timed section (695-895m) respecting the CUMULATIVE constraint.
        #
        # The power curve represents MAX AVERAGE power from start to time T.
        # So at any point: cumulative_energy / elapsed_time <= curve(elapsed_time)
        # Rearranged: cumulative_energy <= curve(elapsed_time) * elapsed_time
        #
        # At timed start (695m), we know:
        # - elapsed_time at 695m (call it T_start)
        # - cumulative_energy at 695m (from the pre-timed allocation)
        #
        # For each point in timed section at time T:
        # - Max allowed cumulative energy = curve(T) * T
        # - Energy already used = cumulative_energy_at_695 + energy_in_timed_so_far
        # - Max power for this segment = (max_allowed - energy_so_far) / dt
        #
        # In FLATOUT mode, rider goes MAX effort = use exactly the curve limit.
        if self.timed_mode == 'FLATOUT':
            # Compute elapsed time and cumulative energy at each grid point
            ds_grid = np.diff(self.s_grid)
            ds_grid = np.append(ds_grid, ds_grid[-1])

            elapsed_time_grid = np.zeros_like(self.s_grid)
            cumulative_energy_grid = np.zeros_like(self.s_grid)
            cumulative_t = 0.0
            cumulative_E = 0.0

            for i, s in enumerate(self.s_grid):
                if s >= self.opt_start_m:
                    if speed_interp is not None:
                        v_here = float(speed_interp(s))
                    else:
                        v_here = 17.0
                    dt = ds_grid[i] / v_here if v_here > 0 else 0
                    cumulative_t += dt
                    # Energy = power * dt (use P_grid which has pre-timed values already)
                    cumulative_E += P_grid[i] * dt
                elapsed_time_grid[i] = cumulative_t
                cumulative_energy_grid[i] = cumulative_E

            # Fill timed section using cumulative constraint
            # For each point: P = (curve(T) * T - cumulative_energy_before) / dt
            # But we need to track cumulative energy as we go
            cumulative_E_timed = 0.0
            timed_start_idx = np.searchsorted(self.s_grid, self.timed_start_m)

            # Get cumulative energy at timed start (from pre-timed allocation)
            if timed_start_idx > 0:
                cumulative_E_at_timed_start = cumulative_energy_grid[timed_start_idx - 1]
            else:
                cumulative_E_at_timed_start = 0.0

            # For FLATOUT mode in timed section:
            # We want a SMOOTH power profile that respects the cumulative constraint.
            #
            # The cumulative constraint: running_avg(T) = E(T)/T <= curve(T)
            #
            # Strategy: Find the MINIMUM scale factor that satisfies the constraint
            # at ALL points in the timed section, not just the end.
            #
            # For each candidate scale, simulate forward and check if constraint
            # is violated anywhere. Use binary search to find optimal scale.

            # Get time at timed start
            t_at_timed_start = elapsed_time_grid[timed_start_idx]
            E_at_start = cumulative_E_at_timed_start

            # Get indices for timed section
            timed_indices = [i for i, s in enumerate(self.s_grid) if s >= self.timed_start_m]

            def check_scale(scale):
                """Check if a given scale satisfies cumulative constraint throughout."""
                cumulative_E = E_at_start
                for i in timed_indices:
                    t_elapsed = elapsed_time_grid[i]
                    curve_at_t = self.get_max_power(max(1.0, t_elapsed), 'seated')
                    power = curve_at_t * scale

                    # Add energy for this step
                    if i > 0:
                        dt = elapsed_time_grid[i] - elapsed_time_grid[i-1]
                    else:
                        dt = 0
                    cumulative_E += power * dt

                    # Check constraint: cumulative_E / t_elapsed <= curve(t_elapsed)
                    budget = curve_at_t * t_elapsed
                    if cumulative_E > budget * 0.999:  # Small margin
                        return False, cumulative_E, budget
                return True, cumulative_E, budget

            # Binary search for maximum valid scale
            scale_low = 0.70
            scale_high = 0.999

            for _ in range(20):  # 20 iterations gives good precision
                scale_mid = (scale_low + scale_high) / 2
                valid, _, _ = check_scale(scale_mid)
                if valid:
                    scale_low = scale_mid  # Can try higher
                else:
                    scale_high = scale_mid  # Must go lower

            # Use the lower bound (guaranteed valid)
            scale = scale_low * 0.995  # Small additional margin

            # Clamp to reasonable range
            scale = max(0.70, min(0.999, scale))

            for i, s in enumerate(self.s_grid):
                if s < self.timed_start_m:
                    continue

                t_elapsed = elapsed_time_grid[i]

                # Get curve value at this time
                curve_at_t = self.get_max_power(max(1.0, t_elapsed), 'seated')

                # Simply scale the curve - guaranteed smooth
                power_here = curve_at_t * scale

                P_grid[i] = power_here
                CdA_grid[i] = self.CdA_seated_grid[i]

        return P_grid, CdA_grid, is_valid

    def run_simulation(self, energy_allocation, transition_m):
        """
        Run simulation with given energy allocation and transition point.

        Args:
            energy_allocation: List of Joules per segment
            transition_m: Where rider sits down

        Returns:
            (result, is_valid) - Simulation result dict and validity flag.
            is_valid is False if the discrete allocation violates constraints.
            If invalid, result is None (simulation skipped to save time).
        """
        P_grid, CdA_grid, is_valid = self.build_power_grid(energy_allocation, transition_m)

        # Skip simulation if allocation is invalid - save time
        if not is_valid:
            return None, False

        result = self.simulate_func(
            self.y_base_grid,
            CdA_grid,
            P_grid,
            self.params,
            self.s_grid,
            self.theta_grid,
            label="energy_opt"
        )

        return result, is_valid

    def run_simulation_iterative(self, energy_allocation, max_iterations=3,
                                 baseline_speed_profile=None, force_positions=None):
        """
        Run simulation with iterative position refinement.

        The position decision (standing vs seated) depends on speed, which we don't
        know until after simulation. This method iterates:
        1. First iteration: use baseline speeds (from athlete's actual profile) for position decisions
        2. Subsequent iterations: use speeds from previous optimization simulation
        3. Stop when positions converge or max iterations reached

        Args:
            energy_allocation: List of Joules per segment
            max_iterations: Maximum iteration count (default 3)
            baseline_speed_profile: Speed profile from baseline simulation (used for first iteration)
                                   Dict with 's' and 'v' arrays. If None, falls back to hardcoded estimates.
            force_positions: Optional list of 'seated'/'standing' per segment.
                           If provided, overrides automatic position decisions (1 iteration only).

        Returns:
            (result, final_positions, iterations_used, is_valid)
            is_valid is False if the discrete allocation violates constraints.
        """
        last_positions = None
        # Start with baseline speeds from the actual athlete's profile (not hardcoded estimates)
        speed_profile = baseline_speed_profile
        result = None
        current_positions = []

        # If force_positions is set, only need 1 iteration (no convergence loop)
        effective_max_iter = 1 if force_positions else max_iterations

        for iteration in range(effective_max_iter):
            # Build power grid with current speed knowledge
            P_grid, CdA_grid, is_valid = self.build_power_grid(
                energy_allocation,
                transition_m=None,
                speed_profile=speed_profile,
                force_positions=force_positions
            )

            # Even if allocation has soft constraint violations (is_valid=False),
            # still run the simulation. The power grid was clamped to feasible values,
            # so the sim will produce a valid result — just possibly one that violates
            # the energy budget policy. We let the caller decide whether to accept it.

            # Run simulation
            result = self.simulate_func(
                self.y_base_grid,
                CdA_grid,
                P_grid,
                self.params,
                self.s_grid,
                self.theta_grid,
                label=f"iter_{iteration}"
            )

            # Extract speed profile for next iteration
            speed_profile = {
                's': self.s_grid,
                'v': result['v']
            }

            # Get positions chosen this iteration
            current_positions = self._last_segment_positions.copy()

            # Check convergence
            if last_positions is not None and current_positions == last_positions:
                # Positions converged - no need for more iterations
                break

            last_positions = current_positions

        # === POST-SIMULATION VALIDATION ===
        # Validate the running average from actual simulation against power curve.
        # The pre-simulation validation uses estimated durations, but the actual
        # simulation runs at different speeds, so we must validate post-simulation.
        if result is not None:
            post_valid = self._validate_simulation_result(result, P_grid)
            if not post_valid:
                return result, current_positions, iteration + 1, False

        return result, current_positions, iteration + 1, True

    def _validate_simulation_result(self, result, P_grid):
        """
        Validate that the simulation result doesn't violate power curve constraints.

        The running average power from opt_start to any point must not exceed
        the power curve at that elapsed time.

        Args:
            result: Simulation result dict with 't', 'v', etc.
            P_grid: The power grid used in simulation

        Returns:
            True if valid, False if running average exceeds power curve.
        """
        # In FLATOUT mode, skip validation - we're intentionally using max power
        # in the timed section which may exceed running average limits
        if self.timed_mode == 'FLATOUT':
            return True

        # If no power curves are configured, skip validation
        if not self.power_curve_seated and not self.power_curve_standing:
            return True

        # Find optimization start point
        opt_start_idx = np.searchsorted(self.s_grid, self.opt_start_m)

        # Get time array
        t = result.get('t', None)
        if t is None:
            # No time array - can't validate
            return True

        # Time at opt start
        t_opt_start = t[opt_start_idx] if opt_start_idx < len(t) else 0

        # Calculate cumulative energy and running average in optimization zone
        cumulative_energy = 0.0
        max_violation_pct = 0.0  # Track worst violation

        for i in range(opt_start_idx, len(self.s_grid) - 1):
            # Time step
            dt = t[i + 1] - t[i] if (i + 1) < len(t) else 0
            if dt <= 0:
                continue

            # Power at this point
            P = P_grid[i]

            # Add energy for this step
            cumulative_energy += P * dt

            # Elapsed time from opt start
            elapsed = t[i + 1] - t_opt_start

            if elapsed > 0:
                # Running average
                running_avg = cumulative_energy / elapsed

                # Power curve limit at this elapsed time
                # Use seated curve as the constraint (most restrictive for later sections)
                curve_limit = self.get_max_power(max(1.0, elapsed), 'seated')

                # Track violation percentage
                if curve_limit > 0:
                    violation_pct = (running_avg - curve_limit) / curve_limit * 100
                    max_violation_pct = max(max_violation_pct, violation_pct)

        # Reject only if violation exceeds 1% - allows for minor numerical errors
        # The pre-simulation validation now uses real baseline speeds, so both should agree
        if max_violation_pct > 1.0:
            return False

        return True

    def random_search(self, n_samples=1000, energy_levels=10,
                      progress_callback=None, stop_check=None,
                      new_best_callback=None, max_position_iterations=3,
                      baseline_result=None):
        """
        Random search over energy distributions using iterative position refinement.

        Position decisions (standing vs seated) are now made iteratively based on
        actual simulated speeds rather than hardcoded estimates. This ensures the
        position choice is optimal for each athlete's specific power/aero profile.

        Args:
            n_samples: Number of random samples
            energy_levels: Discrete energy levels (e.g., 10 = 0%, 10%, 20%, ...)
            progress_callback: Callback(iteration, total, best_time)
            stop_check: Callable returning True to stop
            new_best_callback: Callback when new best found
            max_position_iterations: Max iterations for position convergence (default 3)
            baseline_result: Result dict from baseline simulation (contains 'v' speeds from actual athlete)
                            Used as starting point for position decisions instead of hardcoded estimates.

        Returns:
            (best_allocation, best_positions, best_time, best_result, was_stopped)
        """
        n_segments = len(self.segments)

        # Extract baseline speed profile from actual athlete data
        baseline_speed_profile = None
        baseline_T_200 = None
        if baseline_result is not None:
            if 'v' in baseline_result:
                baseline_speed_profile = {
                    's': self.s_grid,
                    'v': baseline_result['v']
                }
            if 'T_200' in baseline_result:
                baseline_T_200 = baseline_result['T_200']

        # CRITICAL: Initialize best_time to baseline, not infinity
        # This ensures we only accept solutions that are FASTER than baseline
        # (returning a slower "optimized" solution is never useful)
        if baseline_T_200 is not None:
            self.best_time = baseline_T_200
        # If no baseline provided, keep the existing best_time (may be from __init__ as inf)

        was_stopped = False

        # === FIRST PASS: Direct position sweep ===
        # Before random search, test position changes using the EXACT baseline power
        # profile (P_base_grid) and the user's actual CdA (CdA_profile_grid).
        # No energy redistribution — just swap CdA. This is exactly what the user
        # sees when they manually flip a segment from standing to seated.
        profile_cda = self.CdA_profile_grid
        if profile_cda is None:
            # Fallback: no profile CdA provided, skip first pass
            profile_cda = self.CdA_seated_grid

        has_standing = not np.allclose(profile_cda, self.CdA_seated_grid)
        # Uniform fractions as a safe default allocation for first-pass results
        uniform_fractions = list(np.ones(n_segments) / n_segments)

        if has_standing:
            # Derive per-segment positions from the user's profile CdA
            profile_positions = []
            for seg in self.segments:
                seg_mask = (self.s_grid >= seg['start_m']) & (self.s_grid < seg['end_m'])
                if seg_mask.any():
                    seg_cda = profile_cda[seg_mask].mean()
                    seated_cda = self.CdA_seated_grid[seg_mask].mean()
                    profile_positions.append('standing' if seg_cda > seated_cda * 1.01 else 'seated')
                else:
                    profile_positions.append('seated')

            # Test 1: All-seated with baseline power
            all_seated = ['seated'] * n_segments
            try:
                all_seated_result = self.simulate_func(
                    self.y_base_grid,
                    self.CdA_seated_grid,
                    self.P_base_grid,
                    self.params,
                    self.s_grid,
                    self.theta_grid,
                    label="first_pass_all_seated"
                )
                t_all_seated = all_seated_result.get('T_200', float('inf'))
                if t_all_seated < self.best_time:
                    self.best_time = t_all_seated
                    self.best_positions = all_seated
                    self.best_allocation = uniform_fractions
                    self.best_iterations_used = 1
                    self.best_result = all_seated_result
                    self.best_transition_m = self._compute_transition_from_positions(all_seated)
                    if new_best_callback:
                        new_best_callback(self.best_time, self.best_allocation,
                                         self.best_transition_m)
            except Exception:
                pass

            # Test 2: Flip individual standing segments one at a time
            for seg_idx, seg in enumerate(self.segments):
                if profile_positions[seg_idx] != 'standing':
                    continue
                seg_mask = (self.s_grid >= seg['start_m']) & (self.s_grid < seg['end_m'])
                if not seg_mask.any():
                    continue

                # Build CdA grid: user's profile but this segment forced to seated
                test_cda = profile_cda.copy()
                test_cda[seg_mask] = self.CdA_seated_grid[seg_mask]
                test_positions = list(profile_positions)
                test_positions[seg_idx] = 'seated'
                try:
                    flip_result = self.simulate_func(
                        self.y_base_grid,
                        test_cda,
                        self.P_base_grid,
                        self.params,
                        self.s_grid,
                        self.theta_grid,
                        label=f"first_pass_flip_{seg['start_m']}"
                    )
                    t_flip = flip_result.get('T_200', float('inf'))
                    if t_flip < self.best_time:
                        self.best_time = t_flip
                        self.best_positions = test_positions
                        self.best_allocation = uniform_fractions
                        self.best_iterations_used = 1
                        self.best_result = flip_result
                        self.best_transition_m = self._compute_transition_from_positions(test_positions)
                        if new_best_callback:
                            new_best_callback(self.best_time, self.best_allocation,
                                             self.best_transition_m)
                except Exception:
                    pass

        for i in range(n_samples):
            if stop_check and stop_check():
                was_stopped = True
                break

            self.iteration_count += 1

            # Random energy allocation (using discrete levels, normalized)
            # Each segment must get at least 1 level to ensure non-zero allocation
            # (on a fixed gear bike, you must produce power while moving)
            raw_levels = np.random.randint(1, energy_levels + 1, n_segments)

            fractions = raw_levels / raw_levels.sum()
            energy_allocation = self.allocate_energy(fractions)

            # Run iterative simulation (handles position decisions internally)
            # First iteration uses baseline speeds from actual athlete profile
            try:
                result, positions, iters_used, is_valid = self.run_simulation_iterative(
                    energy_allocation,
                    max_iterations=max_position_iterations,
                    baseline_speed_profile=baseline_speed_profile
                )

                if result is None:
                    self.rejected_count += 1
                    if progress_callback:
                        progress_callback(self.iteration_count, n_samples, self.best_time)
                    continue

                t_200 = result.get('T_200', float('inf'))

                if not is_valid:
                    self.rejected_count += 1
                else:
                    self.valid_count += 1

                # Accept any solution that beats the best time, even with soft
                # constraint violations. The power grid was already clamped to
                # physically feasible values; is_valid=False just means the energy
                # budget policy was bent, not that physics was violated.
                if t_200 < self.best_time:
                    self.best_time = t_200
                    self.best_allocation = list(fractions)
                    self.best_positions = positions
                    self.best_iterations_used = iters_used
                    self.best_result = result
                    # Compute transition point from positions for backwards compatibility
                    self.best_transition_m = self._compute_transition_from_positions(positions)

                    if new_best_callback:
                        new_best_callback(self.best_time, self.best_allocation,
                                         self.best_transition_m)

            except Exception as e:
                # Skip invalid configurations
                self.rejected_count += 1

            if progress_callback:
                progress_callback(self.iteration_count, n_samples, self.best_time)

        return (self.best_allocation, self.best_positions,
                self.best_time, self.best_result, was_stopped)

    def optimize_slsqp(self, energy_levels=10,
                       progress_callback=None, stop_check=None,
                       new_best_callback=None, max_position_iterations=3,
                       baseline_result=None, max_wall_time_s=25.0):
        """
        Gradient-based SLSQP optimization over energy distributions.

        Uses scipy.optimize.minimize(method='SLSQP') instead of random sampling.
        The forward-Euler physics simulation is continuous and differentiable w.r.t.
        power inputs, so gradient-based optimization applies directly.

        SLSQP handles inequality constraints natively:
        - Fractions must sum to 1.0
        - Each fraction must be >= small positive value (non-zero allocation)

        Expected: 10-50ms better solutions found in 50-200 evaluations (vs 10,000
        random samples). 25-50x computational speedup. Deterministic results.

        Args:
            energy_levels: Not used directly by SLSQP, kept for API compatibility.
            progress_callback: Callback(iteration, total_est, best_time)
            stop_check: Callable returning True to stop (checked between evaluations)
            new_best_callback: Callback when new best found
            max_position_iterations: Max iterations for position convergence
            baseline_result: Result dict from baseline simulation

        Returns:
            (best_allocation, best_positions, best_time, best_result, was_stopped)
        """
        n_segments = len(self.segments)

        # Extract baseline speed profile from actual athlete data
        baseline_speed_profile = None
        baseline_T_200 = None
        if baseline_result is not None:
            if 'v' in baseline_result:
                baseline_speed_profile = {
                    's': self.s_grid,
                    'v': baseline_result['v']
                }
            if 'T_200' in baseline_result:
                baseline_T_200 = baseline_result['T_200']

        # Initialize best_time to baseline (only accept faster solutions)
        if baseline_T_200 is not None:
            self.best_time = baseline_T_200

        was_stopped = False
        eval_count = [0]  # Mutable counter for closure
        _wall_start = _time.monotonic()
        _cache = {}  # Cache keyed on rounded fractions to avoid redundant sims

        def objective(x):
            """Objective function: fractions -> T_200 (to minimize)."""
            eval_count[0] += 1
            self.iteration_count += 1

            # Wall-clock time guard to prevent Railway timeout
            if _time.monotonic() - _wall_start > max_wall_time_s:
                return 1e6

            if stop_check and stop_check():
                return 1e6  # Signal to stop

            # Normalize to ensure sum = 1 (SLSQP constraint handles this,
            # but normalize defensively for numerical stability)
            fractions = np.abs(x)
            s = fractions.sum()
            if s < 1e-12:
                fractions = np.ones(n_segments) / n_segments
            else:
                fractions = fractions / s

            # Check cache (round to 6 decimals — well within ftol precision)
            cache_key = tuple(np.round(fractions, 6))
            if cache_key in _cache:
                return _cache[cache_key]

            energy_allocation = self.allocate_energy(list(fractions))

            try:
                # Use only 1 position iteration inside SLSQP — the gradient
                # optimizer explores the energy space; iterating positions 3x
                # per evaluation is the main perf bottleneck and unnecessary
                # since SLSQP converges to the right neighbourhood anyway.
                result, positions, iters_used, is_valid = self.run_simulation_iterative(
                    energy_allocation,
                    max_iterations=1,
                    baseline_speed_profile=baseline_speed_profile
                )

                if result is None:
                    self.rejected_count += 1
                    _cache[cache_key] = 1e6
                    return 1e6

                t_200 = result.get('T_200', float('inf'))
                if not is_valid:
                    self.rejected_count += 1
                else:
                    self.valid_count += 1
                _cache[cache_key] = t_200

                if t_200 < self.best_time:
                    self.best_time = t_200
                    self.best_allocation = list(fractions)
                    self.best_positions = positions
                    self.best_iterations_used = iters_used
                    self.best_result = result
                    self.best_transition_m = self._compute_transition_from_positions(positions)

                    if new_best_callback:
                        new_best_callback(self.best_time, self.best_allocation,
                                         self.best_transition_m)

                if progress_callback:
                    progress_callback(eval_count[0], 200, self.best_time)

                return t_200

            except Exception:
                self.rejected_count += 1
                _cache[cache_key] = 1e6
                return 1e6

        # Initial guess: uniform distribution
        x0 = np.ones(n_segments) / n_segments

        # Constraints: fractions sum to 1
        constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x) - 1.0}]

        # Bounds: each fraction between small positive value and 1
        bounds = [(0.01, 1.0)] * n_segments

        # Run SLSQP optimizer
        # With n_segments dimensions, each SLSQP iteration evaluates the objective
        # (n_segments + 1) times for numerical gradients.  Keep maxiter modest to
        # stay well within Railway's 30 s request timeout.
        opt_result = minimize(
            objective,
            x0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={
                'maxiter': 50,
                'ftol': 1e-6,
                'disp': False,
            }
        )

        # Try a couple of random restarts to escape local minima (if time permits)
        n_restarts = 2
        for restart in range(n_restarts):
            if stop_check and stop_check():
                was_stopped = True
                break
            # Bail early if running low on wall-clock time
            if _time.monotonic() - _wall_start > max_wall_time_s * 0.8:
                break

            # Random starting point
            x0_rand = np.random.dirichlet(np.ones(n_segments))
            try:
                minimize(
                    objective,
                    x0_rand,
                    method='SLSQP',
                    bounds=bounds,
                    constraints=constraints,
                    options={
                        'maxiter': 30,
                        'ftol': 1e-6,
                        'disp': False,
                    }
                )
            except Exception:
                pass  # Best result already tracked internally

        return (self.best_allocation, self.best_positions,
                self.best_time, self.best_result, was_stopped)

    def _compute_transition_from_positions(self, positions):
        """
        Compute the transition point (where rider sits down) from position list.

        Args:
            positions: List of 'standing'/'seated' per segment

        Returns:
            Distance in meters where transition occurs, or None if all seated
        """
        if positions is None:
            return None

        # Find last standing segment
        last_standing_idx = -1
        for i, pos in enumerate(positions):
            if pos == 'standing':
                last_standing_idx = i

        if last_standing_idx < 0:
            # All seated - no transition
            return self.opt_start_m

        # Transition is at end of last standing segment
        if last_standing_idx < len(self.segments):
            return self.segments[last_standing_idx]['end_m']

        return self.opt_start_m

    def run_smoothed_simulation(self, smoothing_method='cubic', preserve_energy=True):
        """
        Run simulation with smoothed power profile based on best discrete solution.

        After the optimizer finds the best discrete step-function power allocation,
        this method creates a smoothed version that's more realistic for actual
        cycling execution, then re-runs the simulation to get achievable time.

        Args:
            smoothing_method: 'cubic', 'linear', or 'rolling'
            preserve_energy: If True, scale smoothed profile to preserve total energy

        Returns:
            dict with:
                'result': Simulation result with smoothed power
                'T_200_smoothed': 200m time with smoothed power
                'T_200_discrete': Original discrete solution time
                'time_delta': Difference (smoothed - discrete)
                'P_smooth': Smoothed power grid
                'P_discrete': Original discrete power grid
        """
        if self.best_result is None or self.best_allocation is None:
            return None

        # Rebuild the discrete power grid from best solution
        energy_allocation = self.allocate_energy(self.best_allocation)

        # Get the speed profile from best result for position decisions
        best_speed_profile = {
            's': self.s_grid,
            'v': self.best_result['v']
        }

        # Build discrete power grid
        P_discrete, CdA_grid, _ = self.build_power_grid(
            energy_allocation,
            transition_m=None,
            speed_profile=best_speed_profile
        )

        # Create power curve ceiling function (uses seated curve as ceiling)
        def power_curve_ceiling(elapsed_time_s):
            return self.get_max_power(elapsed_time_s, 'seated')

        # Smooth the power profile, respecting both floor and ceiling constraints
        #
        # In FLATOUT mode, the timed section (695-895m) already has a perfectly smooth
        # power curve from linear interpolation of the power curve - no smoothing needed.
        # Only smooth the pre-timed section (480-695m) which has discrete step changes.
        #
        # In OPT mode, smooth the entire optimization zone.
        if self.timed_mode == 'FLATOUT':
            # Only smooth pre-timed section, preserve timed section exactly as is
            P_smooth = smooth_power_profile(
                self.s_grid, P_discrete, self.segments,
                smoothing_method=smoothing_method,
                preserve_energy=preserve_energy,
                P_base_grid=self.P_base_grid,
                min_power_pct=self.min_power_pct,
                power_curve_func=power_curve_ceiling,
                speed_profile=best_speed_profile,
                smooth_full_curve=False,  # Only smooth optimization zone (segments)
                smooth_end_m=self.timed_start_m  # Stop smoothing at 695m
            )
            # Copy timed section directly from discrete (already smooth from power curve)
            timed_mask = self.s_grid >= self.timed_start_m
            P_smooth[timed_mask] = P_discrete[timed_mask]
        else:
            P_smooth = smooth_power_profile(
                self.s_grid, P_discrete, self.segments,
                smoothing_method=smoothing_method,
                preserve_energy=preserve_energy,
                P_base_grid=self.P_base_grid,
                min_power_pct=self.min_power_pct,
                power_curve_func=power_curve_ceiling,
                speed_profile=best_speed_profile,
                smooth_full_curve=True
            )

        # Run simulation with smoothed power
        result_smooth = self.simulate_func(
            self.y_base_grid,
            CdA_grid,
            P_smooth,
            self.params,
            self.s_grid,
            self.theta_grid,
            label="smoothed"
        )

        T_200_discrete = self.best_result.get('T_200', float('inf'))
        T_200_smoothed = result_smooth.get('T_200', float('inf'))

        # Store smoothed result for export
        self.smoothed_result = result_smooth
        self.P_smooth = P_smooth
        self.P_discrete = P_discrete
        self.CdA_optimized = CdA_grid

        return {
            'result': result_smooth,
            'T_200_smoothed': T_200_smoothed,
            'T_200_discrete': T_200_discrete,
            'time_delta': T_200_smoothed - T_200_discrete,
            'P_smooth': P_smooth,
            'P_discrete': P_discrete,
            'CdA_grid': CdA_grid
        }

    def get_allocation_summary(self):
        """Get human-readable summary of best allocation."""
        if self.best_allocation is None:
            return "No optimization run yet"

        # Build position summary string
        position_str = "All seated"
        if self.best_positions:
            standing_segs = []
            seated_segs = []
            for seg, pos in zip(self.segments, self.best_positions):
                if pos == 'standing':
                    standing_segs.append(f"{seg['start_m']:.0f}-{seg['end_m']:.0f}m")
                else:
                    seated_segs.append(f"{seg['start_m']:.0f}-{seg['end_m']:.0f}m")

            if standing_segs:
                position_str = f"Standing: {', '.join(standing_segs)}"
            else:
                position_str = "All seated"

        # Calculate floor vs discretionary breakdown
        avg_speed_estimate = 17.0
        floor_energies = []
        for segment in self.segments:
            length_m = segment['length_m']
            seg_duration_est = length_m / avg_speed_estimate
            seg_mask = (self.s_grid >= segment['start_m']) & (self.s_grid < segment['end_m'])
            baseline_power = self.P_base_grid[seg_mask].mean() if seg_mask.any() else 0.0
            floor_power = baseline_power * self.min_power_pct
            floor_energies.append(floor_power * seg_duration_est)

        total_floor = sum(floor_energies)
        discretionary = max(0, self.total_energy_budget_J - total_floor)

        lines = [
            f"Energy Budget Optimization Summary",
            f"=" * 40,
            f"Total Budget: {self.total_energy_budget_J:.0f} J",
            f"  Floor energy (min {self.min_power_pct*100:.0f}%): {total_floor:.0f} J",
            f"  Discretionary: {discretionary:.0f} J",
            f"Best 200m Time: {self.best_time:.3f} s",
            f"Position: {position_str}",
            f"Position converged in {self.best_iterations_used} iteration(s)",
            f"Samples evaluated: {self.iteration_count}",
            f"",
            f"Energy Allocation by Segment (floor + discretionary %):",
        ]

        for seg_idx, (segment, frac) in enumerate(zip(self.segments, self.best_allocation)):
            # Calculate actual energy for this segment (floor + discretionary fraction)
            floor_J = floor_energies[seg_idx]
            disc_J = frac * discretionary
            total_seg_J = floor_J + disc_J
            disc_pct = frac * 100
            pos = self.best_positions[seg_idx] if self.best_positions else "?"
            pos_marker = "S" if pos == "standing" else "s"
            lines.append(f"  [{pos_marker}] {segment['name']} ({segment['start_m']:.0f}-{segment['end_m']:.0f}m): "
                        f"{floor_J:.0f}J floor + {disc_pct:.1f}% disc = {total_seg_J:.0f} J")

        return "\n".join(lines)


# ============================================
# Watts/CdA Analysis Functions
# ============================================

def calculate_watts_cda_analysis(result, s_grid, CdA_grid, params, interval_m=10.0):
    """
    Calculate watts/CdA efficiency at regular distance intervals.

    Watts/CdA represents the propulsive power normalized by aerodynamic drag area.
    Higher values mean more power is being applied per unit of drag.

    The breakeven watts/CdA is the value needed to maintain current speed against
    aero drag at that point (where power output = aero drag power).

    Args:
        result: Simulation result dict containing 'v', 'P_eff', 's' arrays
        s_grid: Distance grid array
        CdA_grid: CdA values at each grid point
        params: Simulation parameters dict (needs 'rho' for air density)
        interval_m: Distance interval for analysis points (default 10m)

    Returns:
        DataFrame with columns:
            s_m: Distance (m)
            v_ms: Velocity (m/s)
            P_W: Power (W)
            CdA_m2: CdA (m^2)
            watts_per_CdA: Power / CdA ratio (W/m^2)
            breakeven_watts_per_CdA: Watts/CdA needed to maintain speed (W/m^2)
            efficiency_ratio: watts_per_CdA / breakeven_watts_per_CdA
    """
    # Extract arrays from result
    v = result.get('v', np.array([]))
    P_eff = result.get('P_eff', np.array([]))
    s = result.get('s', s_grid)

    if len(v) == 0 or len(P_eff) == 0:
        return pd.DataFrame()

    # Get air density from params
    rho = params.get('rho', 1.225)  # kg/m^3

    # Determine analysis points at regular intervals
    s_min = s.min()
    s_max = s.max()
    analysis_points = np.arange(s_min, s_max + interval_m, interval_m)

    rows = []
    for s_m in analysis_points:
        # Find closest index
        idx = np.abs(s - s_m).argmin()

        if idx >= len(v) or idx >= len(P_eff) or idx >= len(CdA_grid):
            continue

        v_ms = v[idx]
        P_W = P_eff[idx]
        CdA_m2 = CdA_grid[idx]

        # Calculate watts/CdA
        if CdA_m2 > 0:
            watts_per_CdA = P_W / CdA_m2
        else:
            watts_per_CdA = 0.0

        # Calculate breakeven watts/CdA
        # Aero drag power = 0.5 * rho * CdA * v^3
        # At breakeven: P = 0.5 * rho * CdA * v^3
        # Therefore: P/CdA = 0.5 * rho * v^3
        breakeven_watts_per_CdA = 0.5 * rho * (v_ms ** 3)

        # Efficiency ratio: how much power we're putting in vs breakeven
        if breakeven_watts_per_CdA > 0:
            efficiency_ratio = watts_per_CdA / breakeven_watts_per_CdA
        else:
            efficiency_ratio = 0.0

        rows.append({
            's_m': s_m,
            'v_ms': v_ms,
            'v_kmh': v_ms * 3.6,
            'P_W': P_W,
            'CdA_m2': CdA_m2,
            'watts_per_CdA': watts_per_CdA,
            'breakeven_watts_per_CdA': breakeven_watts_per_CdA,
            'efficiency_ratio': efficiency_ratio
        })

    return pd.DataFrame(rows)


def calculate_aero_drag_power(v_ms, CdA_m2, rho=1.225):
    """
    Calculate aerodynamic drag power at a given speed.

    P_aero = 0.5 * rho * CdA * v^3

    Args:
        v_ms: Velocity in m/s
        CdA_m2: Drag area in m^2
        rho: Air density (default 1.225 kg/m^3)

    Returns:
        Aerodynamic drag power in Watts
    """
    return 0.5 * rho * CdA_m2 * (v_ms ** 3)


def calculate_breakeven_watts_cda(v_ms, rho=1.225):
    """
    Calculate the breakeven watts/CdA at a given speed.

    This is the power-to-drag-area ratio needed to maintain the current speed
    against aerodynamic resistance alone.

    At breakeven: P = P_aero = 0.5 * rho * CdA * v^3
    Therefore: P/CdA = 0.5 * rho * v^3

    Args:
        v_ms: Velocity in m/s
        rho: Air density (default 1.225 kg/m^3)

    Returns:
        Breakeven watts/CdA in W/m^2
    """
    return 0.5 * rho * (v_ms ** 3)


def smooth_power_profile(s_grid, P_grid, segments, smoothing_method='cubic',
                         window_m=25.0, preserve_energy=True,
                         P_base_grid=None, min_power_pct=0.0,
                         power_curve_func=None, speed_profile=None,
                         smooth_full_curve=True, smooth_end_m=None):
    """
    Smooth a discrete step-function power profile to create a realistic power curve.

    In real cycling, power cannot change instantaneously between segments. This function
    creates a smooth transition between segment power levels while optionally preserving
    total energy expenditure.

    Args:
        s_grid: Distance grid array (meters)
        P_grid: Power grid array (watts) - typically step-function from optimization
        segments: List of segment dicts with 'start_m', 'end_m' keys
        smoothing_method: 'cubic' (spline), 'linear', or 'rolling' (rolling average)
        window_m: Window size for rolling average method (meters)
        preserve_energy: If True, scale smoothed profile to match original total energy
        P_base_grid: Optional baseline power grid for minimum power floor constraint
        min_power_pct: Minimum power as fraction of baseline (e.g., 0.9 = 90%)
        power_curve_func: Optional function(elapsed_time_s) -> max_power_W for ceiling
        speed_profile: Dict with 's' and 'v' arrays for actual speed at each distance,
                       or None to use default estimate
        smooth_full_curve: If True, smooth from 0 to 895m; if False, only optimization zone
        smooth_end_m: Optional end distance for smoothing (e.g., 695m for FLATOUT mode).
                      If provided, smoothing stops at this distance.

    Returns:
        P_smooth: Smoothed power array (same shape as P_grid)
    """
    if len(s_grid) == 0 or len(P_grid) == 0:
        return P_grid.copy()

    # Build elapsed time array from speed profile or estimate
    # This is critical for accurate power curve constraint enforcement
    opt_start = segments[0]['start_m'] if segments else 480.0

    if speed_profile is not None and 's' in speed_profile and 'v' in speed_profile:
        # Use actual speed profile to compute elapsed time at each point
        # Create interpolator for speed
        speed_interp = interp1d(
            speed_profile['s'], speed_profile['v'],
            kind='linear', bounds_error=False,
            fill_value=(speed_profile['v'][0], speed_profile['v'][-1])
        )

        # Compute elapsed time from opt_start using actual speeds
        elapsed_time_grid = np.zeros_like(s_grid)
        ds_grid = np.diff(s_grid)
        ds_grid = np.append(ds_grid, ds_grid[-1])

        cumulative_time = 0.0
        opt_start_idx = np.abs(s_grid - opt_start).argmin()

        for i in range(len(s_grid)):
            if s_grid[i] >= opt_start:
                v_at_point = float(speed_interp(s_grid[i]))
                if v_at_point > 0:
                    dt = ds_grid[i] / v_at_point
                else:
                    dt = ds_grid[i] / 15.0  # Fallback
                cumulative_time += dt
                elapsed_time_grid[i] = cumulative_time
    else:
        # Fallback: estimate elapsed time using distance-based speed estimates
        elapsed_time_grid = np.zeros_like(s_grid)
        ds_grid = np.diff(s_grid)
        ds_grid = np.append(ds_grid, ds_grid[-1])

        cumulative_time = 0.0
        for i in range(len(s_grid)):
            if s_grid[i] >= opt_start:
                # Estimate speed based on distance into sprint
                dist_into_sprint = s_grid[i] - opt_start
                if dist_into_sprint < 70:  # First ~70m, accelerating
                    v_est = 14.0
                elif dist_into_sprint < 220:  # Peak speed zone
                    v_est = 17.5
                else:  # Timed section, slightly slower
                    v_est = 16.5

                dt = ds_grid[i] / v_est
                cumulative_time += dt
                elapsed_time_grid[i] = cumulative_time

    # Determine smoothing boundaries
    if smooth_full_curve:
        # Smooth the entire curve from start to finish
        smooth_start = s_grid[0]
        smooth_end = s_grid[-1]
    else:
        # Only smooth the optimization zone
        smooth_start = segments[0]['start_m']
        smooth_end = segments[-1]['end_m']

    # Override smooth_end if smooth_end_m is specified
    if smooth_end_m is not None:
        smooth_end = min(smooth_end, smooth_end_m)

    # Create sampling points for interpolation
    # Sample the power profile at regular intervals
    sample_interval = 25.0  # 25m intervals for sampling
    sample_points = []
    sample_powers = []

    s_current = smooth_start
    while s_current <= smooth_end:
        # Get power value at this point (find nearest grid point)
        idx = np.abs(s_grid - s_current).argmin()
        sample_points.append(s_current)
        sample_powers.append(P_grid[idx])
        s_current += sample_interval

    # Ensure we include the end point
    if sample_points[-1] < smooth_end:
        idx = np.abs(s_grid - smooth_end).argmin()
        sample_points.append(smooth_end)
        sample_powers.append(P_grid[idx])

    sample_points = np.array(sample_points)
    sample_powers = np.array(sample_powers)

    if len(sample_points) < 2:
        return P_grid.copy()

    # Calculate original total energy (for preservation)
    ds = np.diff(s_grid)
    ds = np.append(ds, ds[-1])  # Extend to match length

    smooth_mask = (s_grid >= smooth_start) & (s_grid <= smooth_end)
    original_energy = np.sum(P_grid[smooth_mask] * ds[smooth_mask])

    if smoothing_method == 'cubic':
        # Cubic spline interpolation through sample points
        spline = interp1d(sample_points, sample_powers, kind='cubic',
                         bounds_error=False, fill_value=(sample_powers[0], sample_powers[-1]))
        P_smooth = P_grid.copy()
        P_smooth[smooth_mask] = spline(s_grid[smooth_mask])

    elif smoothing_method == 'linear':
        # Linear interpolation through sample points
        interp_func = interp1d(sample_points, sample_powers, kind='linear',
                              bounds_error=False, fill_value=(sample_powers[0], sample_powers[-1]))
        P_smooth = P_grid.copy()
        P_smooth[smooth_mask] = interp_func(s_grid[smooth_mask])

    elif smoothing_method == 'rolling':
        # Rolling average smoothing
        P_smooth = P_grid.copy()

        # Convert window from meters to grid points
        avg_spacing = np.mean(np.diff(s_grid)) if len(s_grid) > 1 else 1.0
        window_pts = max(3, int(window_m / avg_spacing))
        if window_pts % 2 == 0:
            window_pts += 1  # Ensure odd for centered window

        # Apply rolling average
        half_window = window_pts // 2
        for i in range(len(s_grid)):
            if smooth_mask[i]:
                start_idx = max(0, i - half_window)
                end_idx = min(len(s_grid), i + half_window + 1)
                P_smooth[i] = P_grid[start_idx:end_idx].mean()
    else:
        raise ValueError(f"Unknown smoothing method: {smoothing_method}")

    # Ensure no negative power
    P_smooth = np.maximum(P_smooth, 0)

    # Optimization zone boundaries (constraints apply here regardless of smoothing range)
    opt_start = segments[0]['start_m'] if segments else 480.0
    opt_end = segments[-1]['end_m'] if segments else 895.0
    opt_mask = (s_grid >= opt_start) & (s_grid <= opt_end)

    # Get indices of optimization zone
    opt_indices = np.where(opt_mask)[0]

    # Apply minimum power floor constraint in optimization zone only
    # This prevents the smoothed curve from going below the allowed minimum
    P_floor = None
    if P_base_grid is not None and min_power_pct > 0:
        P_floor = P_base_grid * min_power_pct
        for i in opt_indices:
            P_smooth[i] = max(P_smooth[i], P_floor[i])

    # === CUMULATIVE ENERGY CONSTRAINT ===
    # The power curve gives max AVERAGE power sustainable from start to time T.
    # So cumulative energy at time T cannot exceed: curve(T) * T
    #
    # We enforce this by iterating through the optimization zone and capping
    # power at each point to ensure cumulative energy stays within bounds.
    # Multiple passes may be needed since capping affects later energy headroom.
    if power_curve_func is not None and len(opt_indices) > 0:
        # Compute dt for each point from elapsed_time_grid
        dt_grid = np.zeros_like(s_grid)
        for i in range(1, len(elapsed_time_grid)):
            dt_grid[i] = elapsed_time_grid[i] - elapsed_time_grid[i-1]
        if len(dt_grid) > 0:
            dt_grid[0] = dt_grid[1] if len(dt_grid) > 1 else 0.5

        for pass_num in range(3):
            cumulative_energy = 0.0
            any_capped = False

            for i in opt_indices:
                # Use pre-computed elapsed time from actual speed profile
                elapsed_time_s = max(1.0, elapsed_time_grid[i])

                # Instantaneous cap: can't exceed curve at this elapsed time
                instantaneous_cap = power_curve_func(elapsed_time_s)

                # Maximum cumulative energy allowed at this point
                max_cumulative_energy = instantaneous_cap * elapsed_time_s

                # Time for this segment
                segment_dt = dt_grid[i] if dt_grid[i] > 0 else 0.5

                # What's the max power we can use for this segment?
                # cumulative_energy + P * dt <= max_cumulative_energy
                # P <= (max_cumulative_energy - cumulative_energy) / dt
                energy_headroom = max_cumulative_energy - cumulative_energy
                max_power_this_segment = energy_headroom / segment_dt if segment_dt > 0 else float('inf')

                # Apply the most restrictive ceiling
                ceiling = min(max_power_this_segment, instantaneous_cap)

                # Track if we cap anything
                old_power = P_smooth[i]

                # Apply ceiling (but respect floor if set)
                if P_floor is not None:
                    # If floor > ceiling, we have a conflict - ceiling wins (physiological limit)
                    P_smooth[i] = min(P_smooth[i], ceiling)
                    P_smooth[i] = max(P_smooth[i], min(P_floor[i], ceiling))
                else:
                    P_smooth[i] = min(P_smooth[i], ceiling)

                if P_smooth[i] < old_power - 0.1:
                    any_capped = True

                # Update cumulative energy with actual power used
                cumulative_energy += P_smooth[i] * segment_dt

            # If nothing capped this pass, we're done
            if not any_capped:
                break

    # Energy preservation is DISABLED when power curve constraints are active
    # because scaling can push values above physiological limits which cannot be recovered.
    # The smoothed curve will use less total energy than the discrete, but will respect
    # the power curve constraint which is the hard physiological limit.
    #
    # If no power curve constraint, we can safely preserve energy.
    if preserve_energy and original_energy > 0 and power_curve_func is None:
        smoothed_energy = np.sum(P_smooth[smooth_mask] * ds[smooth_mask])
        if smoothed_energy > 0:
            scale_factor = original_energy / smoothed_energy
            P_smooth[smooth_mask] = P_smooth[smooth_mask] * scale_factor

            # Re-apply floor constraint after scaling
            if P_floor is not None:
                for i in opt_indices:
                    P_smooth[i] = max(P_smooth[i], P_floor[i])

    # === FINAL HARD CEILING ENFORCEMENT ===
    # After all smoothing and adjustments, ensure P_smooth NEVER exceeds instantaneous curve.
    # This is a hard physiological limit that cannot be violated.
    if power_curve_func is not None and len(opt_indices) > 0:
        for i in opt_indices:
            elapsed_time_s = max(1.0, elapsed_time_grid[i])
            ceiling = power_curve_func(elapsed_time_s)
            if P_smooth[i] > ceiling:
                P_smooth[i] = ceiling - 0.5  # Small buffer for safety

    return P_smooth


def get_watts_cda_summary(analysis_df, opt_start_m=480.0, timed_start_m=695.0):
    """
    Generate summary statistics from watts/CdA analysis.

    Args:
        analysis_df: DataFrame from calculate_watts_cda_analysis()
        opt_start_m: Start of optimization zone
        timed_start_m: Start of timed 200m section

    Returns:
        Dict with summary statistics
    """
    if analysis_df.empty:
        return {}

    # Filter to optimization zone
    opt_df = analysis_df[analysis_df['s_m'] >= opt_start_m]

    # Filter to timed section
    timed_df = analysis_df[
        (analysis_df['s_m'] >= timed_start_m) &
        (analysis_df['s_m'] <= timed_start_m + 200)
    ]

    summary = {
        'opt_zone': {
            'avg_watts_per_CdA': opt_df['watts_per_CdA'].mean() if len(opt_df) > 0 else 0,
            'avg_breakeven': opt_df['breakeven_watts_per_CdA'].mean() if len(opt_df) > 0 else 0,
            'avg_efficiency_ratio': opt_df['efficiency_ratio'].mean() if len(opt_df) > 0 else 0,
            'max_watts_per_CdA': opt_df['watts_per_CdA'].max() if len(opt_df) > 0 else 0,
            'min_watts_per_CdA': opt_df['watts_per_CdA'].min() if len(opt_df) > 0 else 0,
        },
        'timed_section': {
            'avg_watts_per_CdA': timed_df['watts_per_CdA'].mean() if len(timed_df) > 0 else 0,
            'avg_breakeven': timed_df['breakeven_watts_per_CdA'].mean() if len(timed_df) > 0 else 0,
            'avg_efficiency_ratio': timed_df['efficiency_ratio'].mean() if len(timed_df) > 0 else 0,
            'max_watts_per_CdA': timed_df['watts_per_CdA'].max() if len(timed_df) > 0 else 0,
            'min_watts_per_CdA': timed_df['watts_per_CdA'].min() if len(timed_df) > 0 else 0,
        },
        'overall': {
            'total_points': len(analysis_df),
            'speed_range_kmh': (analysis_df['v_kmh'].min(), analysis_df['v_kmh'].max()),
            'power_range_W': (analysis_df['P_W'].min(), analysis_df['P_W'].max()),
        }
    }

    return summary
class PowerRedistributionOptimizer:
    """
    Optimizer that finds the best power redistribution from a start point to finish,
    while maintaining constant average power (total work unchanged).

    Key constraint: Sum of all power adjustments = 0 (zero-sum).
    This ensures the rider does the same total work, just distributed differently
    across segments.

    Use cases:
    - "What if I push harder in turns and ease up on straights?"
    - "What if I front-load power early and coast more at the end?"
    - All while maintaining the same total energy expenditure.
    """

    def __init__(self,
                 simulate_func,
                 params: dict,
                 s_grid: np.ndarray,
                 theta_grid: np.ndarray,
                 y_base_grid: np.ndarray,
                 CdA_base_grid: np.ndarray,
                 P_base_grid: np.ndarray,
                 section_arr: np.ndarray = None,
                 opt_start_m: float = 430.0,
                 s_total: float = 895.0,
                 segment_mode: str = 'fixed',
                 segment_length_m: float = 10.0,
                 power_increment_W: float = 10.0,
                 max_adjustment_W: float = 100.0,
                 min_power_floor_pct: float = 0.5,
                 power_curve_func=None):
        """
        Args:
            simulate_func: Function(y, CdA, P, params, s_grid, theta_grid, label) -> result
            params: Simulation parameters dict
            s_grid: Distance grid array
            theta_grid: Track banking angle array
            y_base_grid: Rider lateral position array
            CdA_base_grid: Aerodynamic drag array
            P_base_grid: Baseline power profile from CSV
            section_arr: Array of section names at each grid point (for 'track_section' mode)
            opt_start_m: Distance where redistribution begins (default 430m)
            s_total: Total distance (default 895m)
            segment_mode: 'fixed' (fixed intervals) or 'track_section' (by track geometry)
            segment_length_m: Length of each segment for 'fixed' mode (default 10m)
            power_increment_W: Discrete power adjustment step (e.g., 5W, 10W, 15W)
            max_adjustment_W: Maximum +/- power adjustment per segment
            min_power_floor_pct: Minimum power as fraction of baseline (0.5 = 50%)
            power_curve_func: Optional function(elapsed_time_s) -> max_power_W for ceiling
        """
        self.simulate_func = simulate_func
        self.params = params
        self.s_grid = s_grid
        self.theta_grid = theta_grid
        self.y_base_grid = y_base_grid
        self.CdA_base_grid = CdA_base_grid
        self.P_base_grid = P_base_grid.copy()
        self.section_arr = section_arr
        self.opt_start_m = opt_start_m
        self.s_total = s_total
        self.segment_mode = segment_mode
        self.segment_length_m = segment_length_m
        self.power_increment_W = power_increment_W
        self.max_adjustment_W = max_adjustment_W
        self.min_power_floor_pct = min_power_floor_pct
        self.power_curve_func = power_curve_func

        # Build segments
        self.segments = self._build_segments()

        # Calculate baseline metrics for each segment
        self._calculate_segment_metrics()

        # Results storage
        self.best_time = float('inf')
        self.best_adjustments = None
        self.best_result = None
        self.baseline_result = None
        self.baseline_time = None
        self.iteration_count = 0
        self.valid_count = 0
        self.rejected_count = 0

        # For visualization - store current (possibly non-best) result
        self.current_result = None
        self.current_adjustments = None

    def _build_segments(self):
        """
        Build list of segments for power redistribution based on segment_mode.

        Returns:
            List of dicts: [{'start_m', 'end_m', 'name', 'length_m'}, ...]
        """
        segments = []

        if self.segment_mode == 'fixed':
            # Fixed-length segments (e.g., 10m each)
            s = self.opt_start_m
            seg_idx = 0
            while s < self.s_total:
                seg_end = min(s + self.segment_length_m, self.s_total)
                segments.append({
                    'start_m': s,
                    'end_m': seg_end,
                    'name': f"seg_{seg_idx}",
                    'length_m': seg_end - s
                })
                s = seg_end
                seg_idx += 1

        elif self.segment_mode == 'track_section':
            # Segment by track sections (HomeStraight, Turn1, etc.)
            if self.section_arr is None:
                raise ValueError("section_arr required for 'track_section' mode")

            current_section = None
            segment_start = None

            for i, s in enumerate(self.s_grid):
                if s < self.opt_start_m:
                    continue

                section = self.section_arr[i]

                if section != current_section:
                    # End previous segment
                    if current_section is not None and segment_start is not None:
                        segments.append({
                            'start_m': segment_start,
                            'end_m': s,
                            'name': current_section,
                            'length_m': s - segment_start
                        })
                    # Start new segment
                    current_section = section
                    segment_start = s

            # Add final segment
            if current_section is not None and segment_start is not None:
                segments.append({
                    'start_m': segment_start,
                    'end_m': self.s_total,
                    'name': current_section,
                    'length_m': self.s_total - segment_start
                })

        return segments

    def _calculate_segment_metrics(self):
        """
        Calculate baseline metrics for each segment:
        - Average power
        - Total energy (estimated)
        - Grid indices
        """
        for segment in self.segments:
            mask = (self.s_grid >= segment['start_m']) & (self.s_grid < segment['end_m'])
            segment['mask'] = mask
            segment['indices'] = np.where(mask)[0]

            if mask.any():
                segment['base_avg_power'] = self.P_base_grid[mask].mean()
                # Estimate energy: power * distance / speed
                # Use rough speed estimate of 17 m/s
                avg_speed_est = 17.0
                segment['base_energy_J'] = segment['base_avg_power'] * segment['length_m'] / avg_speed_est
            else:
                segment['base_avg_power'] = 0.0
                segment['base_energy_J'] = 0.0

        # Calculate total baseline energy from opt_start to finish
        self.total_base_energy_J = sum(s['base_energy_J'] for s in self.segments)
        self.avg_base_power_W = np.mean([s['base_avg_power'] for s in self.segments])

    def generate_zero_sum_adjustments(self):
        """
        Generate a random zero-sum adjustment vector with balanced distribution.

        Strategy:
        1. Generate random adjustments for ALL segments
        2. Center them (subtract mean) so they naturally sum to zero
        3. Scale to fit within max_adjustment bounds
        4. Discretize to nearest increment
        5. Distribute any rounding error across segments

        This creates realistic distributions where increases and decreases
        are spread throughout the course, not piled at the end.

        Returns:
            List of adjustments in watts, or None if invalid combination
        """
        n_segments = len(self.segments)
        if n_segments < 2:
            return [0.0]

        # Generate raw random adjustments for ALL segments
        raw = np.random.uniform(-1.0, 1.0, n_segments)

        # Center them so they sum to zero
        raw_centered = raw - np.mean(raw)

        # Randomize the magnitude (don't always use max adjustment)
        # Use a scale factor between 30% and 100% of max
        scale_factor = np.random.uniform(0.3, 1.0)
        target_max = scale_factor * self.max_adjustment_W

        # Scale so max absolute value equals target
        max_abs = np.max(np.abs(raw_centered))
        if max_abs > 0:
            scaled = raw_centered * (target_max / max_abs)
        else:
            scaled = raw_centered

        # Discretize to nearest power increment
        discretized = np.round(scaled / self.power_increment_W) * self.power_increment_W

        # Fix any rounding error in the sum
        total = np.sum(discretized)
        if abs(total) > 0.01:
            # Distribute the error across segments proportionally
            # Find segments that can absorb the adjustment
            correction_per_seg = total / n_segments
            correction_discrete = round(correction_per_seg / self.power_increment_W) * self.power_increment_W

            if correction_discrete != 0:
                # Apply small corrections to multiple segments
                n_corrections = int(abs(total / correction_discrete))
                sign = -1 if total > 0 else 1

                # Randomly select segments to adjust
                indices = np.random.choice(n_segments, min(n_corrections, n_segments), replace=False)
                for idx in indices:
                    new_val = discretized[idx] + sign * abs(correction_discrete)
                    # Only apply if it stays within bounds
                    if abs(new_val) <= self.max_adjustment_W:
                        discretized[idx] = new_val
                        total = np.sum(discretized)
                        if abs(total) < 0.01:
                            break

        # Final validation: ensure all within bounds
        if np.any(np.abs(discretized) > self.max_adjustment_W + 0.01):
            return None

        return list(discretized)

    def validate_adjustment(self, adjustments):
        """
        Validate that adjustments are feasible:
        1. Sum to zero (constant average power)
        2. No segment goes below min_power_floor
        3. No segment exceeds power curve ceiling (if provided)

        Args:
            adjustments: List of power adjustments (watts) per segment

        Returns:
            (is_valid, error_message_or_None)
        """
        # 1. Zero-sum check
        total = sum(adjustments)
        if abs(total) > 0.5:
            return False, f"Adjustments sum to {total:.1f}W, not zero"

        # 2. Power floor check
        for seg_idx, adj in enumerate(adjustments):
            segment = self.segments[seg_idx]
            base_power = segment['base_avg_power']
            new_power = base_power + adj

            floor = base_power * self.min_power_floor_pct
            if new_power < floor:
                return False, f"Segment {seg_idx} ({segment['name']}): power {new_power:.0f}W below floor {floor:.0f}W"

        # 3. Power curve ceiling (if provided) - simplified check
        # Full validation would require elapsed time which depends on simulation
        # Here we just check that adjusted power doesn't exceed a reasonable max
        if self.power_curve_func is not None:
            # Use 1-second power as absolute ceiling
            max_ceiling = self.power_curve_func(1.0)
            for seg_idx, adj in enumerate(adjustments):
                segment = self.segments[seg_idx]
                new_power = segment['base_avg_power'] + adj
                if new_power > max_ceiling:
                    return False, f"Segment {seg_idx}: power {new_power:.0f}W exceeds ceiling {max_ceiling:.0f}W"

        return True, None

    def apply_adjustments(self, adjustments):
        """
        Apply power adjustments to create a modified power grid.

        Args:
            adjustments: List of power adjustments (watts) per segment

        Returns:
            Modified power grid array
        """
        P_modified = self.P_base_grid.copy()

        for seg_idx, segment in enumerate(self.segments):
            adj = adjustments[seg_idx]
            mask = segment['mask']
            P_modified[mask] = P_modified[mask] + adj

        return P_modified

    def run_simulation(self, adjustments):
        """
        Run simulation with given power adjustments.

        Args:
            adjustments: List of power adjustments (watts) per segment

        Returns:
            (result_dict, is_valid)
        """
        P_modified = self.apply_adjustments(adjustments)

        result = self.simulate_func(
            self.y_base_grid,
            self.CdA_base_grid,
            P_modified,
            self.params,
            self.s_grid,
            self.theta_grid,
            label="redistribution"
        )

        # Store adjusted power in result for visualization
        result['P_adjusted'] = P_modified

        return result, True

    def run_baseline(self):
        """
        Run baseline simulation with no adjustments.

        Returns:
            Baseline result dict
        """
        result = self.simulate_func(
            self.y_base_grid,
            self.CdA_base_grid,
            self.P_base_grid,
            self.params,
            self.s_grid,
            self.theta_grid,
            label="baseline"
        )

        self.baseline_result = result
        self.baseline_time = result.get('T_200', float('inf'))

        return result

    def random_search(self, n_samples=5000,
                      progress_callback=None,
                      stop_check=None,
                      new_best_callback=None,
                      chart_update_callback=None,
                      chart_update_interval=50):
        """
        Random search over zero-sum adjustment combinations.

        Args:
            n_samples: Number of random samples to try
            progress_callback: Callback(iteration, total, best_time)
            stop_check: Callable returning True to stop
            new_best_callback: Callback when new best found
            chart_update_callback: Callback to update charts (called every chart_update_interval)
            chart_update_interval: How often to update charts (iterations)

        Returns:
            (best_adjustments, best_time, best_result, was_stopped)
        """
        # Run baseline first if not already done
        if self.baseline_result is None:
            self.run_baseline()

        was_stopped = False

        for i in range(n_samples):
            # Check if we should stop
            if stop_check and stop_check():
                was_stopped = True
                break

            self.iteration_count += 1

            # Generate zero-sum adjustments
            adjustments = self.generate_zero_sum_adjustments()
            if adjustments is None:
                self.rejected_count += 1
                continue

            # Validate adjustments
            is_valid, error_msg = self.validate_adjustment(adjustments)
            if not is_valid:
                self.rejected_count += 1
                continue

            # Run simulation
            try:
                result, sim_valid = self.run_simulation(adjustments)
                if not sim_valid:
                    self.rejected_count += 1
                    continue

                t_200 = result.get('T_200', float('inf'))
                self.valid_count += 1

                # Store current result for visualization (even if not best)
                self.current_result = result
                self.current_adjustments = adjustments

                # Check if this is the best
                if t_200 < self.best_time:
                    self.best_time = t_200
                    self.best_adjustments = adjustments.copy()
                    self.best_result = result

                    if new_best_callback:
                        new_best_callback(self.best_time, self.best_adjustments)

            except Exception as e:
                self.rejected_count += 1
                continue

            # Progress callback
            if progress_callback:
                progress_callback(self.iteration_count, n_samples, self.best_time)

            # Chart update callback (for sanity checking)
            if chart_update_callback and (self.iteration_count % chart_update_interval == 0):
                chart_update_callback(self.current_result, self.current_adjustments)

        return self.best_adjustments, self.best_time, self.best_result, was_stopped

    def differential_evolution_search(self, generations=100, population_size=50,
                                       progress_callback=None, stop_check=None):
        """
        Use scipy.optimize.differential_evolution for continuous optimization.

        This method treats ALL N segment adjustments as continuous variables
        and centers them (subtracts mean) to enforce zero-sum. This creates
        balanced distributions where increases and decreases are spread
        throughout, not piled at the end.

        Args:
            generations: Number of generations (maxiter)
            population_size: Population size
            progress_callback: Callback(iteration, total, best_time)
            stop_check: Callable returning True to stop

        Returns:
            (best_adjustments, best_time, best_result, was_stopped)
        """
        from scipy.optimize import differential_evolution

        # Run baseline first if not already done
        if self.baseline_result is None:
            self.run_baseline()

        n_segments = len(self.segments)
        if n_segments < 2:
            return [0.0], self.baseline_time, self.baseline_result, False

        was_stopped = False
        self.iteration_count = 0

        def objective(adj_array):
            """Objective function to minimize T_200."""
            self.iteration_count += 1

            # Check stop condition
            if stop_check and stop_check():
                return 1e6  # High penalty to stop

            # Center adjustments to force zero-sum (balanced distribution)
            adj_centered = np.array(adj_array) - np.mean(adj_array)

            # Discretize to power increment
            adj_discrete = np.round(adj_centered / self.power_increment_W) * self.power_increment_W

            # Fix any rounding error
            total = np.sum(adj_discrete)
            if abs(total) > 0.01:
                # Distribute error by adjusting one segment
                idx = np.argmin(np.abs(adj_discrete))  # Pick smallest adjustment
                adj_discrete[idx] -= total

            adjustments = list(adj_discrete)

            # Validate
            is_valid, _ = self.validate_adjustment(adjustments)
            if not is_valid:
                self.rejected_count += 1
                return 1e6  # Penalty for invalid

            # Run simulation
            try:
                result, sim_valid = self.run_simulation(adjustments)
                if not sim_valid:
                    self.rejected_count += 1
                    return 1e6

                t_200 = result.get('T_200', float('inf'))
                self.valid_count += 1

                # Track best
                if t_200 < self.best_time:
                    self.best_time = t_200
                    self.best_adjustments = adjustments.copy()
                    self.best_result = result

                # Progress callback
                if progress_callback:
                    progress_callback(self.iteration_count, generations * population_size, self.best_time)

                return t_200

            except Exception:
                self.rejected_count += 1
                return 1e6

        # Bounds for ALL N variables (optimizer explores full space, centering enforces zero-sum)
        bounds = [(-self.max_adjustment_W, self.max_adjustment_W)] * n_segments

        try:
            result = differential_evolution(
                objective,
                bounds,
                maxiter=generations,
                popsize=population_size,
                seed=42,
                disp=False,
                workers=1  # Single-threaded for compatibility
            )

            # Extract best solution
            if result.success or self.best_result is not None:
                return self.best_adjustments, self.best_time, self.best_result, was_stopped

        except Exception as e:
            pass

        return self.best_adjustments, self.best_time, self.best_result, was_stopped

    def get_segment_summary(self):
        """
        Get a summary table of segments with power, speed, and time data.

        Returns:
            List of dicts with segment info including:
            - Power: base, optimized, delta
            - Speed: base avg, optimized avg, delta (kph)
            - Time: base segment time, optimized segment time, delta (ms)
        """
        summary = []

        # Get velocity and time arrays from results
        v_base = self.baseline_result['v'] if self.baseline_result else None
        t_base = self.baseline_result['t'] if self.baseline_result else None
        v_opt = self.best_result['v'] if self.best_result else None
        t_opt = self.best_result['t'] if self.best_result else None

        for seg_idx, segment in enumerate(self.segments):
            mask = segment.get('mask')
            if mask is None:
                mask = (self.s_grid >= segment['start_m']) & (self.s_grid < segment['end_m'])

            row = {
                'segment': segment['name'],
                'start_m': segment['start_m'],
                'end_m': segment['end_m'],
                'base_power_W': segment['base_avg_power'],
            }

            # Calculate speed metrics (convert m/s to kph)
            if v_base is not None and mask.any():
                row['base_speed_kph'] = np.mean(v_base[mask]) * 3.6
            else:
                row['base_speed_kph'] = 0

            if v_opt is not None and mask.any():
                row['opt_speed_kph'] = np.mean(v_opt[mask]) * 3.6
            else:
                row['opt_speed_kph'] = row['base_speed_kph']

            row['speed_delta_kph'] = row['opt_speed_kph'] - row['base_speed_kph']

            # Calculate time spent in segment
            # Time = cumulative time at segment end - cumulative time at segment start
            indices = np.where(mask)[0]
            if len(indices) > 0 and t_base is not None:
                start_idx = indices[0]
                end_idx = indices[-1]
                row['base_time_s'] = t_base[end_idx] - t_base[start_idx] if start_idx > 0 else t_base[end_idx]
            else:
                row['base_time_s'] = 0

            if len(indices) > 0 and t_opt is not None:
                start_idx = indices[0]
                end_idx = indices[-1]
                row['opt_time_s'] = t_opt[end_idx] - t_opt[start_idx] if start_idx > 0 else t_opt[end_idx]
            else:
                row['opt_time_s'] = row['base_time_s']

            row['time_delta_ms'] = (row['opt_time_s'] - row['base_time_s']) * 1000

            # Power adjustments
            if self.best_adjustments is not None:
                adj = self.best_adjustments[seg_idx]
                row['adjustment_W'] = adj
                row['new_power_W'] = segment['base_avg_power'] + adj
                row['delta_pct'] = (adj / segment['base_avg_power'] * 100) if segment['base_avg_power'] > 0 else 0
            else:
                row['adjustment_W'] = 0
                row['new_power_W'] = segment['base_avg_power']
                row['delta_pct'] = 0

            summary.append(row)

        return summary

    def get_track_section_summary(self):
        """
        Get summary aggregated by track section (HomeStraight, Turn1, etc.).

        Returns:
            Dict mapping section_name -> aggregated stats
        """
        if self.segment_mode != 'track_section':
            # For fixed mode, group by track sections using section_arr
            if self.section_arr is None:
                return {}

        section_stats = {}

        for seg_idx, segment in enumerate(self.segments):
            section_name = segment['name']

            if section_name not in section_stats:
                section_stats[section_name] = {
                    'total_base_power': 0,
                    'total_adj_power': 0,
                    'total_adjustment': 0,
                    'count': 0,
                    'length_m': 0
                }

            stats = section_stats[section_name]
            stats['total_base_power'] += segment['base_avg_power']
            stats['length_m'] += segment['length_m']
            stats['count'] += 1

            if self.best_adjustments is not None:
                adj = self.best_adjustments[seg_idx]
                stats['total_adjustment'] += adj
                stats['total_adj_power'] += segment['base_avg_power'] + adj

        # Calculate averages
        for section_name, stats in section_stats.items():
            if stats['count'] > 0:
                stats['avg_base_power'] = stats['total_base_power'] / stats['count']
                stats['avg_adj_power'] = stats['total_adj_power'] / stats['count'] if self.best_adjustments else stats['avg_base_power']
                stats['avg_adjustment'] = stats['total_adjustment'] / stats['count'] if self.best_adjustments else 0

        return section_stats

    def run_smoothed_simulation(self, smoothing_window_m=25.0):
        """
        Run simulation with smoothed power profile based on best redistribution.

        The redistributed power has step changes at segment boundaries. This method
        creates a smoothed version using rolling average that's more realistic.

        Args:
            smoothing_window_m: Window size for rolling average (meters)

        Returns:
            dict with:
                'result': Simulation result with smoothed power
                'T_200_smoothed': 200m time with smoothed power
                'time_delta': Difference (smoothed - discrete)
                'P_smooth': Smoothed power grid
        """
        if self.best_adjustments is None or self.best_result is None:
            return None

        # Get discrete power profile from best result
        P_discrete = self.apply_adjustments(self.best_adjustments)

        # Use rolling average smoothing (doesn't overshoot like splines)
        P_smooth = smooth_power_profile(
            self.s_grid,
            P_discrete,
            self.segments,
            smoothing_method='rolling',
            window_m=smoothing_window_m,
            preserve_energy=True,
            P_base_grid=self.P_base_grid,
            min_power_pct=self.min_power_floor_pct,
            smooth_full_curve=False,  # Only smooth optimization zone
            smooth_end_m=None
        )

        # Run simulation with smoothed power
        result_smooth = self.simulate_func(
            self.y_base_grid,
            self.CdA_base_grid,
            P_smooth,
            self.params,
            self.s_grid,
            self.theta_grid,
            label="smoothed"
        )

        T_200_discrete = self.best_time
        T_200_smoothed = result_smooth.get('T_200', float('inf'))

        # Store smoothed result
        self.smoothed_result = result_smooth
        self.P_smooth = P_smooth
        self.P_discrete = P_discrete

        return {
            'result': result_smooth,
            'T_200_smoothed': T_200_smoothed,
            'T_200_discrete': T_200_discrete,
            'time_delta': T_200_smoothed - T_200_discrete,
            'P_smooth': P_smooth,
        }

    def get_adjustment_summary(self):
        """Get human-readable summary of optimization results."""
        if self.best_adjustments is None:
            return "No optimization run yet"

        delta_time = self.best_time - self.baseline_time if self.baseline_time else 0
        delta_str = f"{delta_time*1000:+.1f}ms" if delta_time != 0 else "0ms"

        if delta_time < 0:
            improvement_str = f"FASTER by {abs(delta_time)*1000:.1f}ms"
        elif delta_time > 0:
            improvement_str = f"SLOWER by {delta_time*1000:.1f}ms"
        else:
            improvement_str = "No change"

        lines = [
            "Power Redistribution Optimizer Results",
            "=" * 50,
            f"Start Distance: {self.opt_start_m:.0f}m",
            f"Segment Mode: {self.segment_mode} ({self.segment_length_m:.0f}m intervals)" if self.segment_mode == 'fixed' else f"Segment Mode: {self.segment_mode}",
            f"Power Increment: {self.power_increment_W:.0f}W",
            f"Max Adjustment: ±{self.max_adjustment_W:.0f}W",
            f"Segments: {len(self.segments)}",
            "",
            f"Baseline 200m time: {self.baseline_time:.3f}s" if self.baseline_time else "Baseline: Not run",
            f"Optimized 200m time: {self.best_time:.3f}s",
            f"Result: {improvement_str}",
            "",
            f"Iterations: {self.iteration_count}",
            f"Valid samples: {self.valid_count}",
            f"Rejected: {self.rejected_count}",
            "",
            "Power Adjustments by Segment:",
        ]

        # Show adjustments
        for seg_idx, segment in enumerate(self.segments):
            adj = self.best_adjustments[seg_idx]
            base_p = segment['base_avg_power']
            new_p = base_p + adj
            sign = "+" if adj >= 0 else ""
            lines.append(f"  {segment['start_m']:.0f}-{segment['end_m']:.0f}m: {sign}{adj:.0f}W ({base_p:.0f}W -> {new_p:.0f}W)")

        # Verify zero-sum
        total_adj = sum(self.best_adjustments)
        lines.append("")
        lines.append(f"Sum of adjustments: {total_adj:.1f}W (should be ~0)")

        return "\n".join(lines)
