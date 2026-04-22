"""
Power-Cadence Constraint Module

Collect, analyze, and interpolate power-cadence constraint data
across different gear ratios for use in optimization algorithms.

Usage:
    # GUI (recommended)
    python -m constraints.gui
    # Or: run_constraints_gui.bat

    # CLI
    python -m constraints collect calendar.json --fit-dir ./fits
    python -m constraints analyze ./data
    python -m constraints interpolate ./data --chainring 55 --cog 14

    # Python API
    from constraints import (
        GearCalendar,
        DataLoader,
        SprintPhaseExtractor,
        CadenceBinAnalyzer,
        GearRatioInterpolator,
        ConstraintDataStore,
    )

    # Load gear calendar
    calendar = GearCalendar.from_json("calendar.json")

    # Collect data
    loader = DataLoader(fit_directory="./fits")
    extractor = SprintPhaseExtractor()

    for entry in calendar.entries:
        records = loader.load_records_for_entry(entry)
        efforts, _ = extractor.process_activity(records, entry.gear, entry.date)
        # ... collect observations

    # Compute statistics
    analyzer = CadenceBinAnalyzer()
    data_set = analyzer.build_all_profiles(observations)

    # Interpolate to new gear
    interpolator = GearRatioInterpolator(data_set.profiles)
    new_profile = interpolator.generate_profile_for_gear(55, 14)
"""

# Models
from .models import (
    GearConfig,
    EffortGearAssignment,
    GearCalendarEntry,
    GearCalendar,
    PowerCadenceObservation,
    EffortObservations,
    CadenceBinStats,
    GearConstraintProfile,
    ConstraintDataSet,
)

# Gear Inference
from .gear_inference import (
    GearInferenceEngine,
    InferredGear,
    GearValidationResult,
    generate_validation_report,
    suggest_gear_assignments,
    create_calendar_from_inference,
)

# Data Sources
from .data_sources import (
    FitFileSource,
    StravaDataSource,
    DataLoader,
)

# Effort Extraction
from .effort_extractor import (
    SprintPhaseExtractor,
    get_observations_summary,
    filter_observations_by_gear,
    filter_observations_by_cadence_range,
)

# Statistical Analysis
from .statistical_analysis import (
    CadenceBinAnalyzer,
    calculate_torque,
    calculate_power_from_torque,
    analyze_torque_cadence_relationship,
    get_power_at_cadence_summary,
    find_optimal_cadence,
)

# Interpolation
from .interpolation import (
    GearRatioInterpolator,
    DevelopmentInterpolator,
    validate_interpolation,
)

# Persistence
from .persistence import (
    ConstraintDataStore,
    merge_data_stores,
    create_backup,
)

# CSV Converter
from .csv_converter import (
    convert_tsv_to_calendar_json,
    convert_inline_data,
    print_calendar_summary,
)

__all__ = [
    # Models
    'GearConfig',
    'EffortGearAssignment',
    'GearCalendarEntry',
    'GearCalendar',
    'PowerCadenceObservation',
    'EffortObservations',
    'CadenceBinStats',
    'GearConstraintProfile',
    'ConstraintDataSet',
    # Gear Inference
    'GearInferenceEngine',
    'InferredGear',
    'GearValidationResult',
    'generate_validation_report',
    'suggest_gear_assignments',
    'create_calendar_from_inference',
    # Data Sources
    'FitFileSource',
    'StravaDataSource',
    'DataLoader',
    # Effort Extraction
    'SprintPhaseExtractor',
    'get_observations_summary',
    'filter_observations_by_gear',
    'filter_observations_by_cadence_range',
    # Statistical Analysis
    'CadenceBinAnalyzer',
    'calculate_torque',
    'calculate_power_from_torque',
    'analyze_torque_cadence_relationship',
    'get_power_at_cadence_summary',
    'find_optimal_cadence',
    # Interpolation
    'GearRatioInterpolator',
    'DevelopmentInterpolator',
    'validate_interpolation',
    # Persistence
    'ConstraintDataStore',
    'merge_data_stores',
    'create_backup',
    # CSV Converter
    'convert_tsv_to_calendar_json',
    'convert_inline_data',
    'print_calendar_summary',
]

__version__ = '0.1.0'
