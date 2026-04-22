"""
Flying 200 V2 - Track Geometry Module

Named segments for human-readable output instead of raw distance markers.
Addresses user pain point: "695m means nothing - need lap + segment descriptors"

Supports two built-in tracks:
- Bromont 250m (default)
- Milton 250m (Mattamy Velodrome, Canada)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


# =============================================================================
# Track Segment Definition
# =============================================================================

@dataclass
class Segment:
    """A named segment of the track within a single lap."""
    name: str               # e.g., "HomeStraight", "Turn1"
    display_name: str       # e.g., "Home Straight", "Turn 1"
    start_m: float          # start distance within lap [m]
    end_m: float            # end distance within lap [m]
    is_turn: bool           # True for turns, False for straights


@dataclass
class TrackGeometry:
    """Complete track geometry definition."""
    name: str                       # e.g., "Bromont 250m"
    length_m: float                 # lap length [m]
    straight_length_m: float        # length of each straight [m]
    turn_radius_m: float            # radius of turns at black line [m]
    banking_straight_deg: float     # banking angle on straights [deg]
    banking_turn_deg: float         # banking angle in turns [deg]
    width_m: float = 7.0            # track width [m] - UCI minimum is 7m
    altitude_m: float = 0.0         # track altitude above sea level [m]
    finish_line_dist_m: Optional[float] = None  # finish line position on home straight [m]
    description: str = ""           # Human-readable track description
    segments: List[Segment] = field(default_factory=list)

    @property
    def arc_length_m(self) -> float:
        """Length of each bend (half-circle)."""
        return np.pi * self.turn_radius_m

    @property
    def segment_names(self) -> List[str]:
        """List of segment names in order."""
        return [s.name for s in self.segments]

    def get_segment_at_lap_distance(self, s_in_lap: float) -> Segment:
        """Get the segment at a given distance within a lap."""
        s_mod = s_in_lap % self.length_m
        for seg in self.segments:
            if seg.start_m <= s_mod < seg.end_m:
                return seg
        # Edge case: exactly at lap end
        return self.segments[-1]


# =============================================================================
# Bromont 250m Track Definition
# =============================================================================

def _create_bromont_250m() -> TrackGeometry:
    """Create the Bromont 250m track geometry."""
    length = 250.0
    straight = 59.0
    radius = (length - 2.0 * straight) / (2.0 * np.pi)  # ~21.1m
    arc = np.pi * radius  # ~66.0m per bend

    # Segment boundaries (within a single lap, starting at Home Straight)
    # Layout: HomeStraight -> Turn1 -> Turn2 -> BackStraight -> Turn3 -> Turn4
    segments = [
        Segment(
            name="HomeStraight",
            display_name="Home Straight",
            start_m=0.0,
            end_m=straight,
            is_turn=False,
        ),
        Segment(
            name="Turn1",
            display_name="Turn 1",
            start_m=straight,
            end_m=straight + arc / 2,
            is_turn=True,
        ),
        Segment(
            name="Turn2",
            display_name="Turn 2",
            start_m=straight + arc / 2,
            end_m=straight + arc,
            is_turn=True,
        ),
        Segment(
            name="BackStraight",
            display_name="Back Straight",
            start_m=straight + arc,
            end_m=straight + arc + straight,
            is_turn=False,
        ),
        Segment(
            name="Turn3",
            display_name="Turn 3",
            start_m=straight + arc + straight,
            end_m=straight + arc + straight + arc / 2,
            is_turn=True,
        ),
        Segment(
            name="Turn4",
            display_name="Turn 4",
            start_m=straight + arc + straight + arc / 2,
            end_m=length,
            is_turn=True,
        ),
    ]

    return TrackGeometry(
        name="Bromont 250m",
        length_m=length,
        straight_length_m=straight,
        turn_radius_m=radius,
        banking_straight_deg=12.0,
        banking_turn_deg=42.0,
        width_m=7.5,  # Atlanta Olympic track specs
        altitude_m=200.0,  # Bromont, Quebec ~200m elevation
        description=(
            "Bromont Velodrome, Quebec, Canada (Atlanta 1996 Olympic track). "
            f"59m straights, {radius:.1f}m turn radius, 42° banking in turns. "
            "Longer straights = more acceleration distance, tighter turns."
        ),
        segments=segments,
    )


# =============================================================================
# Milton 250m Track Definition
# =============================================================================

def _create_milton_250m() -> TrackGeometry:
    """Create the Milton (Mattamy) 250m track geometry."""
    length = 250.0
    straight = 41.0  # Milton has shorter straights
    radius = (length - 2.0 * straight) / (2.0 * np.pi)  # ~26.7m (larger radius)
    arc = np.pi * radius

    # Same segment layout as Bromont
    segments = [
        Segment(
            name="HomeStraight",
            display_name="Home Straight",
            start_m=0.0,
            end_m=straight,
            is_turn=False,
        ),
        Segment(
            name="Turn1",
            display_name="Turn 1",
            start_m=straight,
            end_m=straight + arc / 2,
            is_turn=True,
        ),
        Segment(
            name="Turn2",
            display_name="Turn 2",
            start_m=straight + arc / 2,
            end_m=straight + arc,
            is_turn=True,
        ),
        Segment(
            name="BackStraight",
            display_name="Back Straight",
            start_m=straight + arc,
            end_m=straight + arc + straight,
            is_turn=False,
        ),
        Segment(
            name="Turn3",
            display_name="Turn 3",
            start_m=straight + arc + straight,
            end_m=straight + arc + straight + arc / 2,
            is_turn=True,
        ),
        Segment(
            name="Turn4",
            display_name="Turn 4",
            start_m=straight + arc + straight + arc / 2,
            end_m=length,
            is_turn=True,
        ),
    ]

    return TrackGeometry(
        name="Milton 250m (Mattamy)",
        length_m=length,
        straight_length_m=straight,
        turn_radius_m=radius,
        banking_straight_deg=13.0,  # Milton has slightly different banking
        banking_turn_deg=42.0,
        width_m=7.0,  # Standard UCI width
        altitude_m=176.0,  # Milton, Ontario ~176m elevation
        description=(
            "Mattamy National Cycling Centre, Milton, Ontario, Canada. "
            f"41m straights, {radius:.1f}m turn radius, 42° banking in turns. "
            "Shorter straights, wider turns = faster turn speeds, more sustained effort."
        ),
        segments=segments,
    )


# =============================================================================
# Track Instances
# =============================================================================

BROMONT_250M = _create_bromont_250m()
MILTON_250M = _create_milton_250m()


# =============================================================================
# Konya 250m Track Definition
# =============================================================================

def _create_konya_250m() -> TrackGeometry:
    """Create the Konya (Turkey) 250m track geometry.

    Turkey's first Olympic velodrome, opened 2021.
    UCI homologated for international events including UCI Track Nations Cup.
    Surface: Finnish spruce (wood), 8m width.

    Geometry estimated using centrifugal force calculations:
    - 45.5° banking is steeper than Milton (42°), enabling higher cornering speeds
    - Matthew Richardson's 8.857s flying 200 (81.3 km/h avg) indicates very fast track
    - Shorter straights / larger radius than Milton = longer, faster bends
    - Contrast with Bromont's tight 21.1m radius - Konya optimized for speed
    """
    length = 250.0
    straight = 38.0  # Shortest straights = largest radius bends for maximum cornering speed
    radius = (length - 2.0 * straight) / (2.0 * np.pi)  # ~27.7m - widest turns of the three
    arc = np.pi * radius

    segments = [
        Segment(
            name="HomeStraight",
            display_name="Home Straight",
            start_m=0.0,
            end_m=straight,
            is_turn=False,
        ),
        Segment(
            name="Turn1",
            display_name="Turn 1",
            start_m=straight,
            end_m=straight + arc / 2,
            is_turn=True,
        ),
        Segment(
            name="Turn2",
            display_name="Turn 2",
            start_m=straight + arc / 2,
            end_m=straight + arc,
            is_turn=True,
        ),
        Segment(
            name="BackStraight",
            display_name="Back Straight",
            start_m=straight + arc,
            end_m=straight + arc + straight,
            is_turn=False,
        ),
        Segment(
            name="Turn3",
            display_name="Turn 3",
            start_m=straight + arc + straight,
            end_m=straight + arc + straight + arc / 2,
            is_turn=True,
        ),
        Segment(
            name="Turn4",
            display_name="Turn 4",
            start_m=straight + arc + straight + arc / 2,
            end_m=length,
            is_turn=True,
        ),
    ]

    return TrackGeometry(
        name="Konya 250m",
        length_m=length,
        straight_length_m=straight,
        turn_radius_m=radius,
        banking_straight_deg=12.69,  # Specified value
        banking_turn_deg=45.5,       # Specified value
        width_m=8.0,                 # Wider than UCI minimum
        altitude_m=1020.0,           # Konya, Turkey ~1020m elevation (HIGH ALTITUDE!)
        description=(
            "Konya Velodrome, Turkey. Turkey's first Olympic velodrome (2021). "
            f"38m straights, {radius:.1f}m turn radius, 45.5° banking in turns. "
            "Finnish spruce surface, 8m width. UCI homologated - fastest track geometry. "
            "HIGH ALTITUDE (1020m) = lower air density = faster times."
        ),
        segments=segments,
    )


KONYA_250M = _create_konya_250m()

AVAILABLE_TRACKS: Dict[str, TrackGeometry] = {
    "Bromont": BROMONT_250M,
    "Milton": MILTON_250M,
    "Konya": KONYA_250M,
}

DEFAULT_TRACK = BROMONT_250M


def create_track_from_params(
    name: str,
    lap_length: float,
    straight_length_m: float,
    banking_turn_deg: float,
    banking_straight_deg: float,
    width_m: float = 7.0,
    altitude_m: float = 0.0,
    finish_line_dist_m: Optional[float] = None,
) -> TrackGeometry:
    """Create a TrackGeometry from track-builder parameters.

    Derives turn_radius from lap_length and straight_length using the
    same formula as the built-in tracks: radius = (L - 2*S) / (2*pi).
    Auto-generates standard 6-segment layout.
    """
    radius = (lap_length - 2.0 * straight_length_m) / (2.0 * np.pi)
    arc = np.pi * radius

    segments = [
        Segment("HomeStraight", "Home Straight", 0.0, straight_length_m, False),
        Segment("Turn1", "Turn 1", straight_length_m, straight_length_m + arc / 2, True),
        Segment("Turn2", "Turn 2", straight_length_m + arc / 2, straight_length_m + arc, True),
        Segment("BackStraight", "Back Straight", straight_length_m + arc, straight_length_m + arc + straight_length_m, False),
        Segment("Turn3", "Turn 3", straight_length_m + arc + straight_length_m, straight_length_m + arc + straight_length_m + arc / 2, True),
        Segment("Turn4", "Turn 4", straight_length_m + arc + straight_length_m + arc / 2, lap_length, True),
    ]

    return TrackGeometry(
        name=name,
        length_m=lap_length,
        straight_length_m=straight_length_m,
        turn_radius_m=radius,
        banking_straight_deg=banking_straight_deg,
        banking_turn_deg=banking_turn_deg,
        width_m=width_m,
        altitude_m=altitude_m,
        finish_line_dist_m=finish_line_dist_m,
        description=f"Custom track: {name}",
        segments=segments,
    )


def register_track(key: str, track: TrackGeometry):
    """Add a track to the available tracks registry."""
    AVAILABLE_TRACKS[key] = track


def scale_y_to_track_width(y: np.ndarray, track_width: float) -> np.ndarray:
    """Scale y_m values to fit within track width.

    Uses the same logic as track-builder.html resetTrajectoryToBromont():
    values at or below the red line (0.9m) stay unchanged, values above
    are scaled proportionally so the rail maps to track_width.

    Args:
        y: Array of lateral positions [m]
        track_width: Target track width [m]

    Returns:
        Scaled y array, clipped to [0, track_width]
    """
    y = y.copy()
    max_y = float(y.max())
    if max_y <= track_width:
        return y
    RED_LINE = 0.9
    src_above = max_y - RED_LINE
    dst_above = track_width - RED_LINE
    scale = dst_above / src_above if src_above > 0 else 1.0
    mask = y > RED_LINE
    y[mask] = RED_LINE + (y[mask] - RED_LINE) * scale
    return np.clip(y, 0.0, track_width)


# =============================================================================
# JSON Track Config Loading
# =============================================================================

# Trajectories loaded from JSON configs (key -> list of {s_m, y_m} dicts)
TRACK_TRAJECTORIES: Dict[str, list] = {}


def load_track_from_json(filepath: str) -> 'TrackGeometry':
    """Load a track from a JSON config file (as saved by track-builder).

    JSON format:
    {
      "name": "Colwood BC 333",
      "geometry": {
        "straight_m": 50, "banking_turn_deg": 20, "banking_straight_deg": 10,
        "width_m": 6.4, "lap_m": 333, "altitude_m": 0, "finish_line_dist_m": 50
      },
      "trajectory": [{"s_m": 0, "y_m": 2.5}, ...]
    }
    """
    import json as _json
    import os as _os
    with open(filepath) as f:
        data = _json.load(f)

    geom = data["geometry"]
    track = create_track_from_params(
        name=data.get("name", _os.path.basename(filepath)),
        lap_length=geom["lap_m"],
        straight_length_m=geom["straight_m"],
        banking_turn_deg=geom["banking_turn_deg"],
        banking_straight_deg=geom["banking_straight_deg"],
        width_m=geom.get("width_m", 7.0),
        altitude_m=geom.get("altitude_m", 0.0),
        finish_line_dist_m=geom.get("finish_line_dist_m"),
    )
    return track, data


def load_tracks_from_directory():
    """Scan tracks/ directory and register all JSON track configs."""
    import os as _os
    tracks_dir = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'tracks'
    )
    if not _os.path.isdir(tracks_dir):
        return

    for fname in sorted(_os.listdir(tracks_dir)):
        if not fname.endswith('.json'):
            continue
        filepath = _os.path.join(tracks_dir, fname)
        try:
            track, data = load_track_from_json(filepath)
            key = fname[:-5]  # Remove .json
            register_track(key, track)
            if "trajectory" in data:
                TRACK_TRAJECTORIES[key] = data["trajectory"]
        except Exception:
            pass  # Skip malformed files


# Auto-load on import
load_tracks_from_directory()


# =============================================================================
# Altitude Correction for Air Density
# =============================================================================

# Standard sea-level air density (kg/m³) at 15°C, 1013.25 hPa
RHO_SEA_LEVEL = 1.225

# Standard temperature lapse rate (K/m) in troposphere
TEMP_LAPSE_RATE = 0.0065

# Sea level standard temperature (K)
T0_KELVIN = 288.15

# Gravitational acceleration (m/s²)
G = 9.80665

# Molar mass of dry air (kg/mol)
M_AIR = 0.0289644

# Universal gas constant (J/(mol·K))
R_GAS = 8.31447


def rho_from_altitude(altitude_m: float, temperature_c: float = 15.0) -> float:
    """
    Calculate air density at a given altitude using the barometric formula.

    Uses the International Standard Atmosphere (ISA) model with optional
    temperature adjustment.

    Args:
        altitude_m: Altitude above sea level [m]
        temperature_c: Ambient temperature [°C] (default: 15°C standard)

    Returns:
        Air density rho [kg/m³]

    Examples:
        >>> rho_from_altitude(0)      # Sea level
        1.225
        >>> rho_from_altitude(200)    # Bromont
        1.201
        >>> rho_from_altitude(1020)   # Konya
        1.107

    Note:
        At Konya (1020m), rho is ~10% lower than sea level, giving a
        significant aerodynamic advantage for sprint events.
    """
    # Temperature at altitude (ISA model)
    T_altitude = T0_KELVIN - TEMP_LAPSE_RATE * altitude_m

    # Adjust for actual temperature vs standard
    temp_kelvin = temperature_c + 273.15
    T_ratio = temp_kelvin / (15.0 + 273.15)  # Ratio to standard temp

    # Barometric formula for density
    # ρ = ρ₀ × (T/T₀)^(1 + g×M/(R×L))
    exponent = 1.0 + (G * M_AIR) / (R_GAS * TEMP_LAPSE_RATE)
    rho = RHO_SEA_LEVEL * (T_altitude / T0_KELVIN) ** exponent

    # Adjust for actual temperature (ideal gas law: ρ ∝ 1/T)
    rho = rho / T_ratio

    return rho


def get_track_rho(track: TrackGeometry, temperature_c: float = 15.0) -> float:
    """
    Get the standard air density for a track based on its altitude.

    Args:
        track: Track geometry with altitude
        temperature_c: Ambient temperature [°C] (default: 15°C)

    Returns:
        Air density rho [kg/m³]
    """
    return rho_from_altitude(track.altitude_m, temperature_c)


# Pre-calculated standard rho values for quick reference
TRACK_RHO_STANDARD: Dict[str, float] = {
    "Bromont": rho_from_altitude(200.0),   # ~1.201 kg/m³
    "Milton": rho_from_altitude(176.0),    # ~1.204 kg/m³
    "Konya": rho_from_altitude(1020.0),    # ~1.107 kg/m³
}


# =============================================================================
# Comprehensive Air Density from Environmental Conditions
# =============================================================================

# Specific gas constants
R_DRY_AIR = 287.058      # J/(kg·K) - specific gas constant for dry air
R_WATER_VAPOR = 461.495  # J/(kg·K) - specific gas constant for water vapor


def saturation_vapor_pressure(temperature_c: float) -> float:
    """
    Calculate saturation vapor pressure using Magnus-Tetens formula.

    Args:
        temperature_c: Temperature in Celsius

    Returns:
        Saturation vapor pressure in Pa
    """
    # Magnus-Tetens coefficients
    a = 17.27
    b = 237.7  # °C

    # Calculate saturation vapor pressure in hPa, convert to Pa
    e_s_hpa = 6.1078 * np.exp((a * temperature_c) / (temperature_c + b))
    return e_s_hpa * 100  # Convert hPa to Pa


def rho_from_conditions(
    temperature_c: float,
    relative_humidity_pct: float,
    pressure_hpa: float,
) -> float:
    """
    Calculate air density from temperature, humidity, and pressure.

    Uses the ideal gas law with humidity correction for accurate air density.

    Args:
        temperature_c: Ambient temperature [°C]
        relative_humidity_pct: Relative humidity [%] (0-100)
        pressure_hpa: Barometric pressure [hPa] (millibars)

    Returns:
        Air density rho [kg/m³]

    Examples:
        >>> rho_from_conditions(20, 50, 1013.25)  # Sea level, 20°C, 50% RH
        1.199
        >>> rho_from_conditions(25, 60, 900)      # Higher altitude, warm, humid
        1.044

    Note:
        Higher humidity actually DECREASES air density (water vapor is lighter
        than dry air). This effect is small but measurable for precision work.
    """
    # Convert units
    T_kelvin = temperature_c + 273.15
    P_total = pressure_hpa * 100  # hPa to Pa
    RH = relative_humidity_pct / 100.0  # percentage to fraction

    # Calculate saturation vapor pressure
    e_sat = saturation_vapor_pressure(temperature_c)

    # Actual vapor pressure
    e_vapor = RH * e_sat

    # Partial pressure of dry air
    p_dry = P_total - e_vapor

    # Air density using ideal gas law with humidity correction
    # ρ = (p_dry / (R_dry * T)) + (e_vapor / (R_vapor * T))
    rho = (p_dry / (R_DRY_AIR * T_kelvin)) + (e_vapor / (R_WATER_VAPOR * T_kelvin))

    return rho


def estimate_pressure_at_altitude(
    sea_level_pressure_hpa: float,
    altitude_m: float,
    temperature_c: float = 15.0,
) -> float:
    """
    Estimate barometric pressure at altitude from sea level pressure.

    Uses the barometric formula to estimate pressure at elevation.

    Args:
        sea_level_pressure_hpa: Sea level pressure [hPa]
        altitude_m: Altitude above sea level [m]
        temperature_c: Temperature at altitude [°C]

    Returns:
        Estimated pressure at altitude [hPa]

    Note:
        For best accuracy, use actual measured pressure at the track.
        This is an approximation useful when only sea level pressure is known.
    """
    T_kelvin = temperature_c + 273.15

    # Barometric formula: P = P0 * exp(-g*M*h / (R*T))
    exponent = -(G * M_AIR * altitude_m) / (R_GAS * T_kelvin)
    pressure = sea_level_pressure_hpa * np.exp(exponent)

    return pressure


def get_standard_pressure_at_altitude(altitude_m: float) -> float:
    """
    Get standard atmospheric pressure at a given altitude.

    Args:
        altitude_m: Altitude above sea level [m]

    Returns:
        Standard pressure [hPa]
    """
    return estimate_pressure_at_altitude(1013.25, altitude_m)


# Standard pressure values for tracks
TRACK_PRESSURE_STANDARD: Dict[str, float] = {
    "Bromont": get_standard_pressure_at_altitude(200.0),   # ~989 hPa
    "Milton": get_standard_pressure_at_altitude(176.0),    # ~992 hPa
    "Konya": get_standard_pressure_at_altitude(1020.0),    # ~897 hPa
}


def get_track_summary(track: TrackGeometry) -> str:
    """Get a summary string for a track including key geometry differences."""
    rho = rho_from_altitude(track.altitude_m)
    return (
        f"{track.name}\n"
        f"  Straights: {track.straight_length_m:.0f}m | Turn radius: {track.turn_radius_m:.1f}m | Width: {track.width_m:.0f}m\n"
        f"  Banking: {track.banking_straight_deg:.1f}° (straights) / {track.banking_turn_deg:.1f}° (turns)\n"
        f"  Altitude: {track.altitude_m:.0f}m → ρ = {rho:.4f} kg/m³\n"
        f"  {track.description}"
    )


# =============================================================================
# Named Segment Functions (Address "695m means nothing" pain point)
# =============================================================================

def get_segment_name(
    s_effort: float,
    track: TrackGeometry = None,
    s_offset: float = None,
    include_lap: bool = True,
    include_distance_into: bool = False,
) -> str:
    """
    Convert a raw distance into a human-readable segment name.

    This is the KEY FUNCTION that addresses the user's pain point:
    "695m is hard to conceptualize - need lap + segment descriptors"

    Args:
        s_effort: Distance along the effort (0 = back straight pursuit line)
        track: Track geometry (defaults to Bromont)
        s_offset: Offset from effort start to track reference (auto-calculated if None)
        include_lap: Include lap number in output
        include_distance_into: Include "Xm into" qualifier

    Returns:
        Human-readable segment description, e.g., "Lap 2, Turn 1"

    Examples:
        >>> get_segment_name(695.0)
        "Lap 3, Home Straight"
        >>> get_segment_name(695.0, include_distance_into=True)
        "Lap 3, Home Straight (5m in)"
    """
    if track is None:
        track = DEFAULT_TRACK

    # Calculate offset if not provided (s=0 at mid back-straight for Flying 200)
    if s_offset is None:
        # Standard offset: s=0 is at pursuit line (mid back straight)
        # To convert to track coordinates (s=0 at finish line/home straight start):
        straight = track.straight_length_m
        arc = track.arc_length_m
        s_offset = straight + arc + 0.5 * straight  # home + bend1 + half back

    # Convert effort distance to global track distance
    s_global = s_effort + s_offset

    # Calculate lap and position within lap
    lap_idx = int(s_global // track.length_m)
    s_in_lap = s_global % track.length_m

    # Get segment
    segment = track.get_segment_at_lap_distance(s_in_lap)

    # Calculate distance into segment
    dist_into = s_in_lap - segment.start_m

    # Build output string
    if include_lap:
        result = f"Lap {lap_idx}, {segment.display_name}"
    else:
        result = segment.display_name

    if include_distance_into:
        result += f" ({dist_into:.0f}m in)"

    return result


def get_segment_at_distance(
    s_effort: float,
    track: TrackGeometry = None,
) -> Tuple[int, Segment, float]:
    """
    Get segment information at a given effort distance.

    Args:
        s_effort: Distance along the effort
        track: Track geometry (defaults to Bromont)

    Returns:
        Tuple of (lap_index, Segment, distance_into_segment)
    """
    if track is None:
        track = DEFAULT_TRACK

    # Standard offset calculation
    straight = track.straight_length_m
    arc = track.arc_length_m
    s_offset = straight + arc + 0.5 * straight

    s_global = s_effort + s_offset
    lap_idx = int(s_global // track.length_m)
    s_in_lap = s_global % track.length_m

    segment = track.get_segment_at_lap_distance(s_in_lap)
    dist_into = s_in_lap - segment.start_m

    return lap_idx, segment, dist_into


def format_segment_label(
    lap_idx: int,
    section_name: str,
    short: bool = False,
) -> str:
    """
    Format a segment label for chart display.

    Args:
        lap_idx: Lap number (0-indexed)
        section_name: Section name (e.g., "HomeStraight", "Turn1")
        short: Use abbreviated format for compact display

    Returns:
        Formatted label string
    """
    # Map internal names to display names
    display_names = {
        "HomeStraight": ("Home Straight", "HS"),
        "BackStraight": ("Back Straight", "BS"),
        "Turn1": ("Turn 1", "T1"),
        "Turn2": ("Turn 2", "T2"),
        "Turn3": ("Turn 3", "T3"),
        "Turn4": ("Turn 4", "T4"),
    }

    full_name, abbrev = display_names.get(section_name, (section_name, section_name[:2]))

    if short:
        return f"L{lap_idx}-{abbrev}"
    else:
        return f"Lap {lap_idx}, {full_name}"


# =============================================================================
# Segment Color Mapping (for visualization)
# =============================================================================

SEGMENT_COLORS = {
    "HomeStraight": "#E3F2FD",   # Light blue
    "BackStraight": "#E8F5E9",   # Light green
    "Turn1": "#FCE4EC",          # Light pink
    "Turn2": "#FCE4EC",          # Light pink
    "Turn3": "#FFF3E0",          # Light orange
    "Turn4": "#FFF3E0",          # Light orange
}


def get_segment_color(section_name: str) -> str:
    """Get the color for a segment (for chart shading)."""
    return SEGMENT_COLORS.get(section_name, "#EEEEEE")


# =============================================================================
# Key Distance Markers for Flying 200
# =============================================================================

# These are the critical distances in a Flying 200 effort
# s=0 is at the pursuit line (mid back straight)

FLYING_200_MARKERS = {
    "effort_start": 0.0,           # Back straight pursuit line
    "200m_start": 695.0,           # Start of timed 200m
    "200m_finish": 895.0,          # Finish line
}


def describe_flying_200_position(s_effort: float, track: TrackGeometry = None) -> str:
    """
    Describe a position in the Flying 200 effort.

    Args:
        s_effort: Distance from effort start

    Returns:
        Human-readable description

    Examples:
        >>> describe_flying_200_position(695.0)
        "200m Start (Lap 3, Home Straight)"
        >>> describe_flying_200_position(750.0)
        "55m into timed 200 (Lap 3, Turn 1)"
    """
    segment_name = get_segment_name(s_effort, track)

    if s_effort < 695.0:
        # Before timed 200
        dist_to_200 = 695.0 - s_effort
        return f"{dist_to_200:.0f}m before 200m start ({segment_name})"
    elif s_effort == 695.0:
        return f"200m Start ({segment_name})"
    elif s_effort < 895.0:
        # Within timed 200
        dist_into_200 = s_effort - 695.0
        return f"{dist_into_200:.0f}m into timed 200 ({segment_name})"
    elif s_effort == 895.0:
        return f"Finish Line ({segment_name})"
    else:
        # Past finish (shouldn't happen normally)
        return f"{s_effort - 895.0:.0f}m past finish ({segment_name})"
