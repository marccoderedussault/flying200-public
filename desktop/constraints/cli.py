"""
Command Line Interface for Power-Cadence Constraint Collection

Usage:
    python -m constraints collect calendar.json --fit-dir ./fits --output ./data
    python -m constraints analyze ./data --output statistics.csv
    python -m constraints interpolate ./data --chainring 55 --cog 14
    python -m constraints summary ./data
"""

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional

try:
    from .models import GearCalendar, GearCalendarEntry, ConstraintDataSet
    from .data_sources import DataLoader, FitFileSource
    from .effort_extractor import SprintPhaseExtractor, get_observations_summary
    from .statistical_analysis import CadenceBinAnalyzer
    from .interpolation import GearRatioInterpolator, validate_interpolation
    from .persistence import ConstraintDataStore
except ImportError:
    from models import GearCalendar, GearCalendarEntry, ConstraintDataSet
    from data_sources import DataLoader, FitFileSource
    from effort_extractor import SprintPhaseExtractor, get_observations_summary
    from statistical_analysis import CadenceBinAnalyzer
    from interpolation import GearRatioInterpolator, validate_interpolation
    from persistence import ConstraintDataStore


def collect_command(args: argparse.Namespace) -> int:
    """
    Collect power-cadence data from activities.

    Reads gear calendar, loads activity data, detects efforts,
    extracts observations, and saves to data store.
    """
    print("=" * 60)
    print("Power-Cadence Constraint Data Collection")
    print("=" * 60)

    # Load gear calendar
    print(f"\nLoading gear calendar from: {args.calendar}")
    calendar = GearCalendar.from_json(args.calendar)
    print(f"  Found {len(calendar.entries)} entries")
    print(f"  Gear ratios: {', '.join(calendar.get_unique_gears())}")

    # Initialize data loader
    loader = DataLoader(
        fit_directory=args.fit_dir,
        strava_token=args.strava_token,
    )

    # Initialize extractor
    extractor = SprintPhaseExtractor(
        min_power_threshold=args.min_power,
        min_cadence=args.min_cadence,
        max_cadence=args.max_cadence,
        include_ramp=args.include_ramp,
        sensitivity=args.sensitivity,
    )

    # Initialize data store
    store = ConstraintDataStore(args.output)

    # Process each entry
    print(f"\nProcessing {len(calendar.entries)} activities...")
    print("-" * 60)

    all_observations = []
    success_count = 0
    fail_count = 0

    for i, entry in enumerate(calendar.entries, 1):
        print(f"[{i}/{len(calendar.entries)}] {entry.date} ({entry.gear.gear_ratio_str})...", end=" ")

        try:
            # Load activity data
            records = loader.load_records_for_entry(entry)
            if not records:
                print("No data found")
                fail_count += 1
                continue

            # Detect and extract efforts
            effort_obs_list, detected_efforts = extractor.process_activity(
                records,
                entry.gear,
                entry.date,
                entry.effort_type,
            )

            if not detected_efforts:
                print("No efforts detected")
                fail_count += 1
                continue

            # Collect observations
            for effort_obs in effort_obs_list:
                all_observations.extend(effort_obs.observations)

            n_obs = sum(len(e.observations) for e in effort_obs_list)
            print(f"{len(detected_efforts)} effort(s), {n_obs} observations")
            success_count += 1

        except Exception as e:
            print(f"Error: {e}")
            fail_count += 1
            if args.verbose:
                import traceback
                traceback.print_exc()

    print("-" * 60)
    print(f"\nCollection complete:")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {fail_count}")
    print(f"  Total observations: {len(all_observations)}")

    if not all_observations:
        print("\nNo observations collected. Exiting.")
        return 1

    # Save observations
    new_count = store.save_observations(all_observations, append=True)
    print(f"\nSaved {new_count} new observations to {args.output}")

    # Compute and save statistics
    if args.analyze:
        print("\nComputing statistics...")
        analyzer = CadenceBinAnalyzer(
            bin_size=args.bin_size,
            min_samples=args.min_samples,
        )
        data_set = analyzer.build_all_profiles(store.load_observations())
        store.save_statistics(data_set)

        # Export CSV
        csv_path = store.export_statistics_csv()
        print(f"Statistics saved to: {csv_path}")

    # Save metadata
    store.save_metadata({
        'calendar_file': str(args.calendar),
        'fit_directory': str(args.fit_dir) if args.fit_dir else None,
        'collection_date': date.today().isoformat(),
        'n_entries_processed': success_count,
    })

    # Print summary
    print("\n" + "=" * 60)
    summary = get_observations_summary(all_observations)
    print(f"Summary:")
    print(f"  Gear ratios: {', '.join(summary['gear_ratios'])}")
    print(f"  Power range: {summary['power_range'][0]:.0f} - {summary['power_range'][1]:.0f} W")
    print(f"  Cadence range: {summary['cadence_range'][0]:.0f} - {summary['cadence_range'][1]:.0f} RPM")
    print(f"  Unique efforts: {summary['n_efforts']}")

    return 0


