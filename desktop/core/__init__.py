# Flying 200 V2 - Core Module
# Physics engine, track geometry, and session management

from .physics import simulate_profile, SimulationResult, SimulationConfig
from .track import BROMONT_250M, MILTON_250M, AVAILABLE_TRACKS, get_segment_name
from .session import Session
from .config import (
    load_config,
    save_config,
    get_default_positions,
    get_default_y_profile,
    interpolate_y_to_grid,
    get_config_summary,
)

__all__ = [
    'simulate_profile',
    'SimulationResult',
    'SimulationConfig',
    'BROMONT_250M',
    'MILTON_250M',
    'AVAILABLE_TRACKS',
    'get_segment_name',
    'Session',
    'load_config',
    'save_config',
    'get_default_positions',
    'get_default_y_profile',
    'interpolate_y_to_grid',
    'get_config_summary',
]
