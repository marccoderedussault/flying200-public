"""
Flying 200 V2 - Session Management

Addresses user pain point: "Data sources ambiguous - which CSV is being simulated/optimized?"

The Session class tracks:
- Currently loaded profile (y_m, CdA, P_W data)
- Currently loaded power curves (seated/standing)
- Track selection
- Simulation configuration

All outputs include session info to eliminate ambiguity.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Tuple

from .track import TrackGeometry, DEFAULT_TRACK, AVAILABLE_TRACKS
from .physics import SimulationConfig


# =============================================================================
# Power Curve Data
# =============================================================================

@dataclass
class PowerCurve:
    """Power-duration curve for seated or standing position."""
    durations_s: np.ndarray      # durations in seconds
    powers_w: np.ndarray         # power at each duration in watts
    source: str = "manual"       # source description (e.g., "manual", "fit:file.fit")
    created_at: datetime = field(default_factory=datetime.now)

    def get_power_at_duration(self, duration_s: float) -> float:
        """Interpolate power at a given duration."""
        return float(np.interp(duration_s, self.durations_s, self.powers_w))

    @classmethod
    def from_dict(cls, data: Dict[int, float], source: str = "manual") -> "PowerCurve":
        """Create from a {duration: power} dictionary."""
        durations = np.array(sorted(data.keys()), dtype=float)
        powers = np.array([data[int(d)] for d in durations], dtype=float)
        return cls(durations_s=durations, powers_w=powers, source=source)

    def to_dict(self) -> Dict[int, float]:
        """Convert to {duration: power} dictionary."""
        return {int(d): float(p) for d, p in zip(self.durations_s, self.powers_w)}


@dataclass
class PowerCurves:
    """Container for seated and standing power curves."""
    seated: PowerCurve
    standing: PowerCurve

    def get_power(self, duration_s: float, position: str = "seated") -> float:
        """Get power at duration for specified position."""
        if position == "seated":
            return self.seated.get_power_at_duration(duration_s)
        elif position == "standing":
            return self.standing.get_power_at_duration(duration_s)
        else:
            raise ValueError(f"Unknown position: {position}")

    @property
    def source_description(self) -> str:
        """Human-readable description of power curve sources."""
        if self.seated.source == self.standing.source:
            return self.seated.source
        return f"Seated: {self.seated.source}, Standing: {self.standing.source}"


# =============================================================================
# Profile Data
# =============================================================================

@dataclass
class Profile:
    """Simulation profile (distance, position, CdA, power)."""
    s_m: np.ndarray              # distance along black line [m]
    y_m: np.ndarray              # lateral position [m]
    CdA_m2: np.ndarray           # drag area [m^2]
    P_W: np.ndarray              # target power [W]
    source: str = "unknown"       # source file path or description
    loaded_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_csv(cls, filepath: str) -> "Profile":
        """Load profile from CSV file."""
        df = pd.read_csv(filepath)
        df.columns = df.columns.str.strip()

        required = ["s_m", "y_m", "CdA_m2", "P_W"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Required column '{col}' not found in {filepath}")

        df = df.sort_values("s_m").reset_index(drop=True)

        return cls(
            s_m=df["s_m"].to_numpy(),
            y_m=df["y_m"].to_numpy(),
            CdA_m2=df["CdA_m2"].to_numpy(),
            P_W=df["P_W"].to_numpy(),
            source=str(Path(filepath).name),
        )

    def to_csv(self, filepath: str) -> None:
        """Save profile to CSV file."""
        df = pd.DataFrame({
            "s_m": self.s_m,
            "y_m": self.y_m,
            "CdA_m2": self.CdA_m2,
            "P_W": self.P_W,
        })
        df.to_csv(filepath, index=False)

    def interpolate_to_grid(self, s_grid: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Interpolate profile onto a simulation grid.

        Returns:
            (y_grid, CdA_grid, P_grid) interpolated to s_grid
        """
        y_grid = np.interp(s_grid, self.s_m, self.y_m)
        CdA_grid = np.interp(s_grid, self.s_m, self.CdA_m2)
        P_grid = np.interp(s_grid, self.s_m, self.P_W)
        return y_grid, CdA_grid, P_grid


# =============================================================================
# Session State
# =============================================================================