def analyze_command(args: argparse.Namespace) -> int:
    """
    Recompute statistics from collected observations.
    """
    print("=" * 60)
    print("Power-Cadence Constraint Analysis")
    print("=" * 60)

    # Load data store
    store = ConstraintDataStore(args.data_dir)
    observations = store.load_observations()

    if not observations:
        print("No observations found in data store.")
        return 1

    print(f"\nLoaded {len(observations)} observations")
    print(f"Gear ratios: {', '.join(store.get_unique_gears())}")

    # Compute statistics
    print("\nComputing statistics...")
    analyzer = CadenceBinAnalyzer(
        bin_size=args.bin_size,
        min_samples=args.min_samples,
    )
    data_set = analyzer.build_all_profiles(observations)

    # Save
    store.save_statistics(data_set)
    print(f"Statistics saved to: {store.statistics_path}")

    # Export CSV
    csv_path = store.export_statistics_csv(args.output)
    print(f"CSV exported to: {csv_path}")

    # Print summary per gear
    print("\n" + "=" * 60)
    print("Statistics Summary")
    print("=" * 60)

    for gear_str, profile in sorted(data_set.profiles.items()):
        print(f"\n{gear_str}:")
        print(f"  Observations: {profile.n_total_observations}")
        print(f"  Efforts: {profile.n_efforts}")
        print(f"  Cadence bins: {len(profile.bins)}")
        if profile.bins:
            cad_range = profile.cadence_range
            print(f"  Cadence range: {cad_range[0]}-{cad_range[1]} RPM")

            # Find peak power cadence
            best_bin = max(profile.bins, key=lambda b: b.p95_power_W)
            print(f"  Peak P95 power: {best_bin.p95_power_W:.0f} W @ {best_bin.cadence_range} RPM")

    return 0


