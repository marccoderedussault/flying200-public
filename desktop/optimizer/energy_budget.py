"""
Flying 200 V2 - Energy Budget Optimizer

PRIMARY optimizer that finds the best energy distribution across segments
to minimize 200m time, given a fixed energy budget.

Key concept: Instead of multiplying recorded power values, we allocate
a fixed energy budget (Joules) across segments. The optimizer finds
the distribution that minimizes time while respecting power curve ceilings.

Advantages:
- No constraint violations (can't overspend budget)
- Position-aware (uses correct power curve for standing vs seated)
- Physically intuitive (how to spend X Joules?)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable
from scipy.interpolate import interp1d


# =============================================================================
# Lap / section label helper
# =============================================================================

# Course is 4 full 250 m laps (course s=0 sits 150 m into Lap 0).
# Each lap = HomeStraight (60) + Turn1 (32.5) + Turn2 (32.5) + BackStraight (60)
#         + Turn3 (32.5) + Turn4 (32.5) = 250 m
_LAP_LENGTH_M = 250.0
_LAP0_OFFSET_M = 150.0
_LAP_SECTIONS = [
    ("HomeStraight", 60.0),
    ("Turn1",        32.5),
    ("Turn2",        32.5),
    ("BackStraight", 60.0),
    ("Turn3",        32.5),
    ("Turn4",        32.5),
]


def lap_section_label(s_m: float) -> str:
    """Return CSV-style label like 'Lap2_BackStraight_3of4' for a course position."""
    s_global = s_m + _LAP0_OFFSET_M
    lap_idx = int(s_global // _LAP_LENGTH_M)
    s_in_lap = s_global - lap_idx * _LAP_LENGTH_M
    s_acc = 0.0
    for name, length in _LAP_SECTIONS:
        if s_in_lap < s_acc + length:
            quarter = int(((s_in_lap - s_acc) / length) * 4) + 1
            quarter = max(1, min(4, quarter))
            return f"Lap{lap_idx}_{name}_{quarter}of4"
        s_acc += length
    return f"Lap{lap_idx}_End"


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class OptimizationSegment:
    """A segment of the course for optimization."""
    name: str               # Human-readable name (e.g., "Lap 3, Turn 1")
    start_m: float          # Start distance [m]
    end_m: float            # End distance [m]
    length_m: float         # Segment length [m]


@dataclass
class OptimizationResult:
    """Results from energy budget optimization."""
    success: bool                   # Did optimization complete successfully?
    best_time_s: float              # Best 200m time found [s]
    energy_allocation_J: List[float]  # Energy per segment [J]
    energy_fractions: List[float]   # Fraction of discretionary energy per segment
    positions: List[str]            # 'standing' or 'seated' per segment
    transition_m: Optional[float]   # Where rider sits down [m]
    iterations: int                 # Number of iterations used
    valid_samples: int              # Samples that passed constraints
    rejected_samples: int           # Samples that violated constraints
    simulation_result: dict         # Full simulation result from best solution
    segment_summary: List[dict]     # Per-segment breakdown

    def get_summary(self) -> str:
        """Get human-readable summary."""
        lines = [
            "Energy Budget Optimization Summary",
            "=" * 40,
            f"Best 200m Time: {self.best_time_s:.3f} s",
            f"Iterations: {self.iterations} ({self.valid_samples} valid, {self.rejected_samples} rejected)",
            "",
            "Energy Allocation by Segment:",
        ]

        for seg in self.segment_summary:
            pos_marker = "S" if seg['position'] == "standing" else "s"
            lines.append(
                f"  [{pos_marker}] {seg['name']}: {seg['energy_J']:.0f} J "
                f"({seg['fraction_pct']:.1f}% discretionary)"
            )

        return "\n".join(lines)


# =============================================================================
# Energy Budget Optimizer
# =============================================================================

class EnergyBudgetOptimizer:
    """
    Primary optimizer for Flying 200 energy distribution.

    Finds the best way to allocate a fixed energy budget across course
    segments to minimize 200m time. Respects power curve constraints
    and automatically chooses standing vs seated based on physics.
    """

    def __init__(
        self,
        simulate_func: Callable,
        params: dict,
        s_grid: np.ndarray,
        theta_grid: np.ndarray,
        y_grid: np.ndarray,
        CdA_standing: np.ndarray,
        CdA_seated: np.ndarray,
        P_baseline: np.ndarray,
        power_curve_seated: Dict[float, float],
        power_curve_standing: Dict[float, float],
        total_energy_budget_J: float,
        optimization_start_m: float = 480.0,
        timed_zone_start_m: float = 695.0,
        segment_length_m: float = 50.0,
        min_power_fraction: float = 0.3,
        flatout_mode: bool = True,
        max_transition_jump_W: float = 150.0,
    ):
        """
        Initialize the energy budget optimizer.

        Args:
            simulate_func: Simulation function(y, CdA, P, params, s_grid, theta_grid, label)
            params: Simulation parameters dict
            s_grid: Distance grid [m]
            theta_grid: Track banking angles [rad]
            y_grid: Rider lateral position [m]
            CdA_standing: Drag area when standing [m^2]
            CdA_seated: Drag area when seated [m^2]
            P_baseline: Baseline power profile from FIT file [W]
            power_curve_seated: Power curve {duration_s: max_W} for seated
            power_curve_standing: Power curve {duration_s: max_W} for standing
            total_energy_budget_J: Total joules to allocate (e.g., W')
            optimization_start_m: Where optimization begins [m]
            timed_zone_start_m: Start of timed 200m section [m]
            segment_length_m: Length of each optimization segment [m]
            min_power_fraction: Minimum power as fraction of baseline (0.3 = 30%)
            flatout_mode: If True, use max power curve in timed zone
            max_transition_jump_W: Max power jump at optimization start [W]
        """
        self.simulate_func = simulate_func
        self.params = params
        self.s_grid = s_grid
        self.theta_grid = theta_grid
        self.y_grid = y_grid
        self.CdA_standing = CdA_standing
        self.CdA_seated = CdA_seated
        self.P_baseline = P_baseline
        self.total_energy_budget_J = total_energy_budget_J
        self.optimization_start_m = optimization_start_m
        self.timed_zone_start_m = timed_zone_start_m
        self.segment_length_m = segment_length_m
        self.min_power_fraction = min_power_fraction
        self.flatout_mode = flatout_mode
        self.max_transition_jump_W = max_transition_jump_W

        # Power curve setup
        self.power_curve_seated = power_curve_seated or {}
        self.power_curve_standing = power_curve_standing or {}
        self._setup_power_interpolators()

        # Build optimization segments
        self.segments = self._build_segments()

        # Results tracking
        self.best_time = float('inf')
        self.best_allocation = None
        self.best_positions = None
        self.best_result = None
        self.iteration_count = 0
        self.valid_count = 0
        self.rejected_count = 0

    def _setup_power_interpolators(self):
        """Create interpolators for power curves."""
        def make_interpolator(curve_dict):
            if not curve_dict:
                return None
            durations = sorted(curve_dict.keys())
            powers = [curve_dict[d] for d in durations]
            return interp1d(
                durations, powers, kind='linear',
                fill_value=(powers[0], powers[-1]),
                bounds_error=False
            )

        self.seated_interp = make_interpolator(self.power_curve_seated)
        self.standing_interp = make_interpolator(self.power_curve_standing)

    def get_max_power(self, elapsed_time_s: float, position: str) -> float:
        """
        Get maximum power at given elapsed time and position.

        Args:
            elapsed_time_s: Time since sprint start [s]
            position: 'standing' or 'seated'

        Returns:
            Maximum sustainable power [W]
        """
        if position == 'standing' and self.standing_interp is not None:
            return float(self.standing_interp(elapsed_time_s))
        elif self.seated_interp is not None:
            return float(self.seated_interp(elapsed_time_s))
        else:
            return 1500.0  # Fallback

    def _build_segments(self) -> List[OptimizationSegment]:
        """Build list of segments for optimization."""
        segments = []
        s = self.optimization_start_m

        # In flatout mode, only optimize up to timed zone start
        end_m = self.timed_zone_start_m if self.flatout_mode else (self.timed_zone_start_m + 200.0)

        while s < end_m:
            seg_end = min(s + self.segment_length_m, end_m)
            mid = 0.5 * (s + seg_end)
            segments.append(OptimizationSegment(
                name=lap_section_label(mid),
                start_m=s,
                end_m=seg_end,
                length_m=seg_end - s,
            ))
            s = seg_end

        return segments

    def allocate_energy(self, fractions: List[float]) -> List[float]:
        """
        Convert fraction allocation to Joules per segment.

        Each segment gets guaranteed "floor" energy based on min_power_fraction,
        then discretionary budget is distributed according to fractions.

        Args:
            fractions: List of fractions (must sum to 1.0)

        Returns:
            List of Joules per segment
        """
        avg_speed_estimate = 17.0  # m/s

        # Calculate floor energy for each segment
        floor_energies = []
        for segment in self.segments:
            seg_duration_est = segment.length_m / avg_speed_estimate

            # Get baseline power for this segment
            seg_mask = (self.s_grid >= segment.start_m) & (self.s_grid < segment.end_m)
            baseline_power = self.P_baseline[seg_mask].mean() if seg_mask.any() else 0.0

            # Floor energy = min power x duration
            floor_power = baseline_power * self.min_power_fraction
            floor_energies.append(floor_power * seg_duration_est)

        total_floor = sum(floor_energies)

        # Discretionary energy = total budget - floor
        discretionary = max(0, self.total_energy_budget_J - total_floor)

        # Allocate: floor + fraction of discretionary
        allocations = []
        for i, frac in enumerate(fractions):
            seg_energy = floor_energies[i] + (frac * discretionary)
            allocations.append(seg_energy)

        return allocations

    def build_power_grid(
        self,
        energy_allocation: List[float],
        speed_profile: Optional[dict] = None,
    ) -> Tuple[np.ndarray, np.ndarray, bool]:
        """
        Build power and CdA grids from energy allocation.

        For each segment:
        1. Determine position (standing vs seated) based on power vs drag trade-off
        2. Calculate average power from energy allocation
        3. Cap by power curve at elapsed time
        4. Assign CdA based on position

        Args:
            energy_allocation: Joules per segment
            speed_profile: Optional {'s': array, 'v': array} from previous iteration

        Returns:
            (P_grid, CdA_grid, is_valid)
        """
        P_grid = np.zeros_like(self.s_grid)
        CdA_grid = np.zeros_like(self.s_grid)
        is_valid = True

        # Speed interpolator from previous iteration
        speed_interp = None
        if speed_profile is not None:
            speed_interp = interp1d(
                speed_profile['s'], speed_profile['v'],
                kind='linear', bounds_error=False,
                fill_value=(speed_profile['v'][0], speed_profile['v'][-1])
            )

        # CdA ratio for position decision
        cda_standing = self.CdA_standing[0]
        cda_seated = self.CdA_seated[0]
        cda_ratio = cda_standing / cda_seated if cda_seated > 0 else 1.0

        rho = self.params.get('rho', 1.225)
        elapsed_time = 0.0
        cumulative_energy = 0.0
        segment_positions = []

        for seg_idx, segment in enumerate(self.segments):
            seg_mask = (self.s_grid >= segment.start_m) & (self.s_grid < segment.end_m)

            # Estimate segment duration
            if speed_interp is not None:
                seg_midpoint = segment.start_m + segment.length_m / 2.0
                v_segment = float(speed_interp(seg_midpoint))
                seg_duration_est = segment.length_m / max(v_segment, 10.0)
            else:
                # First iteration: use distance-based estimates
                if segment.start_m < 550:
                    v_estimate = 14.0
                elif segment.start_m < 700:
                    v_estimate = 17.0
                else:
                    v_estimate = 16.5
                seg_duration_est = segment.length_m / v_estimate

            time_at_seg_end = elapsed_time + seg_duration_est

            # Average power from energy allocation
            energy_J = energy_allocation[seg_idx]
            avg_power = energy_J / seg_duration_est if seg_duration_est > 0 else 0.0

            # Speed estimate for position decision
            if speed_interp is not None:
                seg_midpoint = segment.start_m + segment.length_m / 2.0
                v_estimate = float(speed_interp(seg_midpoint))
            else:
                if segment.start_m < 550:
                    v_estimate = 14.0
                elif segment.start_m < 700:
                    v_estimate = 17.0
                else:
                    v_estimate = 16.5

            # Position decision: standing vs seated
            seated_max = self.get_max_power(time_at_seg_end, 'seated')
            standing_max = self.get_max_power(time_at_seg_end, 'standing')

            extra_power = standing_max - seated_max
            delta_cda = cda_standing - cda_seated
            extra_drag = 0.5 * rho * delta_cda * (v_estimate ** 3)

            # Stand only if power gain exceeds drag penalty AND we need the extra power
            if extra_power > extra_drag and avg_power > seated_max:
                position = 'standing'
            else:
                position = 'seated'

            segment_positions.append(position)

            # Assign CdA
            if position == 'standing':
                CdA_grid[seg_mask] = self.CdA_standing[seg_mask]
            else:
                CdA_grid[seg_mask] = self.CdA_seated[seg_mask]

            # Power curve constraint - At elapsed time t, with position p:
            # max instantaneous power = curve_p(t)
            # This represents max sustainable power at that fatigue level for that position
            #
            # Example: After 5s seated at 900W, at second 6:
            #   - If seated: power <= seated_curve(6)
            #   - If standing: power <= standing_curve(6)
            #
            # Energy budget is a SEPARATE constraint (total joules available)
            max_power = self.get_max_power(max(1.0, time_at_seg_end), position)

            # In flatout mode, leave small headroom for timed zone
            in_timed = segment.start_m >= self.timed_zone_start_m
            if self.flatout_mode and not in_timed:
                max_power *= 0.99

            # Minimum power floor
            baseline_avg = self.P_baseline[seg_mask].mean() if seg_mask.any() else 0.0
            min_power = min(baseline_avg * self.min_power_fraction, max_power)

            # Apply constraints
            if self.flatout_mode and in_timed:
                capped_power = max(min_power, max_power)
            else:
                capped_power = max(min_power, min(avg_power, max_power))

            # Transition constraint for first segment
            if seg_idx == 0 and self.max_transition_jump_W is not None:
                baseline_at_start = self.P_baseline[seg_mask].mean() if seg_mask.any() else capped_power
                max_allowed = baseline_at_start + self.max_transition_jump_W
                min_allowed = baseline_at_start - self.max_transition_jump_W
                capped_power = max(min_allowed, min(capped_power, max_allowed))
                capped_power = max(min_power, capped_power)

            P_grid[seg_mask] = capped_power

            # Update tracking
            cumulative_energy += capped_power * seg_duration_est
            elapsed_time += seg_duration_est

        self._last_positions = segment_positions

        # Fill pre-optimization zone with baseline
        pre_opt_mask = self.s_grid < self.optimization_start_m
        P_grid[pre_opt_mask] = self.P_baseline[pre_opt_mask]
        CdA_grid[pre_opt_mask] = self.CdA_seated[pre_opt_mask]

        # Fill timed zone (695-895m) when in flatout mode
        # In flatout mode, segments only go up to timed_zone_start, so we need
        # to fill the timed zone separately with max power curve values
        #
        # CONSTRAINT: At elapsed time t, power <= curve(t, position)
        # In timed zone we use seated (better aero), so power <= seated_curve(t)
        if self.flatout_mode:
            timed_mask = self.s_grid >= self.timed_zone_start_m
            if timed_mask.any():
                # Track elapsed time through timed zone
                timed_elapsed_time = elapsed_time

                # For timed zone, use seated position (better aero) at max power
                CdA_grid[timed_mask] = self.CdA_seated[timed_mask]

                # Fill timed zone with max power at each point
                timed_indices = np.where(timed_mask)[0]
                ds = self.s_grid[1] - self.s_grid[0] if len(self.s_grid) > 1 else 0.25

                for i, idx in enumerate(timed_indices):
                    # Estimate time at this point using speed from previous iteration
                    if speed_interp is not None:
                        v_at_point = float(speed_interp(self.s_grid[idx]))
                        dt = ds / max(v_at_point, 10.0)
                    else:
                        dt = ds / 17.0  # ~17 m/s estimate

                    point_time = timed_elapsed_time + (i * dt)

                    # At elapsed time t, max power = seated_curve(t)
                    # This is the instantaneous power limit at this fatigue level
                    max_power_seated = self.get_max_power(max(1.0, point_time), 'seated')

                    P_grid[idx] = max_power_seated

        return P_grid, CdA_grid, is_valid

    def run_simulation_iterative(
        self,
        energy_allocation: List[float],
        max_iterations: int = 3,
        baseline_speed_profile: Optional[dict] = None,
    ) -> Tuple[Optional[dict], List[str], int, bool]:
        """
        Run simulation with iterative position refinement.

        Position decisions depend on speed, which we don't know until after
        simulation. This method iterates until positions converge.

        Args:
            energy_allocation: Joules per segment
            max_iterations: Maximum iterations
            baseline_speed_profile: Speed profile for first iteration

        Returns:
            (result, positions, iterations_used, is_valid)
        """
        last_positions = None
        speed_profile = baseline_speed_profile
        result = None
        current_positions = []

        for iteration in range(max_iterations):
            P_grid, CdA_grid, is_valid = self.build_power_grid(
                energy_allocation, speed_profile=speed_profile
            )

            if not is_valid:
                return None, [], iteration, False

            result = self.simulate_func(
                self.y_grid,
                CdA_grid,
                P_grid,
                self.params,
                self.s_grid,
                self.theta_grid,
                label=f"iter_{iteration}"
            )

            speed_profile = {'s': self.s_grid, 'v': result['v']}
            current_positions = self._last_positions.copy()

            if last_positions is not None and current_positions == last_positions:
                break

            last_positions = current_positions

        return result, current_positions, iteration + 1, True

    def optimize(
        self,
        n_samples: int = 1000,
        energy_levels: int = 10,
        progress_callback: Optional[Callable] = None,
        stop_check: Optional[Callable] = None,
        baseline_result: Optional[dict] = None,
    ) -> OptimizationResult:
        """
        Run random search optimization over energy distributions.

        Args:
            n_samples: Number of random samples to try
            energy_levels: Discrete energy levels for allocation
            progress_callback: Called with (iteration, total, best_time)
            stop_check: Returns True to stop early
            baseline_result: Result from baseline simulation (provides speeds)

        Returns:
            OptimizationResult with best solution
        """
        n_segments = len(self.segments)

        # Extract baseline speed profile
        baseline_speed_profile = None
        if baseline_result is not None and 'v' in baseline_result:
            baseline_speed_profile = {'s': self.s_grid, 'v': baseline_result['v']}

        was_stopped = False

        for i in range(n_samples):
            if stop_check and stop_check():
                was_stopped = True
                break

            self.iteration_count += 1

            # Random energy allocation (discrete levels)
            raw_levels = np.random.randint(1, energy_levels + 1, n_segments)
            fractions = raw_levels / raw_levels.sum()
            energy_allocation = self.allocate_energy(list(fractions))

            try:
                result, positions, iters_used, is_valid = self.run_simulation_iterative(
                    energy_allocation,
                    max_iterations=3,
                    baseline_speed_profile=baseline_speed_profile
                )

                if not is_valid or result is None:
                    self.rejected_count += 1
                    continue

                t_200 = result.get('T_200', float('inf'))
                self.valid_count += 1

                if t_200 < self.best_time:
                    self.best_time = t_200
                    self.best_allocation = list(fractions)
                    self.best_positions = positions
                    self.best_result = result

            except Exception:
                self.rejected_count += 1

            if progress_callback:
                progress_callback(self.iteration_count, n_samples, self.best_time)

        # Build result
        if self.best_allocation is not None:
            energy_J = self.allocate_energy(self.best_allocation)

            # Build segment summary
            segment_summary = []
            for idx, (seg, frac, energy, pos) in enumerate(zip(
                self.segments, self.best_allocation, energy_J,
                self.best_positions or ['seated'] * len(self.segments)
            )):
                segment_summary.append({
                    'name': seg.name,
                    'start_m': seg.start_m,
                    'end_m': seg.end_m,
                    'energy_J': energy,
                    'fraction_pct': frac * 100,
                    'position': pos,
                })

            # Find transition point
            transition_m = None
            if self.best_positions:
                last_standing_idx = -1
                for idx, pos in enumerate(self.best_positions):
                    if pos == 'standing':
                        last_standing_idx = idx
                if last_standing_idx >= 0:
                    transition_m = self.segments[last_standing_idx].end_m

            return OptimizationResult(
                success=True,
                best_time_s=self.best_time,
                energy_allocation_J=energy_J,
                energy_fractions=self.best_allocation,
                positions=self.best_positions or [],
                transition_m=transition_m,
                iterations=self.iteration_count,
                valid_samples=self.valid_count,
                rejected_samples=self.rejected_count,
                simulation_result=self.best_result,
                segment_summary=segment_summary,
            )
        else:
            return OptimizationResult(
                success=False,
                best_time_s=float('inf'),
                energy_allocation_J=[],
                energy_fractions=[],
                positions=[],
                transition_m=None,
                iterations=self.iteration_count,
                valid_samples=self.valid_count,
                rejected_samples=self.rejected_count,
                simulation_result={},
                segment_summary=[],
            )