@dataclass
class Session:
    """
    Session state manager.

    Tracks all data sources to eliminate ambiguity about what's being simulated.
    All outputs should include session.header_text to show data provenance.

    Observer Pattern:
        Tabs can register callbacks via add_observer() to be notified when
        session data changes. This enables real-time sync across tabs.
    """
    profile: Optional[Profile] = None
    power_curves: Optional[PowerCurves] = None
    track: TrackGeometry = field(default_factory=lambda: DEFAULT_TRACK)
    config: SimulationConfig = field(default_factory=SimulationConfig)
    created_at: datetime = field(default_factory=datetime.now)

    # State flags
    _simulation_stale: bool = True
    _last_simulation_time: Optional[datetime] = None

    # Observer pattern for cross-tab synchronization
    _observers: List = field(default_factory=list)

    # Last simulation result (for Optimizer baseline)
    last_simulation_result: Optional[Dict] = None
    last_simulation_params: Optional[Dict] = None

    # Last optimization result (for Track View overlay)
    last_optimized_y_m: Optional[np.ndarray] = None
    last_optimized_s_m: Optional[np.ndarray] = None
    last_optimization_improvement_ms: float = 0.0

    @property
    def is_ready(self) -> bool:
        """True if session has all required data to run simulation."""
        return self.profile is not None and self.power_curves is not None

    @property
    def simulation_stale(self) -> bool:
        """True if data has changed since last simulation."""
        return self._simulation_stale

    def mark_simulation_complete(self) -> None:
        """Mark that a simulation has been run with current data."""
        self._simulation_stale = False
        self._last_simulation_time = datetime.now()

    def _invalidate_simulation(self) -> None:
        """Mark simulation as stale when data changes."""
        self._simulation_stale = True

    # -------------------------------------------------------------------------
    # Observer Pattern
    # -------------------------------------------------------------------------

    def add_observer(self, callback) -> None:
        """Register a callback to be notified when session data changes.

        Args:
            callback: Callable with no arguments, called on data changes
        """
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback) -> None:
        """Unregister an observer callback."""
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify_observers(self) -> None:
        """Notify all observers that session data has changed."""
        for callback in self._observers:
            try:
                callback()
            except Exception as e:
                # Don't let one bad observer break others
                print(f"Observer callback error: {e}")

    # -------------------------------------------------------------------------
    # Simulation Results (for Optimizer baseline)
    # -------------------------------------------------------------------------

    def set_simulation_result(self, result: Dict, params: Dict) -> None:
        """Store the last simulation result for use as Optimizer baseline.

        Args:
            result: Full simulation result dictionary (T_200, velocities, etc.)
            params: Parameters used (mass, rho, CdA, track, etc.)
        """
        self.last_simulation_result = result
        self.last_simulation_params = params
        self._last_simulation_time = datetime.now()
        self._simulation_stale = False
        self._notify_observers()

    def clear_simulation_result(self) -> None:
        """Clear stored simulation result."""
        self.last_simulation_result = None
        self.last_simulation_params = None
        self._notify_observers()

    def set_optimized_line(self, s_m: np.ndarray, y_m: np.ndarray, improvement_ms: float) -> None:
        """Store the optimized line for Track View overlay.

        Args:
            s_m: Distance array [m]
            y_m: Optimized lateral position array [m]
            improvement_ms: Time improvement in milliseconds (positive = faster)
        """
        self.last_optimized_s_m = s_m.copy()
        self.last_optimized_y_m = y_m.copy()
        self.last_optimization_improvement_ms = improvement_ms
        self._notify_observers()

    def clear_optimized_line(self) -> None:
        """Clear stored optimized line."""
        self.last_optimized_s_m = None
        self.last_optimized_y_m = None
        self.last_optimization_improvement_ms = 0.0
        self._notify_observers()

    # -------------------------------------------------------------------------
    # Profile Loading
    # -------------------------------------------------------------------------

    def load_profile(self, filepath: str) -> None:
        """Load a profile from CSV file."""
        self.profile = Profile.from_csv(filepath)
        self._invalidate_simulation()
        self._notify_observers()

    def set_profile(self, profile: Profile) -> None:
        """Set profile directly."""
        self.profile = profile
        self._invalidate_simulation()
        self._notify_observers()

    def update_profile_y_m(self, s_m: np.ndarray, y_m: np.ndarray) -> None:
        """Update just y_m values in existing profile.

        This allows TrackTab to sync marker positions to the profile
        without reloading the entire profile from CSV.

        Args:
            s_m: Distance array [m]
            y_m: Lateral position array [m]
        """
        if self.profile is None:
            return

        # Interpolate new y_m values onto profile's distance grid
        self.profile.y_m = np.interp(self.profile.s_m, s_m, y_m)
        self._invalidate_simulation()
        self._notify_observers()

    # -------------------------------------------------------------------------
    # Power Curve Loading
    # -------------------------------------------------------------------------

    def load_power_curves_from_csv(self, filepath: str) -> None:
        """Load power curves from CSV file with columns: duration_s, seated_W, standing_W"""
        df = pd.read_csv(filepath)
        df.columns = df.columns.str.strip()

        required = ["duration_s", "seated_W", "standing_W"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Required column '{col}' not found in {filepath}")

        df = df.dropna(subset=required).sort_values("duration_s").reset_index(drop=True)

        seated = PowerCurve(
            durations_s=df["duration_s"].to_numpy(),
            powers_w=df["seated_W"].to_numpy(),
            source=str(Path(filepath).name),
        )
        standing = PowerCurve(
            durations_s=df["duration_s"].to_numpy(),
            powers_w=df["standing_W"].to_numpy(),
            source=str(Path(filepath).name),
        )

        self.power_curves = PowerCurves(seated=seated, standing=standing)
        self._invalidate_simulation()
        self._notify_observers()

    def set_power_curves(
        self,
        seated_dict: Dict[int, float],
        standing_dict: Dict[int, float],
        source: str = "manual",
    ) -> None:
        """Set power curves from dictionaries.

        Args:
            seated_dict: {duration_s: power_W} for seated position
            standing_dict: {duration_s: power_W} for standing position
            source: Description of data source
        """
        self.power_curves = PowerCurves(
            seated=PowerCurve.from_dict(seated_dict, source),
            standing=PowerCurve.from_dict(standing_dict, source),
        )
        self._invalidate_simulation()
        self._notify_observers()

    # -------------------------------------------------------------------------
    # Track Selection
    # -------------------------------------------------------------------------

    def set_track(self, track_key: str) -> None:
        """Set track by key (e.g., 'bromont', 'milton')."""
        if track_key not in AVAILABLE_TRACKS:
            raise ValueError(f"Unknown track: {track_key}. Available: {list(AVAILABLE_TRACKS.keys())}")
        self.track = AVAILABLE_TRACKS[track_key]
        self._invalidate_simulation()
        self._notify_observers()

    # -------------------------------------------------------------------------
    # Header Text (for GUI and chart titles)
    # -------------------------------------------------------------------------

    @property
    def header_text(self) -> str:
        """
        Human-readable session state for GUI header and chart titles.

        This is the KEY OUTPUT that addresses the user's pain point:
        "Don't know which CSV is being simulated"

        Returns something like:
        "Profile: profile_f200.csv | Power Curve: power_curve_template.csv | Track: Bromont 250m"
        """
        parts = []

        if self.profile:
            parts.append(f"Profile: {self.profile.source}")
        else:
            parts.append("Profile: (none)")

        if self.power_curves:
            parts.append(f"Power Curve: {self.power_curves.source_description}")
        else:
            parts.append("Power Curve: (none)")

        parts.append(f"Track: {self.track.name}")

        return " | ".join(parts)

    @property
    def short_header(self) -> str:
        """Abbreviated header for compact display."""
        profile_name = self.profile.source if self.profile else "(none)"
        return f"{profile_name} @ {self.track.name}"

    @property
    def status_text(self) -> str:
        """Status message for GUI."""
        if not self.is_ready:
            missing = []
            if not self.profile:
                missing.append("profile")
            if not self.power_curves:
                missing.append("power curves")
            return f"Missing: {', '.join(missing)}"

        if self._simulation_stale:
            return "Ready (simulation stale - run simulation)"

        return f"Ready (last sim: {self._last_simulation_time.strftime('%H:%M:%S')})"

    # -------------------------------------------------------------------------
    # Chart Title Generation
    # -------------------------------------------------------------------------

    def chart_title(self, chart_type: str) -> str:
        """Generate a chart title that includes data source info.

        Args:
            chart_type: e.g., "Speed Profile", "Power Distribution"

        Returns:
            Title with session info, e.g., "Speed Profile | profile_f200.csv @ Bromont"
        """
        return f"{chart_type} | {self.short_header}"

    # -------------------------------------------------------------------------
    # String Representation
    # -------------------------------------------------------------------------

    def __str__(self) -> str:
        """String representation showing current session state."""
        lines = [
            "Flying 200 Session",
            "-" * 40,
            f"Profile: {self.profile.source if self.profile else '(not loaded)'}",
            f"Power Curves: {self.power_curves.source_description if self.power_curves else '(not loaded)'}",
            f"Track: {self.track.name}",
            f"Status: {self.status_text}",
        ]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"Session(profile={self.profile.source if self.profile else None}, track={self.track.name})"