def interpolate_command(args: argparse.Namespace) -> int:
    """
    Generate constraint profile for an unmeasured gear ratio.
    """
    print("=" * 60)
    print("Power-Cadence Constraint Interpolation")
    print("=" * 60)

    # Load statistics
    store = ConstraintDataStore(args.data_dir)
    data_set = store.load_statistics()

    if not data_set or not data_set.profiles:
        print("No statistics found. Run analyze first.")
        return 1

    print(f"\nMeasured gear ratios: {', '.join(data_set.get_available_gears())}")

    target_gear = f"{args.chainring}/{args.cog}"
    print(f"Target gear: {target_gear}")

    # Check if already measured
    if target_gear in data_set.profiles:
        print(f"\nNote: {target_gear} is already measured. Interpolation not needed.")
        profile = data_set.profiles[target_gear]
    else:
        # Build interpolator
        print("\nBuilding torque-cadence model...")
        interpolator = GearRatioInterpolator(data_set.profiles)

        # Print model summary
        model_info = interpolator.get_torque_model_summary()
        print(f"  Using data from {model_info['n_gears']} gears")
        print(f"  Cadence range: {model_info['cadence_range'][0]}-{model_info['cadence_range'][1]} RPM")

        # Generate profile
        print(f"\nGenerating profile for {target_gear}...")
        profile = interpolator.generate_profile_for_gear(
            args.chainring,
            args.cog,
        )

        # Add to data set and save
        data_set.add_profile(profile)
        store.save_statistics(data_set)
        print(f"Profile saved to statistics file")

    # Print profile
    print("\n" + "-" * 60)
    print(f"Constraint Profile for {target_gear}")
    print("-" * 60)
    print(f"{'Cadence':<12} {'P95 (W)':<10} {'Max (W)':<10} {'Mean (W)':<10} {'Torque (Nm)':<12}")
    print("-" * 60)

    for bin_stats in profile.bins:
        interp_flag = "*" if bin_stats.is_interpolated else ""
        print(f"{bin_stats.cadence_range:<12} {bin_stats.p95_power_W:<10.0f} "
              f"{bin_stats.max_power_W:<10.0f} {bin_stats.mean_power_W:<10.0f} "
              f"{bin_stats.max_torque_Nm:<12.1f}{interp_flag}")

    if profile.is_interpolated:
        print("\n* = interpolated values")

    # Export updated CSV
    csv_path = store.export_statistics_csv()
    print(f"\nUpdated CSV exported to: {csv_path}")

    return 0


def summary_command(args: argparse.Namespace) -> int:
    """
    Show summary of collected data.
    """
    store = ConstraintDataStore(args.data_dir)
    summary = store.get_summary()

    print("=" * 60)
    print("Power-Cadence Constraint Data Summary")
    print("=" * 60)

    print(f"\nData directory: {args.data_dir}")
    print(f"Observations: {summary.get('n_observations', 0)}")
    print(f"Unique efforts: {summary.get('n_efforts', 0)}")
    print(f"Unique dates: {summary.get('n_dates', 0)}")
    print(f"Gear ratios: {', '.join(summary.get('gear_ratios', []))}")

    if 'date_range' in summary:
        print(f"Date range: {summary['date_range'][0]} to {summary['date_range'][1]}")

    if 'last_updated' in summary:
        print(f"Last updated: {summary['last_updated']}")

    # Show profile details if available
    data_set = store.load_statistics()
    if data_set and data_set.profiles:
        print("\n" + "-" * 60)
        print("Profiles:")
        for gear_str, profile in sorted(data_set.profiles.items()):
            interp = " (interpolated)" if profile.is_interpolated else ""
            print(f"  {gear_str}: {profile.n_total_observations} obs, "
                  f"{len(profile.bins)} bins{interp}")

    return 0


