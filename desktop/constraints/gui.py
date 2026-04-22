"""
Power-Cadence Constraint Collection GUI

A Tkinter-based GUI for collecting, analyzing, and interpolating
power-cadence constraint data.
"""

import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Dict

# Handle imports for both direct and package execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

try:
    # Try relative imports first (when run as module)
    from .models import GearCalendar, GearConfig, ConstraintDataSet, STANDARD_DURATIONS
    from .data_sources import DataLoader, FitFileSource
    from .effort_extractor import SprintPhaseExtractor, get_observations_summary
    from .statistical_analysis import CadenceBinAnalyzer
    from .interpolation import GearRatioInterpolator, validate_interpolation
    from .persistence import ConstraintDataStore
    from .gear_inference import GearInferenceEngine, generate_validation_report
except ImportError:
    # Fall back to absolute imports (when run directly)
    from models import GearCalendar, GearConfig, ConstraintDataSet, STANDARD_DURATIONS
    from data_sources import DataLoader, FitFileSource
    from effort_extractor import SprintPhaseExtractor, get_observations_summary
    from statistical_analysis import CadenceBinAnalyzer
    from interpolation import GearRatioInterpolator, validate_interpolation
    from persistence import ConstraintDataStore
    from gear_inference import GearInferenceEngine, generate_validation_report


