# Flying 200 V2 - FIT Analysis Module
# Parse FIT files, auto-detect efforts, convert to distance-based profiles

from .parser import parse_fit_file, FitRecord, FitFileData, extract_power_curve
from .detector import detect_flying_efforts, DetectedEffort, quick_sim_preview
from .converter import (
    convert_time_to_distance,
    GearConfig,
    DistanceProfile,
    align_to_finish_line,
    extract_effort_profile,
    GEAR_55_14,
    GEAR_54_14,
    GEAR_55_15,
)

__all__ = [
    'parse_fit_file',
    'FitRecord',
    'FitFileData',
    'extract_power_curve',
    'detect_flying_efforts',
    'DetectedEffort',
    'quick_sim_preview',
    'convert_time_to_distance',
    'GearConfig',
    'DistanceProfile',
    'align_to_finish_line',
    'extract_effort_profile',
    'GEAR_55_14',
    'GEAR_54_14',
    'GEAR_55_15',
]