def validate_command(args: argparse.Namespace) -> int:
    """
    Validate interpolation accuracy using cross-validation.
    """
    print("=" * 60)
    print("Interpolation Validation (Leave-One-Out)")
    print("=" * 60)

    store = ConstraintDataStore(args.data_dir)
    data_set = store.load_statistics()

    if not data_set or len(data_set.profiles) < 2:
        print("Need at least 2 measured gears for validation.")
        return 1

    print(f"\nValidating with {len(data_set.profiles)} measured gears...")

    # Build interpolator with all data
    interpolator = GearRatioInterpolator(data_set.profiles)

    # Run validation
    results = validate_interpolation(
        interpolator,
        data_set.profiles,
        verbose=args.verbose,
    )

    print("\n" + "-" * 60)
    print("Validation Results:")
    print(f"  Comparisons: {results['n_comparisons']}")
    print(f"  Mean relative error: {results['mean_error']*100:.1f}%")
    print(f"  Std error: {results.get('std_error', 0)*100:.1f}%")
    print(f"  Max error: {results['max_error']*100:.1f}%")

    if results['mean_error'] < 0.05:
        print("\n  Interpolation accuracy: GOOD (<5% mean error)")
    elif results['mean_error'] < 0.10:
        print("\n  Interpolation accuracy: ACCEPTABLE (5-10% mean error)")
    else:
        print("\n  Interpolation accuracy: POOR (>10% mean error)")
        print("  Consider collecting more data at different gears.")

    return 0


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Power-Cadence Constraint Collection Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Collect command
    collect_parser = subparsers.add_parser(
        'collect',
        help='Collect power-cadence data from activities'
    )
    collect_parser.add_argument(
        'calendar',
        help='JSON file mapping dates to gear ratios'
    )
    collect_parser.add_argument(
        '--fit-dir',
        help='Directory containing FIT files'
    )
    collect_parser.add_argument(
        '--strava-token',
        help='Strava API access token'
    )
    collect_parser.add_argument(
        '--output', '-o',
        default='./constraint_data',
        help='Output directory for data (default: ./constraint_data)'
    )
    collect_parser.add_argument(
        '--min-power',
        type=float,
        default=600.0,
        help='Minimum power threshold (default: 600W)'
    )
    collect_parser.add_argument(
        '--min-cadence',
        type=float,
        default=50.0,
        help='Minimum cadence (default: 50 RPM)'
    )
    collect_parser.add_argument(
        '--max-cadence',
        type=float,
        default=180.0,
        help='Maximum cadence (default: 180 RPM)'
    )
    collect_parser.add_argument(
        '--bin-size',
        type=int,
        default=5,
        help='Cadence bin size (default: 5 RPM)'
    )
    collect_parser.add_argument(
        '--min-samples',
        type=int,
        default=3,
        help='Minimum samples per bin (default: 3)'
    )
    collect_parser.add_argument(
        '--sensitivity',
        choices=['low', 'medium', 'high'],
        default='medium',
        help='Detection sensitivity (default: medium)'
    )
    collect_parser.add_argument(
        '--include-ramp',
        action='store_true',
        help='Include ramp phase data (not just sprint)'
    )
    collect_parser.add_argument(
        '--analyze',
        action='store_true',
        default=True,
        help='Compute statistics after collection (default: True)'
    )
    collect_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )

    # Analyze command
    analyze_parser = subparsers.add_parser(
        'analyze',
        help='Recompute statistics from collected data'
    )
    analyze_parser.add_argument(
        'data_dir',
        help='Data directory with observations'
    )
    analyze_parser.add_argument(
        '--output', '-o',
        help='Output CSV file path'
    )
    analyze_parser.add_argument(
        '--bin-size',
        type=int,
        default=5,
        help='Cadence bin size (default: 5 RPM)'
    )
    analyze_parser.add_argument(
        '--min-samples',
        type=int,
        default=3,
        help='Minimum samples per bin (default: 3)'
    )

    # Interpolate command
    interp_parser = subparsers.add_parser(
        'interpolate',
        help='Generate profile for unmeasured gear'
    )
    interp_parser.add_argument(
        'data_dir',
        help='Data directory with statistics'
    )
    interp_parser.add_argument(
        '--chainring',
        type=int,
        required=True,
        help='Chainring teeth (e.g., 55)'
    )
    interp_parser.add_argument(
        '--cog',
        type=int,
        required=True,
        help='Cog teeth (e.g., 14)'
    )

    # Summary command
    summary_parser = subparsers.add_parser(
        'summary',
        help='Show data summary'
    )
    summary_parser.add_argument(
        'data_dir',
        help='Data directory'
    )

    # Validate command
    validate_parser = subparsers.add_parser(
        'validate',
        help='Validate interpolation accuracy'
    )
    validate_parser.add_argument(
        'data_dir',
        help='Data directory with statistics'
    )
    validate_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed comparison results'
    )

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Dispatch to command handler
    commands = {
        'collect': collect_command,
        'analyze': analyze_command,
        'interpolate': interpolate_command,
        'summary': summary_command,
        'validate': validate_command,
    }

    return commands[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
