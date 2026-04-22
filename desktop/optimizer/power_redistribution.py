"""
Flying 200 V2 - Power Redistribution Optimizer

ADVANCED optimizer that redistributes power across segments while maintaining
constant total work (zero-sum adjustments).

Key constraint: Sum of all power adjustments = 0
This ensures the rider does the same total work, just distributed differently.

Use cases:
- "What if I push harder in turns and ease up on straights?"
- "What if I front-load power early and coast more at the end?"

This is the ADVANCED mode - use EnergyBudgetOptimizer for typical optimization.
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Callable
from scipy.optimize import differential_evolution

# Import track geometry for track_section mode
import sys
import os
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from core.track import TrackGeometry, DEFAULT_TRACK, get_segment_at_distance


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class RedistributionSegment:
    """A segment for power redistribution."""
    name: str               # Human-readable name
    start_m: float          # Start distance [m]
    end_m: float            # End distance [m]
    length_m: float         # Segment length [m]
    base_avg_power_W: float = 0.0   # Baseline average power [W]
    base_energy_J: float = 0.0      # Baseline energy [J]
    mask: np.ndarray = None         # Grid mask for this segment


@dataclass
class RedistributionResult:
    """Results from power redistribution optimization."""
    success: bool                   # Did optimization complete?
    best_time_s: float              # Best 200m time [s]
    baseline_time_s: float          # Original baseline time [s]
    improvement_ms: float           # Time saved [ms]
    adjustments_W: List[float]      # Power adjustment per segment [W]
    iterations: int                 # Iterations used
    valid_samples: int              # Valid samples tested
    rejected_samples: int           # Rejected samples
    simulation_result: dict         # Full simulation result
    segment_summary: List[dict]     # Per-segment breakdown

    def get_summary(self) -> str:
        """Get human-readable summary."""
        lines = [
            "Power Redistribution Summary",
            "=" * 40,
            f"Baseline Time: {self.baseline_time_s:.3f} s",
            f"Optimized Time: {self.best_time_s:.3f} s",
            f"Improvement: {self.improvement_ms:.1f} ms",
            "",
            "Power Adjustments by Segment:",
        ]

        for seg in self.segment_summary:
            sign = "+" if seg['adjustment_W'] >= 0 else ""
            lines.append(
                f"  {seg['name']}: {seg['base_power_W']:.0f}W "
                f"({sign}{seg['adjustment_W']:.0f}W) = {seg['new_power_W']:.0f}W"
            )

        return "\n".join(lines)


# =============================================================================
# Power Redistribution Optimizer
# =============================================================================

class PowerRedistributionOptimizer:
    """
    Advanced optimizer that redistributes power while maintaining total work.

    Unlike EnergyBudgetOptimizer, this optimizer takes an existing power
    profile and adjusts it with zero-sum changes. The rider does the same
    total work, but distributed differently across segments.
    """

    def __init__(
        self,
        simulate_func: Callable,
        params: dict,
        s_grid: np.ndarray,
        theta_grid: np.ndarray,
        y_grid: np.ndarray,
        CdA_grid: np.ndarray,
        P_baseline: np.ndarray,
        optimization_start_m: float = 430.0,
        finish_m: float = 895.0,
        segment_mode: str = 'fixed',
        segment_length_m: float = 10.0,
        power_increment_W: float = 10.0,
        max_adjustment_W: float = 100.0,
        min_power_fraction: float = 0.5,
        power_curve_func: Optional[Callable] = None,
        track_geometry: Optional[TrackGeometry] = None,
    ):
        """
        Initialize the power redistribution optimizer.

        Args:
            simulate_func: Simulation function
            params: Simulation parameters
            s_grid: Distance grid [m]
            theta_grid: Banking angles [rad]
            y_grid: Lateral position [m]
            CdA_grid: Drag area [m^2]
            P_baseline: Baseline power profile [W]
            optimization_start_m: Where redistribution begins [m]
            finish_m: Finish line position [m]
            segment_mode: 'fixed' for equal intervals, 'track_section' for track geometry
            segment_length_m: Length per segment [m] (only for 'fixed' mode)
            power_increment_W: Discrete power step [W]
            max_adjustment_W: Maximum +/- adjustment per segment [W]
            min_power_fraction: Minimum power as fraction of baseline
            power_curve_func: Optional function(elapsed_time_s) -> max_power_W
            track_geometry: Track geometry for 'track_section' mode (defaults to Bromont)
        """
        self.simulate_func = simulate_func
        self.params = params
        self.s_grid = s_grid
        self.theta_grid = theta_grid
        self.y_grid = y_grid
        self.CdA_grid = CdA_grid
        self.P_baseline = P_baseline.copy()
        self.optimization_start_m = optimization_start_m
        self.finish_m = finish_m
        self.segment_mode = segment_mode
        self.segment_length_m = segment_length_m
        self.power_increment_W = power_increment_W
        self.max_adjustment_W = max_adjustment_W
        self.min_power_fraction = min_power_fraction
        self.power_curve_func = power_curve_func
        self.track_geometry = track_geometry or DEFAULT_TRACK

        # Build segments
        self.segments = self._build_segments()
        self._calculate_segment_metrics()

        # Effective power ceiling: the 1-second power from the curve, but never
        # below the observed baseline peak. Real baseline profiles from FIT
        # exports frequently contain 1-grid-point spikes above the curve's 1s
        # value (discretization + anaerobic surges). Treating those spikes as
        # hard ceiling violations rejects every sample that touches them, even
        # when the adjustment is negative. Floor the ceiling at 1.05 x peak so
        # we validate against "realistic headroom," not curve-fit artifacts.
        curve_ceiling = (
            float(self.power_curve_func(1.0))
            if self.power_curve_func is not None
            else float('inf')
        )
        baseline_peak = float(np.max(self.P_baseline)) if len(self.P_baseline) else 0.0
        self.effective_ceiling_W = max(curve_ceiling, baseline_peak * 1.05)

        # Results tracking
        self.best_time = float('inf')
        self.best_adjustments = None
        self.best_result = None
        self.baseline_result = None
        self.baseline_time = None
        self.iteration_count = 0
        self.valid_count = 0
        self.rejected_count = 0

    def _build_segments(self) -> List[RedistributionSegment]:
        """Build segments for redistribution based on segment_mode."""
        segments = []

        if self.segment_mode == 'fixed':
            # Fixed-length segments (e.g., 50m each)
            s = self.optimization_start_m
            seg_idx = 0
            while s < self.finish_m:
                seg_end = min(s + self.segment_length_m, self.finish_m)
                segments.append(RedistributionSegment(
                    name=f"Segment {seg_idx + 1}",
                    start_m=s,
                    end_m=seg_end,
                    length_m=seg_end - s,
                ))
                s = seg_end
                seg_idx += 1

        elif self.segment_mode == 'track_section':
            # Segment by track sections (HomeStraight, Turn1, Turn2, BackStraight, etc.)
            # Build a section array for the s_grid
            current_section = None
            segment_start = None

            for i, s in enumerate(self.s_grid):
                if s < self.optimization_start_m or s > self.finish_m:
                    continue

                # Get track section at this distance
                lap_idx, track_segment, _ = get_segment_at_distance(s, self.track_geometry)
                section_key = f"L{lap_idx}_{track_segment.name}"

                if section_key != current_section:
                    # Close previous segment if exists
                    if current_section is not None and segment_start is not None:
                        segments.append(RedistributionSegment(
                            name=current_section.replace('_', ' '),
                            start_m=segment_start,
                            end_m=s,
                            length_m=s - segment_start,
                        ))

                    # Start new segment
                    current_section = section_key
                    segment_start = s

            # Close final segment
            if current_section is not None and segment_start is not None:
                segments.append(RedistributionSegment(
                    name=current_section.replace('_', ' '),
                    start_m=segment_start,
                    end_m=self.finish_m,
                    length_m=self.finish_m - segment_start,
                ))

        return segments

    def _calculate_segment_metrics(self):
        """Calculate baseline metrics for each segment."""
        avg_speed_est = 17.0  # m/s

        for segment in self.segments:
            mask = (self.s_grid >= segment.start_m) & (self.s_grid < segment.end_m)
            segment.mask = mask

            if mask.any():
                segment.base_avg_power_W = self.P_baseline[mask].mean()
                segment.base_energy_J = segment.base_avg_power_W * segment.length_m / avg_speed_est
            else:
                segment.base_avg_power_W = 0.0
                segment.base_energy_J = 0.0

        self.total_base_energy_J = sum(s.base_energy_J for s in self.segments)

    def generate_zero_sum_adjustments(self) -> Optional[List[float]]:
        """
        Generate random zero-sum power adjustments.

        The sum of all adjustments equals zero, ensuring constant total work.

        Returns:
            List of adjustments in watts, or None if invalid
        """
        n_segments = len(self.segments)
        if n_segments < 2:
            return [0.0]

        # Random adjustments for all segments
        raw = np.random.uniform(-1.0, 1.0, n_segments)

        # Center to enforce zero-sum
        raw_centered = raw - np.mean(raw)

        # Random magnitude (30-100% of max)
        scale_factor = np.random.uniform(0.3, 1.0)
        target_max = scale_factor * self.max_adjustment_W

        # Scale
        max_abs = np.max(np.abs(raw_centered))
        if max_abs > 0:
            scaled = raw_centered * (target_max / max_abs)
        else:
            scaled = raw_centered

        # Discretize
        discretized = np.round(scaled / self.power_increment_W) * self.power_increment_W

        # Absorb the residual into a single segment that can still fit it
        # within bounds. Discretization breaks the zero-sum invariant (often by
        # 10-30W); spreading a correction across multiple segments is fragile
        # because each sub-correction must also be in-bounds. Landing the full
        # residual on one segment in a single shot is simpler and succeeds
        # more often. If no segment has headroom, reject the sample.
        residual = -float(np.sum(discretized))
        if abs(residual) > 0.01:
            placed = False
            for idx in np.random.permutation(n_segments):
                candidate = discretized[idx] + residual
                if abs(candidate) <= self.max_adjustment_W + 0.01:
                    discretized[idx] = candidate
                    placed = True
                    break
            if not placed:
                return None

        # Validate bounds
        if np.any(np.abs(discretized) > self.max_adjustment_W + 0.01):
            return None

        return list(discretized)

    def validate_adjustments(self, adjustments: List[float]) -> Tuple[bool, Optional[str]]:
        """
        Validate that adjustments are feasible.

        Checks:
        1. Sum to zero (constant total work)
        2. No segment below minimum power
        3. No segment above power curve ceiling

        Args:
            adjustments: Power adjustments per segment [W]

        Returns:
            (is_valid, error_message)
        """
        # Zero-sum check
        total = sum(adjustments)
        if abs(total) > 0.5:
            return False, f"Adjustments sum to {total:.1f}W, not zero"

        # Power floor check
        for seg_idx, adj in enumerate(adjustments):
            segment = self.segments[seg_idx]
            new_power = segment.base_avg_power_W + adj
            floor = segment.base_avg_power_W * self.min_power_fraction

            if new_power < floor:
                return False, f"Segment {seg_idx}: {new_power:.0f}W below floor {floor:.0f}W"

        # Power ceiling check (uses effective ceiling: max of power curve(1s)
        # and baseline peak with 5% headroom - see __init__ for rationale)
        if self.effective_ceiling_W != float('inf'):
            for seg_idx, adj in enumerate(adjustments):
                new_power = self.segments[seg_idx].base_avg_power_W + adj
                if new_power > self.effective_ceiling_W:
                    return False, f"Segment {seg_idx}: {new_power:.0f}W exceeds ceiling"

        return True, None

    def apply_adjustments(self, adjustments: List[float]) -> np.ndarray:
        """
        Apply power adjustments to create modified power grid.

        Args:
            adjustments: Power adjustments per segment [W]

        Returns:
            Modified power grid
        """
        P_modified = self.P_baseline.copy()

        for seg_idx, segment in enumerate(self.segments):
            adj = adjustments[seg_idx]
            P_modified[segment.mask] = P_modified[segment.mask] + adj

        return P_modified

    def run_simulation(self, adjustments: List[float]) -> Tuple[dict, bool]:
        """
        Run simulation with given adjustments.

        Args:
            adjustments: Power adjustments per segment

        Returns:
            (result_dict, is_valid)
        """
        P_modified = self.apply_adjustments(adjustments)

        result = self.simulate_func(
            self.y_grid,
            self.CdA_grid,
            P_modified,
            self.params,
            self.s_grid,
            self.theta_grid,
            label="redistribution"
        )

        result['P_adjusted'] = P_modified

        return result, True

    def run_baseline(self) -> dict:
        """Run baseline simulation with no adjustments."""
        result = self.simulate_func(
            self.y_grid,
            self.CdA_grid,
            self.P_baseline,
            self.params,
            self.s_grid,
            self.theta_grid,
            label="baseline"
        )

        self.baseline_result = result
        self.baseline_time = result.get('T_200', float('inf'))

        return result

    def optimize_random(
        self,
        n_samples: int = 5000,
        progress_callback: Optional[Callable] = None,
        stop_check: Optional[Callable] = None,
    ) -> RedistributionResult:
        """
        Random search over zero-sum adjustment combinations.

        Args:
            n_samples: Number of random samples
            progress_callback: Called with (iteration, total, best_time)
            stop_check: Returns True to stop early

        Returns:
            RedistributionResult with best solution
        """
        # Run baseline first
        if self.baseline_result is None:
            self.run_baseline()

        was_stopped = False

        for i in range(n_samples):
            if stop_check and stop_check():
                was_stopped = True
                break

            self.iteration_count += 1

            # Generate adjustments
            adjustments = self.generate_zero_sum_adjustments()
            if adjustments is None:
                self.rejected_count += 1
                continue

            # Validate
            is_valid, _ = self.validate_adjustments(adjustments)
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

                if t_200 < self.best_time:
                    self.best_time = t_200
                    self.best_adjustments = adjustments.copy()
                    self.best_result = result

            except Exception:
                self.rejected_count += 1
                continue

            if progress_callback:
                progress_callback(self.iteration_count, n_samples, self.best_time)

        return self._build_result()

    def optimize_differential_evolution(
        self,
        generations: int = 100,
        population_size: int = 50,
        progress_callback: Optional[Callable] = None,
        stop_check: Optional[Callable] = None,
    ) -> RedistributionResult:
        """
        Use differential evolution for continuous optimization.

        This method treats all segment adjustments as continuous variables
        and centers them to enforce zero-sum.

        Args:
            generations: Number of generations
            population_size: Population size
            progress_callback: Called with (iteration, total, best_time)
            stop_check: Returns True to stop early

        Returns:
            RedistributionResult with best solution
        """
        # Run baseline first
        if self.baseline_result is None:
            self.run_baseline()

        n_segments = len(self.segments)
        if n_segments < 2:
            return self._build_result()

        self.iteration_count = 0

        def objective(adj_array):
            """Objective function to minimize T_200."""
            self.iteration_count += 1

            if stop_check and stop_check():
                return 1e6

            # Center to force zero-sum
            adj_centered = np.array(adj_array) - np.mean(adj_array)

            # Discretize
            adj_discrete = np.round(adj_centered / self.power_increment_W) * self.power_increment_W

            # Fix rounding error
            total = np.sum(adj_discrete)
            if abs(total) > 0.01:
                idx = np.argmin(np.abs(adj_discrete))
                adj_discrete[idx] -= total

            adjustments = list(adj_discrete)

            # Validate
            is_valid, _ = self.validate_adjustments(adjustments)
            if not is_valid:
                self.rejected_count += 1
                return 1e6

            # Simulate
            try:
                result, sim_valid = self.run_simulation(adjustments)
                if not sim_valid:
                    self.rejected_count += 1
                    return 1e6

                t_200 = result.get('T_200', float('inf'))
                self.valid_count += 1

                if t_200 < self.best_time:
                    self.best_time = t_200
                    self.best_adjustments = adjustments.copy()
                    self.best_result = result

                if progress_callback:
                    progress_callback(
                        self.iteration_count,
                        generations * population_size,
                        self.best_time
                    )

                return t_200

            except Exception:
                self.rejected_count += 1
                return 1e6

        # Bounds for all segments
        bounds = [(-self.max_adjustment_W, self.max_adjustment_W)] * n_segments

        try:
            differential_evolution(
                objective,
                bounds,
                maxiter=generations,
                popsize=population_size,
                seed=42,
                disp=False,
                workers=1
            )
        except Exception:
            pass

        return self._build_result()

    def _build_result(self) -> RedistributionResult:
        """Build result object from current state."""
        if self.best_adjustments is not None:
            segment_summary = []
            for idx, (seg, adj) in enumerate(zip(self.segments, self.best_adjustments)):
                segment_summary.append({
                    'name': seg.name,
                    'start_m': seg.start_m,
                    'end_m': seg.end_m,
                    'base_power_W': seg.base_avg_power_W,
                    'adjustment_W': adj,
                    'new_power_W': seg.base_avg_power_W + adj,
                })

            improvement_ms = (self.baseline_time - self.best_time) * 1000

            return RedistributionResult(
                success=True,
                best_time_s=self.best_time,
                baseline_time_s=self.baseline_time,
                improvement_ms=improvement_ms,
                adjustments_W=self.best_adjustments,
                iterations=self.iteration_count,
                valid_samples=self.valid_count,
                rejected_samples=self.rejected_count,
                simulation_result=self.best_result,
                segment_summary=segment_summary,
            )
        else:
            return RedistributionResult(
                success=False,
                best_time_s=float('inf'),
                baseline_time_s=self.baseline_time or float('inf'),
                improvement_ms=0.0,
                adjustments_W=[],
                iterations=self.iteration_count,
                valid_samples=self.valid_count,
                rejected_samples=self.rejected_count,
                simulation_result={},
                segment_summary=[],
            )
