"""
Flying 200 V2 - Simulation Tab

Three-panel simulation comparison interface:
- Left: Simulation 1 (base simulation with full controls)
- Middle: Simulation 2 (uses Sim 1 profile with editable params + overrides)
- Right: Delta panel (shows differences between simulations)
"""

import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from typing import Optional, Dict, Callable
import sys
import os

# Handle imports for both direct and package execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from core.physics import simulate_profile, SimulationConfig
from core.track import (
    BROMONT_250M, MILTON_250M, AVAILABLE_TRACKS, get_segment_name,
    rho_from_altitude, get_track_rho, rho_from_conditions, get_standard_pressure_at_altitude,
)
from core.session import Session
from charts import (
    ChartCanvas,
    create_velocity_chart,
    create_power_chart,
    create_combined_chart,
    create_comparison_chart,
)


# =============================================================================
# Simulation Tab
# =============================================================================

class SimulationTab:
    """
    Simulation tab for Flying 200 GUI with three-panel comparison layout.

    Contains:
    - Left: Simulation 1 with full controls
    - Middle: Simulation 2 with editable params + profile overrides
    - Right: Delta panel showing differences
    """

    def __init__(
        self,
        parent: ttk.Frame,
        session: Session,
        status_callback: Optional[Callable[[str], None]] = None,
        header_callback: Optional[Callable[[], None]] = None,
        calibration_callback: Optional[Callable] = None,
    ):
        """
        Initialize simulation tab.

        Args:
            parent: Parent frame to build in
            session: Session object for state tracking
            status_callback: Callback for status updates
            header_callback: Callback to refresh main header
            calibration_callback: Callback to update calibration tab with results
        """
        self.parent = parent
        self.session = session
        self.status_callback = status_callback or (lambda x: None)
        self.header_callback = header_callback or (lambda: None)
        self.calibration_callback = calibration_callback

        # Results storage - Simulation 1
        self.sim1_result = None
        self.s_grid = None
        self.y_grid = None
        self.last_config = None

        # Store raw profile arrays from Sim 1 for Sim 2 to use
        self.sim1_s_break = None
        self.sim1_y_break = None
        self.sim1_cda_break = None
        self.sim1_p_break = None

        # Results storage - Simulation 2
        self.sim2_result = None

        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build the three-panel simulation UI."""
        # Main horizontal paned window
        self.paned = ttk.PanedWindow(self.parent, orient="horizontal")
        self.paned.pack(fill="both", expand=True)

        # Create three panels
        self.sim1_container = self._create_scrollable_panel(self.paned)
        self.sim2_container = self._create_scrollable_panel(self.paned)
        self.delta_container = self._create_scrollable_panel(self.paned)

        self.paned.add(self.sim1_container, weight=5)
        self.paned.add(self.sim2_container, weight=5)
        self.paned.add(self.delta_container, weight=1)

        # Build each panel (charts are included inside scrollable panels)
        self._build_sim1_panel()
        self._build_sim2_panel()
        self._build_delta_panel()

    def _create_scrollable_panel(self, parent) -> ttk.Frame:
        """Create a scrollable frame inside parent."""
        container = ttk.Frame(parent)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        # Create window in canvas
        canvas_window = canvas.create_window((0, 0), window=scrollable, anchor="nw")

        # Update scrollregion when scrollable frame changes
        scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        # Stretch scrollable frame to canvas width when canvas resizes
        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mouse wheel scrolling for this canvas
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Store reference to scrollable frame
        container.scrollable = scrollable
        container.canvas = canvas
        return container

    # =========================================================================
    # SIMULATION 1 PANEL
    # =========================================================================

    def _build_sim1_panel(self):
        """Build Simulation 1 panel with full controls."""
        frame = self.sim1_container.scrollable

        # Header
        ttk.Label(frame, text="SIMULATION 1", font=('Segoe UI', 11, 'bold')).pack(pady=5)

        # === DATA SOURCE SECTION ===
        self.data_source_frame = ttk.LabelFrame(frame, text="Active Data Source", padding=5)
        self.data_source_frame.pack(fill="x", padx=5, pady=5)
        self._build_data_source_section(self.data_source_frame)

        # === PARAMETERS SECTION ===
        params_frame = ttk.LabelFrame(frame, text="Simulation Parameters", padding=5)
        params_frame.pack(fill="x", padx=5, pady=5)
        self._build_params_section(params_frame)

        # Now that csv_var exists, update the data source display
        self._update_data_source_display()

        # === BUTTONS SECTION ===
        buttons_frame = ttk.Frame(frame)
        buttons_frame.pack(fill="x", padx=5, pady=5)

        ttk.Button(buttons_frame, text="Run Simulation", command=self._run_simulation).pack(side="left", padx=5)
        ttk.Button(buttons_frame, text="Load Profile CSV", command=self._browse_csv).pack(side="left", padx=5)

        # === RESULTS SECTION ===
        self.sim1_results_frame = ttk.LabelFrame(frame, text="Results", padding=5)
        self.sim1_results_frame.pack(fill="x", padx=5, pady=5)

        # Tables frame for Sim 1
        self.sim1_tables_frame = ttk.Frame(self.sim1_results_frame)
        self.sim1_tables_frame.pack(fill="x", pady=5)

        # === CHART SECTION (inside scrollable panel) ===
        self.sim1_chart_frame = ttk.LabelFrame(frame, text="Chart", padding=5)
        self.sim1_chart_frame.pack(fill="x", padx=5, pady=5)

        # Create a frame with minimum height for the chart
        chart_inner = ttk.Frame(self.sim1_chart_frame)
        chart_inner.pack(fill="both", expand=True)
        chart_inner.configure(height=400)  # Minimum height for chart visibility
        chart_inner.pack_propagate(False)  # Prevent shrinking

        self.chart_canvas = ChartCanvas(chart_inner)

    def _build_data_source_section(self, parent: ttk.Frame):
        """Build the data source display section."""
        # Row 1: Source type indicator
        row1 = ttk.Frame(parent)
        row1.pack(fill="x", pady=2)

        ttk.Label(row1, text="Source:", font=('Segoe UI', 9, 'bold')).pack(side="left", padx=5)
        self.source_type_var = tk.StringVar(value="(none)")
        self.source_type_label = ttk.Label(
            row1,
            textvariable=self.source_type_var,
            foreground='#DC2626',
            font=('Segoe UI', 9, 'bold')
        )
        self.source_type_label.pack(side="left", padx=5)

        # Refresh button
        ttk.Button(row1, text="Refresh", command=self._update_data_source_display, width=8).pack(side="right", padx=2)
        ttk.Button(row1, text="Clear", command=self._clear_session_profile, width=6).pack(side="right", padx=2)

        # Row 2: Profile summary
        row2 = ttk.Frame(parent)
        row2.pack(fill="x", pady=2)

        self.profile_summary_var = tk.StringVar(value="No profile loaded")
        ttk.Label(row2, textvariable=self.profile_summary_var, foreground='#6B7280', wraplength=300).pack(side="left", padx=5)

    def _update_data_source_display(self):
        """Update the data source display to show current state."""
        if self.session.profile is not None:
            profile = self.session.profile
            source = profile.source

            y_min, y_max = profile.y_m.min(), profile.y_m.max()
            cda_min, cda_max = profile.CdA_m2.min(), profile.CdA_m2.max()
            p_min, p_max = profile.P_W.min(), profile.P_W.max()

            self.source_type_var.set(f"SESSION: {source}")
            self.source_type_label.config(foreground='#059669')

            if y_min == 0 and y_max == 0:
                y_warning = " (y_m=0)"
            else:
                y_warning = ""

            summary = (
                f"s: {profile.s_m[0]:.0f}-{profile.s_m[-1]:.0f}m | "
                f"y: {y_min:.1f}-{y_max:.1f}m{y_warning} | "
                f"CdA: {cda_min:.3f}-{cda_max:.3f} | "
                f"P: {p_min:.0f}-{p_max:.0f}W"
            )
            self.profile_summary_var.set(summary)
        else:
            csv_path = self.csv_var.get()
            self.source_type_var.set(f"CSV: {csv_path}")
            self.source_type_label.config(foreground='#2563EB')
            self.profile_summary_var.set("Will load from CSV file")

    def _clear_session_profile(self):
        """Clear the session profile so CSV will be used instead."""
        self.session.profile = None
        self._update_data_source_display()
        self.header_callback()
        self.status_callback("Session profile cleared")

    def _build_params_section(self, parent: ttk.Frame):
        """Build parameter input controls for Sim 1."""
        # Row 1: File parameters
        row1 = ttk.Frame(parent)
        row1.pack(fill="x", pady=2)

        ttk.Label(row1, text="CSV:").pack(side="left", padx=2)
        self.csv_var = tk.StringVar(value="profile_f200.csv")
        ttk.Entry(row1, textvariable=self.csv_var, width=20).pack(side="left", padx=2)

        ttk.Label(row1, text="Track:").pack(side="left", padx=5)
        self.track_var = tk.StringVar(value="Bromont")
        track_combo = ttk.Combobox(
            row1, textvariable=self.track_var,
            values=list(AVAILABLE_TRACKS.keys()),
            state="readonly", width=10
        )
        track_combo.pack(side="left", padx=2)
        track_combo.bind("<<ComboboxSelected>>", self._on_track_changed)

        # Row 2: Rider parameters
        row2 = ttk.Frame(parent)
        row2.pack(fill="x", pady=2)

        ttk.Label(row2, text="Mass:").pack(side="left", padx=2)
        self.mass_var = tk.StringVar(value="92.0")
        ttk.Entry(row2, textvariable=self.mass_var, width=6).pack(side="left", padx=2)

        ttk.Label(row2, text="Rho:").pack(side="left", padx=5)
        self.rho_var = tk.StringVar(value="1.2010")  # Bromont default
        ttk.Entry(row2, textvariable=self.rho_var, width=7).pack(side="left", padx=2)

        # Altitude correction button
        ttk.Button(row2, text="↻ Alt", width=5, command=self._apply_altitude_correction).pack(side="left", padx=2)

        ttk.Label(row2, text="C_RR:").pack(side="left", padx=5)
        self.crr_var = tk.StringVar(value="0.0020")
        ttk.Entry(row2, textvariable=self.crr_var, width=7).pack(side="left", padx=2)

        # Row 3: More parameters
        row3 = ttk.Frame(parent)
        row3.pack(fill="x", pady=2)

        ttk.Label(row3, text="V0:").pack(side="left", padx=2)
        self.v0_var = tk.StringVar(value="5.0")
        ttk.Entry(row3, textvariable=self.v0_var, width=5).pack(side="left", padx=2)

        ttk.Label(row3, text="S_TOT:").pack(side="left", padx=5)
        self.s_total_var = tk.StringVar(value="895.0")
        ttk.Entry(row3, textvariable=self.s_total_var, width=6).pack(side="left", padx=2)

        ttk.Label(row3, text="DS:").pack(side="left", padx=5)
        self.ds_var = tk.StringVar(value="0.25")
        ttk.Entry(row3, textvariable=self.ds_var, width=5).pack(side="left", padx=2)

        # Row 4: Efficiency and CdA
        row4 = ttk.Frame(parent)
        row4.pack(fill="x", pady=2)

        ttk.Label(row4, text="Eff:").pack(side="left", padx=2)
        self.eff_var = tk.StringVar(value="0.98")
        ttk.Entry(row4, textvariable=self.eff_var, width=5).pack(side="left", padx=2)

        ttk.Label(row4, text="CdA Bend:").pack(side="left", padx=5)
        self.cda_bend_factor_var = tk.StringVar(value="0.97")
        ttk.Entry(row4, textvariable=self.cda_bend_factor_var, width=5).pack(side="left", padx=2)

        # Row 5: Environmental conditions for rho calculation
        row5 = ttk.Frame(parent)
        row5.pack(fill="x", pady=2)

        ttk.Label(row5, text="Temp (°C):").pack(side="left", padx=2)
        self.temp_var = tk.StringVar(value="20.0")
        ttk.Entry(row5, textvariable=self.temp_var, width=5).pack(side="left", padx=2)

        ttk.Label(row5, text="Humidity (%):").pack(side="left", padx=5)
        self.humidity_var = tk.StringVar(value="50")
        ttk.Entry(row5, textvariable=self.humidity_var, width=4).pack(side="left", padx=2)

        ttk.Label(row5, text="Baro (hPa):").pack(side="left", padx=5)
        # Default to standard pressure at Bromont altitude
        self.baro_var = tk.StringVar(value="989")
        ttk.Entry(row5, textvariable=self.baro_var, width=5).pack(side="left", padx=2)

        ttk.Button(row5, text="Calc ρ", width=5, command=self._calc_rho_from_conditions).pack(side="left", padx=5)

    def _on_track_changed(self, event=None):
        """Handle track selection change."""
        track_name = self.track_var.get()
        track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)
        self.session.track = track
        # Update default barometric pressure for the track altitude
        std_pressure = get_standard_pressure_at_altitude(track.altitude_m)
        self.baro_var.set(f"{std_pressure:.0f}")
        # Auto-apply altitude correction
        self._apply_altitude_correction()

    def _apply_altitude_correction(self):
        """Apply altitude-based air density correction for the selected track."""
        track_name = self.track_var.get()
        track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)
        rho = get_track_rho(track)
        self.rho_var.set(f"{rho:.4f}")
        self.status_callback(f"Rho set to {rho:.4f} kg/m³ (altitude: {track.altitude_m:.0f}m)")

    def _calc_rho_from_conditions(self):
        """Calculate rho from temperature, humidity, and barometric pressure."""
        try:
            temp_c = float(self.temp_var.get())
            humidity_pct = float(self.humidity_var.get())
            pressure_hpa = float(self.baro_var.get())

            rho = rho_from_conditions(temp_c, humidity_pct, pressure_hpa)
            self.rho_var.set(f"{rho:.4f}")
            self.status_callback(
                f"Rho = {rho:.4f} kg/m³ (T={temp_c:.1f}°C, RH={humidity_pct:.0f}%, P={pressure_hpa:.0f}hPa)"
            )
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please enter valid numeric values.\n{str(e)}")

    def _browse_csv(self):
        """Browse for profile CSV file and load it."""
        filepath = filedialog.askopenfilename(
            title="Select Profile CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filepath:
            self.csv_var.set(filepath)
            try:
                from core.session import Profile
                profile = Profile.from_csv(filepath)
                self.session.set_profile(profile)
                self._update_data_source_display()
                self.header_callback()
                self.status_callback(f"Loaded: {profile.source}")
            except Exception as e:
                messagebox.showerror("Load Error", f"Failed to load profile:\n{str(e)}")

    def _get_params(self) -> Dict:
        """Get Sim 1 parameters from UI."""
        return {
            'PROFILE_CSV': self.csv_var.get(),
            'S_TOTAL': float(self.s_total_var.get()),
            'DS': float(self.ds_var.get()),
            'M': float(self.mass_var.get()),
            'rho': float(self.rho_var.get()),
            'C_RR': float(self.crr_var.get()),
            'V0': float(self.v0_var.get()),
            'drivetrain_eff': float(self.eff_var.get()),
            'cda_bend_factor': float(self.cda_bend_factor_var.get()),
            'track_name': self.track_var.get(),
        }

    def _run_simulation(self):
        """Run Simulation 1."""
        self._update_data_source_display()
        self.status_callback("Running Simulation 1...")

        try:
            params = self._get_params()

            # Get profile data
            if self.session.profile is not None:
                source_type = f"SESSION: {self.session.profile.source}"
                self.status_callback(f"Using {source_type}...")
                s_break = self.session.profile.s_m.copy()
                y_break = self.session.profile.y_m.copy()
                CdA_break = self.session.profile.CdA_m2.copy()
                P_break = self.session.profile.P_W.copy()
            else:
                csv_path = params['PROFILE_CSV']
                if not csv_path or csv_path == "profile_f200.csv":
                    messagebox.showwarning(
                        "No Profile",
                        "No profile loaded.\n\n"
                        "Either:\n"
                        "1. Export a profile from FIT Analysis tab, or\n"
                        "2. Enter a valid CSV file path"
                    )
                    return

                profile = pd.read_csv(csv_path)
                profile.columns = profile.columns.str.strip()

                required_cols = ["s_m", "y_m", "CdA_m2", "P_W"]
                for col in required_cols:
                    if col not in profile.columns:
                        raise ValueError(f"Required column '{col}' not found")

                profile = profile.sort_values("s_m").reset_index(drop=True)
                s_break = profile["s_m"].to_numpy()
                y_break = profile["y_m"].to_numpy()
                CdA_break = profile["CdA_m2"].to_numpy()
                P_break = profile["P_W"].to_numpy()

            # Store raw profile for Sim 2 to use
            self.sim1_s_break = s_break.copy()
            self.sim1_y_break = y_break.copy()
            self.sim1_cda_break = CdA_break.copy()
            self.sim1_p_break = P_break.copy()

            # Build grids
            self.s_grid = np.arange(0.0, params['S_TOTAL'] + params['DS'], params['DS'])

            # Interpolate to grid
            y_grid = np.interp(self.s_grid, s_break, y_break)
            CdA_grid = np.interp(self.s_grid, s_break, CdA_break)
            P_grid = np.interp(self.s_grid, s_break, P_break)

            # Get track
            track_name = self.track_var.get()
            track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)

            # Create simulation config
            config = SimulationConfig(
                mass_kg=params['M'],
                rho_kg_m3=params['rho'],
                c_rr=params['C_RR'],
                v0_m_s=params['V0'],
                ds_m=params['DS'],
                drivetrain_efficiency=params['drivetrain_eff'],
                cda_bend_factor=params['cda_bend_factor'],
                w_prime_joules=float('inf'),  # Simulator: no joule balance
            )

            self.session.track = track
            self.y_grid = y_grid
            self.last_config = params

            # Run simulation
            self.sim1_result = simulate_profile(
                self.s_grid,
                y_grid,
                CdA_grid,
                P_grid,
                config,
                track_geometry=track,
            )

            # Store in session
            if self.sim1_result is not None:
                result_dict = {
                    'T_200': self.sim1_result.T_200,
                    'T_total': self.sim1_result.T_total,
                    'v_200_entry': self.sim1_result.v_200_entry,
                    'v_200_exit': self.sim1_result.v_200_exit,
                    'P_avg_sprint': self.sim1_result.P_avg_sprint,
                    'line_cost_200': self.sim1_result.line_cost_200,
                    'v': self.sim1_result.v.copy(),
                    'P_eff': self.sim1_result.P_eff.copy(),
                    'CdA': self.sim1_result.CdA.copy(),
                    's_grid': self.s_grid.copy(),
                    'y_grid': y_grid.copy(),
                    'CdA_grid': CdA_grid.copy(),
                    'P_grid': P_grid.copy(),
                }
                self.session.set_simulation_result(result_dict, params)

            # Display results
            self._display_sim1_results(params)
            self._update_chart()
            self._update_delta_display()

            # Fill Sim 2 grid with Sim 1 values
            self._fill_grid_from_sim1()

            # Calibration callback
            if self.calibration_callback and self.sim1_result is not None:
                self.calibration_callback(
                    self.sim1_result,
                    self.s_grid,
                    self.y_grid,
                    params
                )

            self.status_callback("Simulation 1 complete!")

        except Exception as e:
            self.status_callback(f"Error: {str(e)}")
            messagebox.showerror("Simulation Error", str(e))

    def _display_sim1_results(self, params: Dict):
        """Display Simulation 1 results."""
        # Clear previous
        for widget in self.sim1_tables_frame.winfo_children():
            widget.destroy()

        if self.sim1_result is None:
            return

        # Summary
        self._build_summary_table(self.sim1_tables_frame, self.sim1_result, "200m Summary")

        # Power breakdown
        self._build_power_breakdown(self.sim1_tables_frame, self.sim1_result, params)

    # =========================================================================
    # SIMULATION 2 PANEL
    # =========================================================================

    def _build_sim2_panel(self):
        """Build Simulation 2 panel with editable params + override table."""
        frame = self.sim2_container.scrollable

        # Header
        ttk.Label(frame, text="SIMULATION 2", font=('Segoe UI', 11, 'bold')).pack(pady=5)

        # Data source label (read-only - profile comes from Sim 1)
        src_frame = ttk.LabelFrame(frame, text="Data Source", padding=5)
        src_frame.pack(fill="x", padx=5, pady=5)
        ttk.Label(src_frame, text="Uses Sim 1 profile data", foreground='#6B7280').pack()

        # === PARAMETERS SECTION (EDITABLE) ===
        params_frame = ttk.LabelFrame(frame, text="Simulation Parameters", padding=5)
        params_frame.pack(fill="x", padx=5, pady=5)
        self._build_sim2_params_section(params_frame)

        # === PROFILE OVERRIDES (editable grid like Track Tab) ===
        override_frame = ttk.LabelFrame(frame, text="Profile Overrides", padding=5)
        override_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self._build_override_table(override_frame)

        # === BUTTONS ===
        buttons_frame = ttk.Frame(frame)
        buttons_frame.pack(fill="x", padx=5, pady=5)
        ttk.Button(buttons_frame, text="Run Simulation 2", command=self._run_simulation_2).pack(side="left", padx=5)

        # === RESULTS SECTION ===
        self.sim2_results_frame = ttk.LabelFrame(frame, text="Results", padding=5)
        self.sim2_results_frame.pack(fill="x", padx=5, pady=5)

        self.sim2_tables_frame = ttk.Frame(self.sim2_results_frame)
        self.sim2_tables_frame.pack(fill="x", pady=5)

    def _build_sim2_params_section(self, parent: ttk.Frame):
        """Build Sim 2 parameter controls - independent from Sim 1."""
        # Row 1: Track
        row1 = ttk.Frame(parent)
        row1.pack(fill="x", pady=2)

        ttk.Label(row1, text="Track:").pack(side="left", padx=2)
        self.sim2_track_var = tk.StringVar(value="Bromont")
        track_combo = ttk.Combobox(
            row1, textvariable=self.sim2_track_var,
            values=list(AVAILABLE_TRACKS.keys()),
            state="readonly", width=10
        )
        track_combo.pack(side="left", padx=2)
        track_combo.bind("<<ComboboxSelected>>", self._on_sim2_track_changed)

        # Row 2: Rider/environment
        row2 = ttk.Frame(parent)
        row2.pack(fill="x", pady=2)

        ttk.Label(row2, text="Mass:").pack(side="left", padx=2)
        self.sim2_mass_var = tk.StringVar(value="92.0")
        ttk.Entry(row2, textvariable=self.sim2_mass_var, width=6).pack(side="left", padx=2)

        ttk.Label(row2, text="Rho:").pack(side="left", padx=5)
        self.sim2_rho_var = tk.StringVar(value="1.2010")  # Bromont default
        ttk.Entry(row2, textvariable=self.sim2_rho_var, width=7).pack(side="left", padx=2)

        # Altitude correction button
        ttk.Button(row2, text="↻ Alt", width=5, command=self._apply_sim2_altitude_correction).pack(side="left", padx=2)

        ttk.Label(row2, text="C_RR:").pack(side="left", padx=5)
        self.sim2_crr_var = tk.StringVar(value="0.0020")
        ttk.Entry(row2, textvariable=self.sim2_crr_var, width=7).pack(side="left", padx=2)

        # Row 3: More parameters
        row3 = ttk.Frame(parent)
        row3.pack(fill="x", pady=2)

        ttk.Label(row3, text="V0:").pack(side="left", padx=2)
        self.sim2_v0_var = tk.StringVar(value="5.0")
        ttk.Entry(row3, textvariable=self.sim2_v0_var, width=5).pack(side="left", padx=2)

        ttk.Label(row3, text="Eff:").pack(side="left", padx=5)
        self.sim2_eff_var = tk.StringVar(value="0.98")
        ttk.Entry(row3, textvariable=self.sim2_eff_var, width=5).pack(side="left", padx=2)

        ttk.Label(row3, text="CdA Bend:").pack(side="left", padx=5)
        self.sim2_cda_bend_factor_var = tk.StringVar(value="0.97")
        ttk.Entry(row3, textvariable=self.sim2_cda_bend_factor_var, width=5).pack(side="left", padx=2)

        # Row 4: Environmental conditions for rho calculation
        row4 = ttk.Frame(parent)
        row4.pack(fill="x", pady=2)

        ttk.Label(row4, text="Temp (°C):").pack(side="left", padx=2)
        self.sim2_temp_var = tk.StringVar(value="20.0")
        ttk.Entry(row4, textvariable=self.sim2_temp_var, width=5).pack(side="left", padx=2)

        ttk.Label(row4, text="Humidity (%):").pack(side="left", padx=5)
        self.sim2_humidity_var = tk.StringVar(value="50")
        ttk.Entry(row4, textvariable=self.sim2_humidity_var, width=4).pack(side="left", padx=2)

        ttk.Label(row4, text="Baro (hPa):").pack(side="left", padx=5)
        self.sim2_baro_var = tk.StringVar(value="989")
        ttk.Entry(row4, textvariable=self.sim2_baro_var, width=5).pack(side="left", padx=2)

        ttk.Button(row4, text="Calc ρ", width=5, command=self._calc_sim2_rho_from_conditions).pack(side="left", padx=5)

        # Copy from Sim 1 button
        ttk.Button(parent, text="Copy from Sim 1", command=self._copy_params_from_sim1).pack(pady=5)

    def _on_sim2_track_changed(self, event=None):
        """Handle Sim 2 track selection change."""
        track_name = self.sim2_track_var.get()
        track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)
        # Update default barometric pressure for the track altitude
        std_pressure = get_standard_pressure_at_altitude(track.altitude_m)
        self.sim2_baro_var.set(f"{std_pressure:.0f}")
        self._apply_sim2_altitude_correction()

    def _apply_sim2_altitude_correction(self):
        """Apply altitude-based air density correction for Sim 2's selected track."""
        track_name = self.sim2_track_var.get()
        track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)
        rho = get_track_rho(track)
        self.sim2_rho_var.set(f"{rho:.4f}")
        self.status_callback(f"Sim 2 Rho set to {rho:.4f} kg/m³ (altitude: {track.altitude_m:.0f}m)")

    def _calc_sim2_rho_from_conditions(self):
        """Calculate rho from temperature, humidity, and barometric pressure for Sim 2."""
        try:
            temp_c = float(self.sim2_temp_var.get())
            humidity_pct = float(self.sim2_humidity_var.get())
            pressure_hpa = float(self.sim2_baro_var.get())

            rho = rho_from_conditions(temp_c, humidity_pct, pressure_hpa)
            self.sim2_rho_var.set(f"{rho:.4f}")
            self.status_callback(
                f"Sim 2 Rho = {rho:.4f} kg/m³ (T={temp_c:.1f}°C, RH={humidity_pct:.0f}%, P={pressure_hpa:.0f}hPa)"
            )
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please enter valid numeric values.\n{str(e)}")

    def _copy_params_from_sim1(self):
        """Copy all parameter values from Sim 1 to Sim 2."""
        self.sim2_track_var.set(self.track_var.get())
        self.sim2_mass_var.set(self.mass_var.get())
        self.sim2_rho_var.set(self.rho_var.get())
        self.sim2_crr_var.set(self.crr_var.get())
        self.sim2_v0_var.set(self.v0_var.get())
        self.sim2_eff_var.set(self.eff_var.get())
        self.sim2_cda_bend_factor_var.set(self.cda_bend_factor_var.get())
        # Copy environmental conditions
        self.sim2_temp_var.set(self.temp_var.get())
        self.sim2_humidity_var.set(self.humidity_var.get())
        self.sim2_baro_var.set(self.baro_var.get())
        self.status_callback("Copied parameters from Sim 1")

    def _build_override_table(self, parent: ttk.Frame):
        """Build editable grid table for profile overrides with modify range controls."""
        # Main horizontal layout: grid on left, controls on right
        main_container = ttk.Frame(parent)
        main_container.pack(fill="both", expand=True)

        # === LEFT: Grid table ===
        grid_frame = ttk.Frame(main_container)
        grid_frame.pack(side="left", fill="both", expand=True)

        ttk.Label(
            grid_frame,
            text="Edit values directly. Tab=right, Enter=down.",
            foreground='#6B7280',
            font=('Segoe UI', 8)
        ).pack(pady=2)

        # Scrollable canvas for the table
        table_container = ttk.Frame(grid_frame)
        table_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(table_container, height=250, width=240, highlightthickness=0)
        scrollbar_y = ttk.Scrollbar(table_container, orient="vertical", command=canvas.yview)
        self.override_table_frame = ttk.Frame(canvas)

        self.override_table_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.override_table_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_y.set)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        scrollbar_y.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Storage for override entries: list of (s_m, p_var, y_var, cda_var)
        self.override_entries = []
        self.override_entry_widgets = []

        # === RIGHT: Modify Range controls ===
        controls_frame = ttk.LabelFrame(main_container, text="Modify Range", padding=5)
        controls_frame.pack(side="right", fill="y", padx=(10, 0))

        # Range inputs
        range_frame = ttk.Frame(controls_frame)
        range_frame.pack(fill="x", pady=2)
        ttk.Label(range_frame, text="From:", font=('Segoe UI', 8)).grid(row=0, column=0, sticky="w")
        self.range_start_var = tk.StringVar(value="480")
        ttk.Entry(range_frame, textvariable=self.range_start_var, width=5, font=('Segoe UI', 8)).grid(row=0, column=1, padx=2)
        ttk.Label(range_frame, text="To:", font=('Segoe UI', 8)).grid(row=0, column=2, padx=(5, 0), sticky="w")
        self.range_end_var = tk.StringVar(value="695")
        ttk.Entry(range_frame, textvariable=self.range_end_var, width=5, font=('Segoe UI', 8)).grid(row=0, column=3, padx=2)

        # Operation type
        ttk.Label(controls_frame, text="Operation:", font=('Segoe UI', 8)).pack(anchor="w", pady=(5, 0))
        self.range_operation_var = tk.StringVar(value="Add Power")
        operations = [
            "Add Power",
            "Set Power",
            "Add CdA",
            "Set CdA",
            "Add y_m",
            "Set y_m"
        ]
        op_combo = ttk.Combobox(
            controls_frame,
            textvariable=self.range_operation_var,
            values=operations,
            state="readonly",
            width=12,
            font=('Segoe UI', 8)
        )
        op_combo.pack(fill="x", pady=2)

        # Value input
        value_frame = ttk.Frame(controls_frame)
        value_frame.pack(fill="x", pady=2)
        ttk.Label(value_frame, text="Value:", font=('Segoe UI', 8)).pack(side="left")
        self.range_value_var = tk.StringVar(value="20")
        ttk.Entry(value_frame, textvariable=self.range_value_var, width=8, font=('Segoe UI', 8)).pack(side="left", padx=5)

        # Apply button
        ttk.Button(controls_frame, text="Apply", command=self._apply_range_modification, width=10).pack(pady=5)

        # Separator
        ttk.Separator(controls_frame, orient="horizontal").pack(fill="x", pady=5)

        # Reset button
        ttk.Button(controls_frame, text="Reset to Sim 1", command=self._reset_grid_to_sim1, width=12).pack(pady=2)

        # Pre-populate with standard 10m interval markers (empty initially)
        self._populate_override_table()

    def _populate_override_table(self):
        """Populate override table with standard 10m interval markers."""
        # Clear existing entries
        for widget in self.override_table_frame.winfo_children():
            widget.destroy()
        self.override_entries = []
        self.override_entry_widgets = []

        # Header row
        header = ttk.Frame(self.override_table_frame)
        header.pack(fill="x", pady=2)
        ttk.Label(header, text="s_m", width=4, font=('Segoe UI', 8, 'bold')).pack(side="left", padx=1)
        ttk.Label(header, text="P(W)", width=6, font=('Segoe UI', 8, 'bold')).pack(side="left", padx=1)
        ttk.Label(header, text="y_m", width=6, font=('Segoe UI', 8, 'bold')).pack(side="left", padx=1)
        ttk.Label(header, text="CdA", width=7, font=('Segoe UI', 8, 'bold')).pack(side="left", padx=1)

        # Standard markers: 0, 10, 20, ..., 690, 695, 700, ..., 890, 895
        self.grid_markers = list(range(0, 691, 10))  # 0-690 in 10m
        self.grid_markers.append(695)  # 200m start
        self.grid_markers.extend(range(700, 891, 10))  # 700-890 in 10m
        self.grid_markers.append(895)  # Finish
        self.grid_markers.sort()

        # Create entry rows for each marker
        for s_m in self.grid_markers:
            row = ttk.Frame(self.override_table_frame)
            row.pack(fill="x", pady=0)

            # s_m label (read-only)
            ttk.Label(row, text=f"{s_m}", width=4, font=('Segoe UI', 8)).pack(side="left", padx=1)

            # Power entry
            p_var = tk.StringVar(value="")
            p_entry = ttk.Entry(row, textvariable=p_var, width=6, font=('Segoe UI', 8))
            p_entry.pack(side="left", padx=1)

            # y_m entry
            y_var = tk.StringVar(value="")
            y_entry = ttk.Entry(row, textvariable=y_var, width=6, font=('Segoe UI', 8))
            y_entry.pack(side="left", padx=1)

            # CdA entry
            cda_var = tk.StringVar(value="")
            cda_entry = ttk.Entry(row, textvariable=cda_var, width=7, font=('Segoe UI', 8))
            cda_entry.pack(side="left", padx=1)

            self.override_entries.append((s_m, p_var, y_var, cda_var))
            self.override_entry_widgets.extend([p_entry, y_entry, cda_entry])

        # Set up keyboard navigation
        for idx, entry in enumerate(self.override_entry_widgets):
            entry.bind("<Tab>", lambda e, i=idx: self._override_nav_right(i))
            entry.bind("<Return>", lambda e, i=idx: self._override_nav_down(i))
            entry.bind("<Shift-Tab>", lambda e, i=idx: self._override_nav_left(i))

    def _fill_grid_from_sim1(self):
        """Fill the override grid with Sim 1's profile values.

        Stores full-precision original values alongside display strings so that
        _get_profile_from_grid() can detect unmodified cells and avoid rounding
        error when Sim 2 runs with an identical profile.
        """
        if self.sim1_s_break is None:
            return

        # Store original values and display strings for precision recovery
        self._grid_original_values = {}

        # Interpolate Sim 1 profile values at each grid marker
        for s_m, p_var, y_var, cda_var in self.override_entries:
            p_val = np.interp(s_m, self.sim1_s_break, self.sim1_p_break)
            y_val = np.interp(s_m, self.sim1_s_break, self.sim1_y_break)
            cda_val = np.interp(s_m, self.sim1_s_break, self.sim1_cda_break)

            p_str = f"{p_val:.0f}"
            y_str = f"{y_val:.2f}"
            cda_str = f"{cda_val:.4f}"

            self._grid_original_values[s_m] = (p_val, y_val, cda_val, p_str, y_str, cda_str)

            p_var.set(p_str)
            y_var.set(y_str)
            cda_var.set(cda_str)

    def _reset_grid_to_sim1(self):
        """Reset grid values to Sim 1's original profile."""
        if self.sim1_s_break is None:
            messagebox.showinfo("No Data", "Run Simulation 1 first to load profile data.")
            return
        self._fill_grid_from_sim1()
        self.status_callback("Grid reset to Sim 1 values")

    def _apply_range_modification(self):
        """Apply a bulk modification to a range of markers."""
        try:
            start_m = float(self.range_start_var.get())
            end_m = float(self.range_end_var.get())
            value = float(self.range_value_var.get())
            operation = self.range_operation_var.get()
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numeric values.")
            return

        if start_m > end_m:
            start_m, end_m = end_m, start_m

        count = 0
        for s_m, p_var, y_var, cda_var in self.override_entries:
            if start_m <= s_m <= end_m:
                if operation == "Add Power":
                    try:
                        current = float(p_var.get()) if p_var.get() else 0
                        p_var.set(f"{current + value:.0f}")
                        count += 1
                    except ValueError:
                        pass
                elif operation == "Set Power":
                    p_var.set(f"{value:.0f}")
                    count += 1
                elif operation == "Add CdA":
                    try:
                        current = float(cda_var.get()) if cda_var.get() else 0
                        cda_var.set(f"{current + value:.4f}")
                        count += 1
                    except ValueError:
                        pass
                elif operation == "Set CdA":
                    cda_var.set(f"{value:.4f}")
                    count += 1
                elif operation == "Add y_m":
                    try:
                        current = float(y_var.get()) if y_var.get() else 0
                        y_var.set(f"{current + value:.2f}")
                        count += 1
                    except ValueError:
                        pass
                elif operation == "Set y_m":
                    y_var.set(f"{value:.2f}")
                    count += 1

        self.status_callback(f"Modified {count} markers ({start_m:.0f}m - {end_m:.0f}m): {operation} {value}")

    def _override_nav_right(self, idx):
        """Tab: move to next entry (right)."""
        if idx + 1 < len(self.override_entry_widgets):
            self.override_entry_widgets[idx + 1].focus_set()
        return "break"

    def _override_nav_left(self, idx):
        """Shift-Tab: move to previous entry (left)."""
        if idx > 0:
            self.override_entry_widgets[idx - 1].focus_set()
        return "break"

    def _override_nav_down(self, idx):
        """Enter: move down (same column, next row)."""
        # 3 columns per row (P, y_m, CdA)
        next_idx = idx + 3
        if next_idx < len(self.override_entry_widgets):
            self.override_entry_widgets[next_idx].focus_set()
        return "break"

    def _get_sim2_params(self) -> Dict:
        """Get Sim 2 parameters from its own controls."""
        return {
            'S_TOTAL': float(self.s_total_var.get()),  # Same grid as Sim 1
            'DS': float(self.ds_var.get()),
            'M': float(self.sim2_mass_var.get()),
            'rho': float(self.sim2_rho_var.get()),
            'C_RR': float(self.sim2_crr_var.get()),
            'V0': float(self.sim2_v0_var.get()),
            'drivetrain_eff': float(self.sim2_eff_var.get()),
            'cda_bend_factor': float(self.sim2_cda_bend_factor_var.get()),
            'track_name': self.sim2_track_var.get(),
        }

    def _get_profile_from_grid(self):
        """Build profile arrays from the override grid values.

        Uses full-precision original values for unmodified cells to avoid
        rounding error.  When NO cells have been modified, returns Sim 1's
        exact raw breakpoints so identical profiles produce identical results.
        """
        originals = getattr(self, '_grid_original_values', {})

        # --- Fast path: if every cell matches its original display string,
        #     bypass the grid entirely and return Sim 1's raw breakpoints.
        if originals and self.sim1_s_break is not None:
            all_unmodified = True
            for s_m, p_var, y_var, cda_var in self.override_entries:
                if s_m in originals:
                    _, _, _, orig_p_str, orig_y_str, orig_cda_str = originals[s_m]
                    if (p_var.get().strip() != orig_p_str or
                            y_var.get().strip() != orig_y_str or
                            cda_var.get().strip() != orig_cda_str):
                        all_unmodified = False
                        break
                else:
                    all_unmodified = False
                    break

            if all_unmodified:
                return (self.sim1_s_break.copy(), self.sim1_y_break.copy(),
                        self.sim1_cda_break.copy(), self.sim1_p_break.copy())

        # --- Normal path: build from grid, using full-precision originals
        #     for any cell that hasn't been edited.
        s_break = []
        y_break = []
        cda_break = []
        p_break = []

        for s_m, p_var, y_var, cda_var in self.override_entries:
            p_str = p_var.get().strip()
            y_str = y_var.get().strip()
            cda_str = cda_var.get().strip()

            # Include point if all values are present
            if p_str and y_str and cda_str:
                try:
                    s_break.append(float(s_m))

                    # Use full-precision original if the cell is unmodified
                    if s_m in originals:
                        orig_p, orig_y, orig_cda, orig_p_str, orig_y_str, orig_cda_str = originals[s_m]
                        p_break.append(orig_p if p_str == orig_p_str else float(p_str))
                        y_break.append(orig_y if y_str == orig_y_str else float(y_str))
                        cda_break.append(orig_cda if cda_str == orig_cda_str else float(cda_str))
                    else:
                        p_break.append(float(p_str))
                        y_break.append(float(y_str))
                        cda_break.append(float(cda_str))
                except ValueError:
                    pass  # Skip invalid entries

        if not s_break:
            return None, None, None, None

        return np.array(s_break), np.array(y_break), np.array(cda_break), np.array(p_break)

    def _run_simulation_2(self):
        """Run Simulation 2 using Sim 1 profile with overrides."""
        if self.sim1_s_break is None:
            messagebox.showwarning("No Profile", "Run Simulation 1 first to load profile data.")
            return

        self.status_callback("Running Simulation 2...")

        try:
            params = self._get_sim2_params()

            # Build profile directly from grid values (not merging with Sim 1 breakpoints)
            s_break, y_break, cda_break, p_break = self._get_profile_from_grid()

            if s_break is None or len(s_break) == 0:
                messagebox.showwarning(
                    "No Profile Data",
                    "Grid is empty. Run Simulation 1 first to populate the grid."
                )
                return

            # Use same grid as Sim 1
            s_grid = self.s_grid

            # Interpolate to grid
            y_grid = np.interp(s_grid, s_break, y_break)
            CdA_grid = np.interp(s_grid, s_break, cda_break)
            P_grid = np.interp(s_grid, s_break, p_break)

            # Get track
            track_name = self.sim2_track_var.get()
            track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)

            # Create simulation config with Sim 2 parameters
            config = SimulationConfig(
                mass_kg=params['M'],
                rho_kg_m3=params['rho'],
                c_rr=params['C_RR'],
                v0_m_s=params['V0'],
                ds_m=params['DS'],
                drivetrain_efficiency=params['drivetrain_eff'],
                cda_bend_factor=params['cda_bend_factor'],
                w_prime_joules=float('inf'),  # Simulator: no joule balance
            )

            # Run simulation
            self.sim2_result = simulate_profile(
                s_grid,
                y_grid,
                CdA_grid,
                P_grid,
                config,
                track_geometry=track,
            )

            # Display results
            self._display_sim2_results(params)
            self._update_chart()
            self._update_delta_display()

            self.status_callback("Simulation 2 complete!")

        except Exception as e:
            self.status_callback(f"Error: {str(e)}")
            messagebox.showerror("Simulation Error", str(e))

    def _display_sim2_results(self, params: Dict):
        """Display Simulation 2 results."""
        for widget in self.sim2_tables_frame.winfo_children():
            widget.destroy()

        if self.sim2_result is None:
            return

        # Summary
        self._build_summary_table(self.sim2_tables_frame, self.sim2_result, "200m Summary")

        # Power breakdown
        self._build_power_breakdown(self.sim2_tables_frame, self.sim2_result, params)

    # =========================================================================
    # DELTA PANEL
    # =========================================================================

    def _build_delta_panel(self):
        """Build the delta comparison panel."""
        frame = self.delta_container.scrollable

        # Header
        ttk.Label(frame, text="DELTA", font=('Segoe UI', 11, 'bold')).pack(pady=5)

        # Summary deltas
        self.delta_summary_frame = ttk.LabelFrame(frame, text="Summary Δ", padding=5)
        self.delta_summary_frame.pack(fill="x", padx=5, pady=5)

        # Power breakdown deltas
        self.delta_breakdown_frame = ttk.LabelFrame(frame, text="Power Δ", padding=5)
        self.delta_breakdown_frame.pack(fill="x", padx=5, pady=5)

        # Initial message
        ttk.Label(
            self.delta_summary_frame,
            text="Run both simulations\nto see comparison",
            foreground='#6B7280'
        ).pack()

    def _update_delta_display(self):
        """Update delta panel with comparison between Sim 1 and Sim 2."""
        # Clear previous
        for w in self.delta_summary_frame.winfo_children():
            w.destroy()
        for w in self.delta_breakdown_frame.winfo_children():
            w.destroy()

        if self.sim1_result is None or self.sim2_result is None:
            ttk.Label(
                self.delta_summary_frame,
                text="Run both simulations\nto see comparison",
                foreground='#6B7280'
            ).pack()
            return

        # Calculate and display deltas
        deltas = [
            ("Δ 200m Time", self.sim2_result.T_200 - self.sim1_result.T_200, "ms", 1000),
            ("Δ Total Time", self.sim2_result.T_total - self.sim1_result.T_total, "ms", 1000),
            ("Δ Entry v", (self.sim2_result.v_200_entry - self.sim1_result.v_200_entry) * 3.6, "km/h", 1),
            ("Δ Exit v", (self.sim2_result.v_200_exit - self.sim1_result.v_200_exit) * 3.6, "km/h", 1),
            ("Δ Avg P", self.sim2_result.P_avg_sprint - self.sim1_result.P_avg_sprint, "W", 1),
            ("Δ Line Cost", (self.sim2_result.line_cost_200 - self.sim1_result.line_cost_200) * 1000, "ms", 1),
        ]

        for row, (label, value, unit, scale) in enumerate(deltas):
            # Color: green if faster (negative time delta), red if slower
            if "Time" in label or "Line Cost" in label:
                color = '#059669' if value < -0.001 else '#DC2626' if value > 0.001 else '#6B7280'
            else:
                # For speed/power, positive is generally better
                color = '#059669' if value > 0.001 else '#DC2626' if value < -0.001 else '#6B7280'

            sign = "+" if value > 0 else ""
            scaled_value = value * scale
            if abs(scaled_value) >= 0.1:
                text = f"{sign}{scaled_value:.1f} {unit}"
            else:
                text = f"~0 {unit}"

            ttk.Label(self.delta_summary_frame, text=label, font=('Segoe UI', 8)).grid(
                row=row, column=0, sticky="w", padx=2, pady=1
            )
            ttk.Label(self.delta_summary_frame, text=text, foreground=color, font=('Segoe UI', 8, 'bold')).grid(
                row=row, column=1, sticky="e", padx=2, pady=1
            )

        # Power breakdown deltas
        self._build_power_breakdown_delta()

    def _build_power_breakdown_delta(self):
        """Build power breakdown delta display."""
        if self.sim1_result is None or self.sim2_result is None:
            return

        # Calculate power breakdowns for both
        def calc_power_breakdown(result):
            s_200_start = 695.0
            mask_200 = result.s_grid >= s_200_start
            dt_200 = result.dt[mask_200]
            total_time = np.sum(dt_200) if np.sum(dt_200) > 0 else 1

            return {
                'P_aero': np.sum(result.W_aero[mask_200]) / total_time,
                'P_rr': np.sum(result.W_rr[mask_200]) / total_time,
                'P_pot': np.sum(result.dE_pot[mask_200]) / total_time,
                'P_kin': np.sum(result.dE_kin[mask_200]) / total_time,
            }

        pb1 = calc_power_breakdown(self.sim1_result)
        pb2 = calc_power_breakdown(self.sim2_result)

        breakdown_deltas = [
            ("Δ Aero", pb2['P_aero'] - pb1['P_aero']),
            ("Δ RR", pb2['P_rr'] - pb1['P_rr']),
            ("Δ Elev", pb2['P_pot'] - pb1['P_pot']),
            ("Δ Accel", pb2['P_kin'] - pb1['P_kin']),
        ]

        for row, (label, value) in enumerate(breakdown_deltas):
            # Less power loss is better (negative delta = improvement)
            color = '#059669' if value < -0.5 else '#DC2626' if value > 0.5 else '#6B7280'
            sign = "+" if value > 0 else ""
            text = f"{sign}{value:.0f} W" if abs(value) >= 1 else "~0 W"

            ttk.Label(self.delta_breakdown_frame, text=label, font=('Segoe UI', 8)).grid(
                row=row, column=0, sticky="w", padx=2, pady=1
            )
            ttk.Label(self.delta_breakdown_frame, text=text, foreground=color, font=('Segoe UI', 8)).grid(
                row=row, column=1, sticky="e", padx=2, pady=1
            )

    # =========================================================================
    # SHARED COMPONENTS
    # =========================================================================

    def _build_summary_table(self, parent: ttk.Frame, result, title: str):
        """Build a summary table for a simulation result."""
        summary_frame = ttk.LabelFrame(parent, text=title, padding=3)
        summary_frame.pack(fill="x", pady=2)

        line_cost = result.line_cost_200
        if line_cost > 0.001:
            line_cost_str = f"+{line_cost*1000:.1f}ms"
        elif line_cost < -0.001:
            line_cost_str = f"{line_cost*1000:.1f}ms"
        else:
            line_cost_str = "0ms"

        summary_text = (
            f"200m: {result.T_200:.3f}s | Total: {result.T_total:.3f}s\n"
            f"Entry: {result.v_200_entry * 3.6:.1f} | Exit: {result.v_200_exit * 3.6:.1f} km/h\n"
            f"Avg P: {result.P_avg_sprint:.0f}W | Line: {line_cost_str}"
        )

        ttk.Label(summary_frame, text=summary_text, font=('Consolas', 8)).pack()

    def _build_power_breakdown(self, parent: ttk.Frame, result, params: Dict):
        """Build power breakdown table."""
        s_200_start = 695.0
        mask_200 = result.s_grid >= s_200_start
        dt_200 = result.dt[mask_200]
        total_time_200 = np.sum(dt_200) if np.sum(dt_200) > 0 else 1

        P_aero_avg = np.sum(result.W_aero[mask_200]) / total_time_200
        P_rr_avg = np.sum(result.W_rr[mask_200]) / total_time_200
        P_pot_avg = np.sum(result.dE_pot[mask_200]) / total_time_200
        P_kin_avg = np.sum(result.dE_kin[mask_200]) / total_time_200
        P_eff_avg = np.mean(result.P_eff[mask_200])

        breakdown_frame = ttk.LabelFrame(parent, text="Power (200m)", padding=3)
        breakdown_frame.pack(fill="x", pady=2)

        rows = [
            ("Pedal", f"{P_eff_avg:.0f}W"),
            ("Aero", f"{P_aero_avg:.0f}W"),
            ("RR", f"{P_rr_avg:.0f}W"),
            ("Elev", f"{P_pot_avg:.0f}W"),
            ("Accel", f"{P_kin_avg:.0f}W"),
        ]

        for row_idx, (label, value) in enumerate(rows):
            ttk.Label(breakdown_frame, text=label, font=('Segoe UI', 8)).grid(
                row=row_idx, column=0, padx=2, pady=1, sticky="w"
            )
            ttk.Label(breakdown_frame, text=value, font=('Segoe UI', 8)).grid(
                row=row_idx, column=1, padx=2, pady=1, sticky="e"
            )

    def _update_chart(self):
        """Update the comparison chart with both simulation results."""
        self.chart_canvas.clear()

        if self.sim1_result is None:
            return

        track = self.session.track or BROMONT_250M

        def get_seg_name(s):
            return get_segment_name(s, track)

        data_source = self.session.header_text

        # Use comparison chart if both results exist
        if self.sim2_result is not None:
            # Convert SimulationResult objects to dicts for chart function
            sim1_dict = {
                'v': self.sim1_result.v,
                'P_eff': self.sim1_result.P_eff,
                'CdA': self.sim1_result.CdA,
                'T_200': self.sim1_result.T_200,
            }
            sim2_dict = {
                'v': self.sim2_result.v,
                'P_eff': self.sim2_result.P_eff,
                'CdA': self.sim2_result.CdA,
                'T_200': self.sim2_result.T_200,
            }
            fig = create_comparison_chart(
                self.s_grid,
                sim1_dict,
                sim2_dict,
                data_source=data_source,
                get_segment_func=get_seg_name,
            )
        else:
            # Just Sim 1
            fig = create_combined_chart(
                self.s_grid,
                {
                    'v': self.sim1_result.v,
                    'P_eff': self.sim1_result.P_eff,
                    'CdA': self.sim1_result.CdA,
                },
                data_source=data_source,
                get_segment_func=get_seg_name,
            )

        self.chart_canvas.show_figure(fig)