class ConstraintsGUI:
    """
    Main GUI for Power-Cadence Constraint Collection.

    Features:
    - Load gear calendar JSON
    - Set FIT files directory
    - Run data collection
    - Validate gear assignments
    - Analyze and compute statistics
    - Interpolate to new gears
    - View results
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Power-Cadence Constraint Collection")
        self.root.geometry("1200x800")

        # Try to maximize
        try:
            self.root.state('zoomed')
        except tk.TclError:
            pass

        # State
        self.calendar: Optional[GearCalendar] = None
        self.store: Optional[ConstraintDataStore] = None
        self.data_set: Optional[ConstraintDataSet] = None

        # Variables (with sensible defaults)
        self.calendar_path = tk.StringVar(value="C:/Projects/velodrome/flying200-package-v2/constraints/gear_calendar_data.json")
        self.fit_dir_path = tk.StringVar(value="C:/Projects/velodrome/cadence")
        self.output_dir_path = tk.StringVar(value="./constraint_data")
        self.strava_token = tk.StringVar()

        # Settings
        self.min_power = tk.IntVar(value=600)
        self.min_cadence = tk.IntVar(value=50)
        self.max_cadence = tk.IntVar(value=180)
        self.bin_size = tk.IntVar(value=5)

        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build the main UI."""
        # Main container with left panel and right results
        main_paned = ttk.PanedWindow(self.root, orient="horizontal")
        main_paned.pack(fill="both", expand=True, padx=5, pady=5)

        # Left panel: Controls
        left_frame = ttk.Frame(main_paned, width=400)
        main_paned.add(left_frame, weight=1)

        # Right panel: Results
        right_frame = ttk.Frame(main_paned, width=800)
        main_paned.add(right_frame, weight=3)

        self._build_controls(left_frame)
        self._build_results(right_frame)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill="x", side="bottom")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side="left", padx=10)

        self.progress = ttk.Progressbar(status_frame, mode='indeterminate', length=200)
        self.progress.pack(side="right", padx=10)

    def _build_controls(self, parent):
        """Build the left control panel."""
        # Make scrollable
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # === Section 1: File Paths ===
        paths_frame = ttk.LabelFrame(scrollable_frame, text="Data Sources", padding=10)
        paths_frame.pack(fill="x", padx=5, pady=5)

        # Calendar file
        ttk.Label(paths_frame, text="Gear Calendar JSON:").pack(anchor="w")
        cal_frame = ttk.Frame(paths_frame)
        cal_frame.pack(fill="x", pady=2)
        ttk.Entry(cal_frame, textvariable=self.calendar_path, width=40).pack(side="left", fill="x", expand=True)
        ttk.Button(cal_frame, text="Browse", command=self._browse_calendar).pack(side="left", padx=5)
        ttk.Button(cal_frame, text="Load", command=self._load_calendar).pack(side="left")

        # FIT directory
        ttk.Label(paths_frame, text="FIT Files Directory:").pack(anchor="w", pady=(10, 0))
        fit_frame = ttk.Frame(paths_frame)
        fit_frame.pack(fill="x", pady=2)
        ttk.Entry(fit_frame, textvariable=self.fit_dir_path, width=40).pack(side="left", fill="x", expand=True)
        ttk.Button(fit_frame, text="Browse", command=self._browse_fit_dir).pack(side="left", padx=5)

        # Output directory
        ttk.Label(paths_frame, text="Output Directory:").pack(anchor="w", pady=(10, 0))
        out_frame = ttk.Frame(paths_frame)
        out_frame.pack(fill="x", pady=2)
        ttk.Entry(out_frame, textvariable=self.output_dir_path, width=40).pack(side="left", fill="x", expand=True)
        ttk.Button(out_frame, text="Browse", command=self._browse_output_dir).pack(side="left", padx=5)

        # Strava token (optional)
        ttk.Label(paths_frame, text="Strava Token (optional):").pack(anchor="w", pady=(10, 0))
        ttk.Entry(paths_frame, textvariable=self.strava_token, width=50, show="*").pack(fill="x", pady=2)

        # === Section 2: Settings ===
        settings_frame = ttk.LabelFrame(scrollable_frame, text="Settings", padding=10)
        settings_frame.pack(fill="x", padx=5, pady=5)

        settings_grid = ttk.Frame(settings_frame)
        settings_grid.pack(fill="x")

        ttk.Label(settings_grid, text="Min Power (W):").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Spinbox(settings_grid, from_=0, to=1000, textvariable=self.min_power, width=8).grid(row=0, column=1, padx=5)

        ttk.Label(settings_grid, text="Min Cadence (RPM):").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Spinbox(settings_grid, from_=0, to=100, textvariable=self.min_cadence, width=8).grid(row=1, column=1, padx=5)

        ttk.Label(settings_grid, text="Max Cadence (RPM):").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Spinbox(settings_grid, from_=100, to=250, textvariable=self.max_cadence, width=8).grid(row=2, column=1, padx=5)

        ttk.Label(settings_grid, text="Bin Size (RPM):").grid(row=3, column=0, sticky="w", pady=2)
        ttk.Spinbox(settings_grid, from_=1, to=20, textvariable=self.bin_size, width=8).grid(row=3, column=1, padx=5)

        # === Section 3: Actions ===
        actions_frame = ttk.LabelFrame(scrollable_frame, text="Actions", padding=10)
        actions_frame.pack(fill="x", padx=5, pady=5)

        # Row 1: Collection
        ttk.Button(
            actions_frame,
            text="Collect Data",
            command=self._run_collection,
            width=20
        ).pack(pady=5, fill="x")

        # Row 2: Analysis
        ttk.Button(
            actions_frame,
            text="Analyze / Compute Statistics",
            command=self._run_analysis,
            width=20
        ).pack(pady=5, fill="x")

        # Row 3: Validation
        ttk.Button(
            actions_frame,
            text="Validate Gear Assignments",
            command=self._run_validation,
            width=20
        ).pack(pady=5, fill="x")

        # Row 4: Summary
        ttk.Button(
            actions_frame,
            text="Show Summary",
            command=self._show_summary,
            width=20
        ).pack(pady=5, fill="x")

        # Row 5: Export
        ttk.Button(
            actions_frame,
            text="Export to CSV",
            command=self._export_csv,
            width=20
        ).pack(pady=5, fill="x")

        # === Section 4: Interpolation ===
        interp_frame = ttk.LabelFrame(scrollable_frame, text="Interpolate to New Gear", padding=10)
        interp_frame.pack(fill="x", padx=5, pady=5)

        interp_grid = ttk.Frame(interp_frame)
        interp_grid.pack(fill="x")

        ttk.Label(interp_grid, text="Chainring:").grid(row=0, column=0, sticky="w", pady=2)
        self.interp_chainring = tk.IntVar(value=55)
        ttk.Spinbox(interp_grid, from_=48, to=60, textvariable=self.interp_chainring, width=8).grid(row=0, column=1, padx=5)

        ttk.Label(interp_grid, text="Cog:").grid(row=1, column=0, sticky="w", pady=2)
        self.interp_cog = tk.IntVar(value=13)
        ttk.Spinbox(interp_grid, from_=10, to=20, textvariable=self.interp_cog, width=8).grid(row=1, column=1, padx=5)

        ttk.Button(
            interp_frame,
            text="Generate Interpolated Profile",
            command=self._run_interpolation
        ).pack(pady=10, fill="x")

        # === Section 5: Calendar Info ===
        self.calendar_info_frame = ttk.LabelFrame(scrollable_frame, text="Calendar Info", padding=10)
        self.calendar_info_frame.pack(fill="x", padx=5, pady=5)

        self.calendar_info_text = tk.Text(self.calendar_info_frame, height=10, width=45, state="disabled")
        self.calendar_info_text.pack(fill="x")

    def _build_results(self, parent):
        """Build the right results panel."""
        # Notebook for different result views
        self.results_notebook = ttk.Notebook(parent)
        self.results_notebook.pack(fill="both", expand=True)

        # Tab 1: Log Output
        log_frame = ttk.Frame(self.results_notebook)
        self.results_notebook.add(log_frame, text="Log")

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=('Consolas', 10))
        self.log_text.pack(fill="both", expand=True)

        # Tab 2: Statistics Table
        stats_frame = ttk.Frame(self.results_notebook)
        self.results_notebook.add(stats_frame, text="Statistics")

        # Treeview for statistics
        columns = ('gear', 'cadence', 'n', 'mean', 'std', 'max', 'p95', 'torque')
        self.stats_tree = ttk.Treeview(stats_frame, columns=columns, show='headings')

        self.stats_tree.heading('gear', text='Gear')
        self.stats_tree.heading('cadence', text='Cadence')
        self.stats_tree.heading('n', text='N')
        self.stats_tree.heading('mean', text='Mean (W)')
        self.stats_tree.heading('std', text='Std (W)')
        self.stats_tree.heading('max', text='Max (W)')
        self.stats_tree.heading('p95', text='P95 (W)')
        self.stats_tree.heading('torque', text='Max Torque (Nm)')

        self.stats_tree.column('gear', width=80)
        self.stats_tree.column('cadence', width=80)
        self.stats_tree.column('n', width=50)
        self.stats_tree.column('mean', width=80)
        self.stats_tree.column('std', width=80)
        self.stats_tree.column('max', width=80)
        self.stats_tree.column('p95', width=80)
        self.stats_tree.column('torque', width=100)

        stats_scroll = ttk.Scrollbar(stats_frame, orient="vertical", command=self.stats_tree.yview)
        self.stats_tree.configure(yscrollcommand=stats_scroll.set)

        self.stats_tree.pack(side="left", fill="both", expand=True)
        stats_scroll.pack(side="right", fill="y")

        # Tab 3: Gear Profiles
        profiles_frame = ttk.Frame(self.results_notebook)
        self.results_notebook.add(profiles_frame, text="Gear Profiles")

        self.profiles_text = scrolledtext.ScrolledText(profiles_frame, wrap=tk.WORD, font=('Consolas', 10))
        self.profiles_text.pack(fill="both", expand=True)

    # =========================================================================
    # File Operations
    # =========================================================================

    def _browse_calendar(self):
        path = filedialog.askopenfilename(
            title="Select Gear Calendar JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.calendar_path.set(path)

    def _browse_fit_dir(self):
        path = filedialog.askdirectory(title="Select FIT Files Directory")
        if path:
            self.fit_dir_path.set(path)

    def _browse_output_dir(self):
        path = filedialog.askdirectory(title="Select Output Directory")
        if path:
            self.output_dir_path.set(path)

    def _load_calendar(self):
        """Load and display the gear calendar."""
        path = self.calendar_path.get()
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", "Please select a valid calendar file")
            return

        try:
            self.calendar = GearCalendar.from_json(path)
            self._update_calendar_info()
            self._log(f"Loaded calendar: {len(self.calendar.entries)} dates")
            self._log(f"Gear ratios: {', '.join(self.calendar.get_unique_gears())}")

            # Count total efforts
            total_efforts = sum(len(e.assignments) for e in self.calendar.entries)
            self._log(f"Total efforts: {total_efforts}")

            self._update_status("Calendar loaded")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load calendar: {e}")
            self._log(f"ERROR: {e}")

    def _update_calendar_info(self):
        """Update the calendar info display."""
        if not self.calendar:
            return

        self.calendar_info_text.config(state="normal")
        self.calendar_info_text.delete(1.0, tk.END)

        lines = [
            f"Dates: {len(self.calendar.entries)}",
            f"Gears: {', '.join(self.calendar.get_unique_gears())}",
            "",
            "Efforts per date:",
        ]

        # Show dates with mixed gears
        for entry in self.calendar.entries[:15]:  # Show first 15
            gears = [a.gear.gear_ratio_str for a in entry.assignments]
            unique = set(gears)
            if len(unique) > 1:
                lines.append(f"  {entry.date}: {len(entry.assignments)} efforts (MIXED: {', '.join(unique)})")
            else:
                lines.append(f"  {entry.date}: {len(entry.assignments)} efforts @ {gears[0]}")

        if len(self.calendar.entries) > 15:
            lines.append(f"  ... and {len(self.calendar.entries) - 15} more dates")

        self.calendar_info_text.insert(tk.END, "\n".join(lines))
        self.calendar_info_text.config(state="disabled")

    # =========================================================================
    # Main Operations
    # =========================================================================

    def _run_collection(self):
        """Run data collection in background thread."""
        if not self.calendar:
            messagebox.showerror("Error", "Please load a calendar first")
            return

        fit_dir = self.fit_dir_path.get()
        if not fit_dir or not os.path.exists(fit_dir):
            messagebox.showerror("Error", "Please select a valid FIT files directory")
            return

        output_dir = self.output_dir_path.get()
        if not output_dir:
            messagebox.showerror("Error", "Please specify an output directory")
            return

        # Run in thread
        self.progress.start()
        thread = threading.Thread(target=self._collection_worker, args=(fit_dir, output_dir))
        thread.start()

    def _collection_worker(self, fit_dir: str, output_dir: str):
        """Worker thread for data collection."""
        try:
            self._log("\n" + "=" * 60)
            self._log("Starting Data Collection")
            self._log("=" * 60)

            # Initialize
            loader = DataLoader(fit_directory=fit_dir)
            extractor = SprintPhaseExtractor(
                min_power_threshold=self.min_power.get(),
                min_cadence=self.min_cadence.get(),
                max_cadence=self.max_cadence.get(),
            )
            self.store = ConstraintDataStore(output_dir)

            all_observations = []
            success = 0
            failed = 0

            for i, entry in enumerate(self.calendar.entries):
                self._update_status(f"Processing {entry.date} ({i+1}/{len(self.calendar.entries)})")

                try:
                    records = loader.load_records_for_entry(entry)
                    if not records:
                        self._log(f"  {entry.date}: No data found")
                        failed += 1
                        continue

                    # Process each effort assignment
                    for j, assignment in enumerate(entry.assignments):
                        effort_obs_list, detected = extractor.process_activity(
                            records,
                            assignment.gear,
                            entry.date,
                            assignment.effort_type,
                        )

                        # Match detected efforts to assignments by index
                        if assignment.effort_index is not None and assignment.effort_index < len(effort_obs_list):
                            obs = effort_obs_list[assignment.effort_index]
                            all_observations.extend(obs.observations)
                        elif effort_obs_list:
                            # Fallback: use all detected
                            for obs in effort_obs_list:
                                all_observations.extend(obs.observations)

                    n_obs = len([o for o in all_observations if o.source_date == entry.date])
                    self._log(f"  {entry.date}: {len(entry.assignments)} assignments, {n_obs} observations")
                    success += 1

                except Exception as e:
                    self._log(f"  {entry.date}: ERROR - {e}")
                    failed += 1

            # Save observations
            new_count = self.store.save_observations(all_observations, append=True)
            self._log(f"\nSaved {new_count} new observations")
            self._log(f"Success: {success}, Failed: {failed}")

            # Auto-analyze
            self._log("\nComputing statistics...")
            analyzer = CadenceBinAnalyzer(bin_size=self.bin_size.get())
            self.data_set = analyzer.build_all_profiles(self.store.load_observations())
            self.store.save_statistics(self.data_set)

            # Update UI
            self.root.after(0, self._update_statistics_display)
            self._update_status("Collection complete")

        except Exception as e:
            self._log(f"ERROR: {e}")
            self._update_status("Collection failed")

        finally:
            self.root.after(0, self.progress.stop)

    def _run_analysis(self):
        """Recompute statistics from stored observations."""
        output_dir = self.output_dir_path.get()
        if not output_dir:
            messagebox.showerror("Error", "Please specify output directory")
            return

        try:
            self.store = ConstraintDataStore(output_dir)
            observations = self.store.load_observations()

            if not observations:
                messagebox.showwarning("Warning", "No observations found. Run collection first.")
                return

            self._log("\n" + "=" * 60)
            self._log("Analyzing Data")
            self._log("=" * 60)
            self._log(f"Loaded {len(observations)} observations")

            analyzer = CadenceBinAnalyzer(bin_size=self.bin_size.get())
            self.data_set = analyzer.build_all_profiles(observations)
            self.store.save_statistics(self.data_set)

            self._log(f"Computed profiles for {len(self.data_set.profiles)} gears")
            self._update_statistics_display()
            self._update_status("Analysis complete")

        except Exception as e:
            messagebox.showerror("Error", f"Analysis failed: {e}")
            self._log(f"ERROR: {e}")

    def _run_validation(self):
        """Validate gear assignments using speed/cadence inference."""
        if not self.calendar:
            messagebox.showerror("Error", "Please load a calendar first")
            return

        fit_dir = self.fit_dir_path.get()
        if not fit_dir:
            messagebox.showerror("Error", "Please specify FIT directory")
            return

        self.progress.start()
        thread = threading.Thread(target=self._validation_worker, args=(fit_dir,))
        thread.start()

    def _validation_worker(self, fit_dir: str):
        """Worker thread for gear validation."""
        try:
            self._log("\n" + "=" * 60)
            self._log("Validating Gear Assignments")
            self._log("=" * 60)

            loader = DataLoader(fit_directory=fit_dir)
            extractor = SprintPhaseExtractor(
                min_power_threshold=self.min_power.get(),
                min_cadence=self.min_cadence.get(),
            )
            inference = GearInferenceEngine()

            for entry in self.calendar.entries:
                self._update_status(f"Validating {entry.date}")

                try:
                    records = loader.load_records_for_entry(entry)
                    if not records:
                        self._log(f"{entry.date}: No data found")
                        continue

                    # Detect efforts
                    effort_obs_list, detected = extractor.process_activity(
                        records,
                        entry.assignments[0].gear,  # Use first gear for detection
                        entry.date,
                        entry.effort_type,
                    )

                    self._log(f"\n{entry.date}: {len(detected)} efforts detected, {len(entry.assignments)} assigned")

                    # Validate each detected effort
                    for i, effort in enumerate(detected):
                        # Get sprint records
                        sprint_records = extractor.extract_sprint_records(records, effort)

                        # Infer gear
                        inferred = inference.infer_gear_from_records([
                            {'speed_kph': r.speed_kph, 'cadence_rpm': r.cadence_rpm}
                            for r in sprint_records
                        ])

                        # Get assigned gear for this effort index
                        assignment = entry.get_gear_for_effort(i, effort.start_time)
                        assigned_str = assignment.gear.gear_ratio_str if assignment else "NOT ASSIGNED"

                        # Compare
                        inferred_str = f"{inferred.inferred_chainring}/{inferred.inferred_cog}"
                        match = "✓" if assignment and abs(inferred.inferred_ratio - assignment.gear.gear_ratio) < 0.1 else "✗"

                        self._log(f"  Effort {i+1}: Assigned={assigned_str}, Inferred={inferred_str} "
                                 f"(conf={inferred.confidence:.0%}) {match}")

                except Exception as e:
                    self._log(f"{entry.date}: ERROR - {e}")

            self._update_status("Validation complete")

        except Exception as e:
            self._log(f"ERROR: {e}")

        finally:
            self.root.after(0, self.progress.stop)

    def _run_interpolation(self):
        """Generate interpolated profile for new gear."""
        output_dir = self.output_dir_path.get()
        if not output_dir:
            messagebox.showerror("Error", "Please specify output directory")
            return

        try:
            self.store = ConstraintDataStore(output_dir)
            self.data_set = self.store.load_statistics()

            if not self.data_set or not self.data_set.profiles:
                messagebox.showwarning("Warning", "No statistics found. Run analysis first.")
                return

            chainring = self.interp_chainring.get()
            cog = self.interp_cog.get()
            target_gear = f"{chainring}/{cog}"

            self._log("\n" + "=" * 60)
            self._log(f"Interpolating to {target_gear}")
            self._log("=" * 60)

            if target_gear in self.data_set.profiles:
                self._log(f"Note: {target_gear} is already measured")

            interpolator = GearRatioInterpolator(self.data_set.profiles)
            new_profile = interpolator.generate_profile_for_gear(chainring, cog)

            # Add to data set
            self.data_set.add_profile(new_profile)
            self.store.save_statistics(self.data_set)

            self._log(f"Generated profile with {len(new_profile.bins)} cadence bins")
            self._log("\nProfile:")
            self._log(f"{'Cadence':<12} {'P95 (W)':<10} {'Max (W)':<10} {'Torque (Nm)':<12}")
            self._log("-" * 50)

            for bin_stats in new_profile.bins:
                self._log(f"{bin_stats.cadence_range:<12} {bin_stats.p95_power_W:<10.0f} "
                         f"{bin_stats.max_power_W:<10.0f} {bin_stats.max_torque_Nm:<12.1f}")

            self._update_statistics_display()
            self._update_status(f"Interpolated profile for {target_gear}")

        except Exception as e:
            messagebox.showerror("Error", f"Interpolation failed: {e}")
            self._log(f"ERROR: {e}")

    def _show_summary(self):
        """Show summary of collected data."""
        output_dir = self.output_dir_path.get()
        if not output_dir:
            messagebox.showerror("Error", "Please specify output directory")
            return

        try:
            self.store = ConstraintDataStore(output_dir)
            summary = self.store.get_summary()

            self._log("\n" + "=" * 60)
            self._log("Data Summary")
            self._log("=" * 60)

            for key, value in summary.items():
                self._log(f"  {key}: {value}")

        except Exception as e:
            self._log(f"ERROR: {e}")

    def _export_csv(self):
        """Export statistics to CSV."""
        output_dir = self.output_dir_path.get()
        if not output_dir:
            messagebox.showerror("Error", "Please specify output directory")
            return

        try:
            self.store = ConstraintDataStore(output_dir)
            csv_path = self.store.export_statistics_csv()
            self._log(f"\nExported to: {csv_path}")
            messagebox.showinfo("Export Complete", f"Exported to:\n{csv_path}")

        except Exception as e:
            messagebox.showerror("Error", f"Export failed: {e}")

    # =========================================================================
    # UI Updates
    # =========================================================================

    def _update_statistics_display(self):
        """Update the statistics treeview."""
        # Clear existing
        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)

        if not self.data_set:
            return

        # Populate
        for gear_str, profile in sorted(self.data_set.profiles.items()):
            for bin_stats in profile.bins:
                self.stats_tree.insert('', 'end', values=(
                    gear_str,
                    bin_stats.cadence_range,
                    bin_stats.n_samples,
                    f"{bin_stats.mean_power_W:.0f}",
                    f"{bin_stats.std_power_W:.0f}",
                    f"{bin_stats.max_power_W:.0f}",
                    f"{bin_stats.p95_power_W:.0f}",
                    f"{bin_stats.max_torque_Nm:.1f}",
                ))

        # Update profiles tab
        self._update_profiles_display()

    def _update_profiles_display(self):
        """Update the profiles text display."""
        if not self.data_set:
            return

        self.profiles_text.delete(1.0, tk.END)

        for gear_str, profile in sorted(self.data_set.profiles.items()):
            interp = " (INTERPOLATED)" if profile.is_interpolated else ""
            self.profiles_text.insert(tk.END, f"\n{'='*70}\n")
            self.profiles_text.insert(tk.END, f"{gear_str}{interp}\n")
            self.profiles_text.insert(tk.END, f"{'='*70}\n")
            self.profiles_text.insert(tk.END, f"Observations: {profile.n_total_observations}\n")
            self.profiles_text.insert(tk.END, f"Efforts: {profile.n_efforts}\n")
            self.profiles_text.insert(tk.END, f"Cadence range: {profile.cadence_range[0]}-{profile.cadence_range[1]} RPM\n\n")

            # Basic stats header
            self.profiles_text.insert(tk.END, f"{'Cadence':<12} {'Mean':<8} {'P95':<8} {'Max':<8} {'Torque':<10}\n")
            self.profiles_text.insert(tk.END, "-" * 50 + "\n")

            for bin_stats in profile.bins:
                self.profiles_text.insert(tk.END,
                    f"{bin_stats.cadence_range:<12} {bin_stats.mean_power_W:<8.0f} "
                    f"{bin_stats.p95_power_W:<8.0f} {bin_stats.max_power_W:<8.0f} "
                    f"{bin_stats.max_torque_Nm:<10.1f}\n"
                )

            # Duration-based power if available
            has_duration_data = any(
                bin_stats.power_by_duration for bin_stats in profile.bins
            )
            if has_duration_data:
                self.profiles_text.insert(tk.END, f"\nDuration-Based Power (MMP):\n")
                self.profiles_text.insert(tk.END, "-" * 70 + "\n")

                # Header row with durations
                header = f"{'Cadence':<10}"
                for dur in STANDARD_DURATIONS:
                    header += f"{dur}s".rjust(8)
                self.profiles_text.insert(tk.END, header + "\n")

                for bin_stats in profile.bins:
                    if bin_stats.power_by_duration:
                        row = f"{bin_stats.cadence_range:<10}"
                        for dur in STANDARD_DURATIONS:
                            dur_stats = bin_stats.power_by_duration.get(dur)
                            if dur_stats:
                                row += f"{dur_stats.max_power_W:>8.0f}"
                            else:
                                row += f"{'--':>8}"
                        self.profiles_text.insert(tk.END, row + "\n")

    def _log(self, message: str):
        """Add message to log."""
        self.root.after(0, lambda: self._log_immediate(message))

    def _log_immediate(self, message: str):
        """Add message to log (must be called from main thread)."""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def _update_status(self, message: str):
        """Update status bar."""
        self.root.after(0, lambda: self.status_var.set(message))


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """Launch the Constraints GUI."""
    root = tk.Tk()

    # Set theme
    try:
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')
    except tk.TclError:
        pass

    app = ConstraintsGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
