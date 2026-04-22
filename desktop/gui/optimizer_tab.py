"""
Flying 200 V2 - Optimizer Tab

Energy budget optimization interface with:
- Clear parameter controls
- Progress display
- Results with segment labels
- Position recommendations
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable, Dict
import numpy as np
import threading
import sys
import os
from dataclasses import asdict

# Handle imports for both direct and package execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from core.session import Session
from core.physics import (
    simulate_profile, SimulationConfig, S_OFFSET, theta_track_blackline,
    compute_theta_for_track, compute_track_params_from_geometry,
)
from optimizer.energy_budget import EnergyBudgetOptimizer, OptimizationResult
from optimizer.power_redistribution import PowerRedistributionOptimizer, RedistributionResult
from charts import ChartCanvas, COLORS


# =============================================================================
# Simulation Wrapper for Optimizers
# =============================================================================

def create_simulation_wrapper(config: SimulationConfig, track_geometry=None):
    """
    Create a simulation wrapper function compatible with the optimizers.

    The optimizers expect: simulate_func(y, CdA, P, params, s_grid, theta_grid, label)
    This wrapper calls the actual simulate_profile function and returns a dict.

    Args:
        config: SimulationConfig with default parameters
        track_geometry: Optional TrackGeometry object for track-specific physics
    """
    def sim_func(y_grid, CdA_grid, P_grid, params, s_grid, theta_grid, label=""):
        """Wrapper function that calls simulate_profile and returns a dict."""
        # Create a config from params (or use the captured config)
        sim_config = SimulationConfig(
            mass_kg=params.get('M', config.mass_kg),
            rho_kg_m3=params.get('rho', config.rho_kg_m3),
            c_rr=params.get('C_RR', config.c_rr),
            v0_m_s=params.get('V0', config.v0_m_s),
            ds_m=params.get('DS', config.ds_m),
            drivetrain_efficiency=params.get('drivetrain_eff', config.drivetrain_efficiency),
        )

        # Run simulation with optional track geometry
        result = simulate_profile(
            s_grid, y_grid, CdA_grid, P_grid, sim_config,
            track_geometry=track_geometry
        )

        # Convert SimulationResult dataclass to dict for optimizer compatibility
        return {
            's': result.s_grid,
            'v': result.v,
            't': result.t,
            'dt': result.dt,
            'y': result.y,
            'CdA': result.CdA,
            'P_eff': result.P_eff,
            'T_total': result.T_total,
            'T_200': result.T_200,
            'v_200_entry': result.v_200_entry,
            'v_200_exit': result.v_200_exit,
            'T_sprint': result.T_sprint,
            'P_avg_sprint': result.P_avg_sprint,
            'theta': result.theta,
        }

    return sim_func


# =============================================================================
# Optimizer Tab
# =============================================================================

class OptimizerTab:
    """
    Optimizer tab for energy budget optimization.

    Features:
    - Primary optimizer (EnergyBudget) with clear controls
    - Advanced mode (PowerRedistribution)
    - Progress tracking
    - Results with segment-labeled output
    """

    def __init__(
        self,
        parent: ttk.Frame,
        session: Session,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize optimizer tab.

        Args:
            parent: Parent frame
            session: Session object
            status_callback: Status update callback
        """
        self.parent = parent
        self.session = session
        self.status_callback = status_callback or (lambda x: None)

        # Optimization state
        self.optimizer = None
        self.result: Optional[OptimizationResult] = None
        self.redistrib_result: Optional[RedistributionResult] = None
        self.is_running = False
        self.stop_requested = False

        # Simulation parameters (defaults)
        self.sim_params = {
            'M': 92.0,
            'rho': 1.1627,
            'C_RR': 0.0020,
            'V0': 5.0,
            'DS': 0.25,
            'drivetrain_eff': 0.98,
            'S_TOTAL': 895.0,
        }

        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build the optimizer tab UI."""
        # Left panel: Controls
        left_panel = ttk.Frame(self.parent, width=380)
        left_panel.pack(side="left", fill="y", padx=5, pady=5)
        left_panel.pack_propagate(False)

        # Right panel: Results
        right_panel = ttk.Frame(self.parent)
        right_panel.pack(side="right", fill="both", expand=True, padx=5, pady=5)

        self._build_controls(left_panel)
        self._build_results(right_panel)

    def _build_controls(self, parent: ttk.Frame):
        """Build control panel."""
        # === Data Status ===
        status_frame = ttk.LabelFrame(parent, text="Data Status", padding=5)
        status_frame.pack(fill="x", pady=5)

        self.status_var = tk.StringVar(value="Checking...")
        ttk.Label(status_frame, textvariable=self.status_var, wraplength=350).pack(fill="x")
        ttk.Button(status_frame, text="Refresh Status", command=self._update_status).pack(pady=2)

        # Initial status check
        self.parent.after(100, self._update_status)

        # === Mode Selection ===
        mode_frame = ttk.LabelFrame(parent, text="Optimization Mode", padding=5)
        mode_frame.pack(fill="x", pady=5)

        self.mode_var = tk.StringVar(value="energy_budget")
        self.mode_var.trace_add('write', lambda *args: self._on_mode_changed())
        ttk.Radiobutton(
            mode_frame, text="Energy Budget (Recommended)",
            variable=self.mode_var, value="energy_budget"
        ).pack(anchor="w")
        ttk.Radiobutton(
            mode_frame, text="Power Redistribution (Advanced)",
            variable=self.mode_var, value="redistribution"
        ).pack(anchor="w")

        # === Simulation Parameters ===
        sim_frame = ttk.LabelFrame(parent, text="Simulation Parameters", padding=5)
        sim_frame.pack(fill="x", pady=5)

        # Row 0: Track selection with altitude
        row_sim0 = ttk.Frame(sim_frame)
        row_sim0.pack(fill="x", pady=2)
        ttk.Label(row_sim0, text="Track:").pack(side="left", padx=5)
        self.opt_track_var = tk.StringVar(value="Bromont")
        from core.track import AVAILABLE_TRACKS, get_track_rho
        track_combo = ttk.Combobox(
            row_sim0, textvariable=self.opt_track_var,
            values=list(AVAILABLE_TRACKS.keys()),
            state="readonly", width=10
        )
        track_combo.pack(side="left", padx=5)
        track_combo.bind("<<ComboboxSelected>>", self._on_opt_track_changed)

        row_sim1 = ttk.Frame(sim_frame)
        row_sim1.pack(fill="x", pady=2)
        ttk.Label(row_sim1, text="Mass (kg):").pack(side="left", padx=5)
        self.mass_var = tk.StringVar(value="92.0")
        ttk.Entry(row_sim1, textvariable=self.mass_var, width=8).pack(side="left", padx=5)

        ttk.Label(row_sim1, text="Rho (kg/m3):").pack(side="left", padx=5)
        self.rho_var = tk.StringVar(value="1.2010")  # Bromont default
        ttk.Entry(row_sim1, textvariable=self.rho_var, width=8).pack(side="left", padx=5)

        # Altitude correction button
        ttk.Button(row_sim1, text="↻ Alt", width=5, command=self._apply_opt_altitude_correction).pack(side="left", padx=5)

        # Row for environmental conditions
        row_sim1b = ttk.Frame(sim_frame)
        row_sim1b.pack(fill="x", pady=2)
        ttk.Label(row_sim1b, text="Temp (°C):").pack(side="left", padx=5)
        self.opt_temp_var = tk.StringVar(value="20.0")
        ttk.Entry(row_sim1b, textvariable=self.opt_temp_var, width=5).pack(side="left", padx=2)

        ttk.Label(row_sim1b, text="Humidity (%):").pack(side="left", padx=5)
        self.opt_humidity_var = tk.StringVar(value="50")
        ttk.Entry(row_sim1b, textvariable=self.opt_humidity_var, width=4).pack(side="left", padx=2)

        ttk.Label(row_sim1b, text="Baro (hPa):").pack(side="left", padx=5)
        self.opt_baro_var = tk.StringVar(value="989")  # Bromont default
        ttk.Entry(row_sim1b, textvariable=self.opt_baro_var, width=5).pack(side="left", padx=2)

        ttk.Button(row_sim1b, text="Calc ρ", width=5, command=self._calc_opt_rho_from_conditions).pack(side="left", padx=5)

        row_sim2 = ttk.Frame(sim_frame)
        row_sim2.pack(fill="x", pady=2)
        ttk.Label(row_sim2, text="CdA Seated:").pack(side="left", padx=5)
        self.cda_seated_var = tk.StringVar(value="0.24")
        ttk.Entry(row_sim2, textvariable=self.cda_seated_var, width=8).pack(side="left", padx=5)

        ttk.Label(row_sim2, text="CdA Standing:").pack(side="left", padx=5)
        self.cda_standing_var = tk.StringVar(value="0.38")
        ttk.Entry(row_sim2, textvariable=self.cda_standing_var, width=8).pack(side="left", padx=5)

        # === Optimizer Parameters ===
        params_frame = ttk.LabelFrame(parent, text="Optimizer Parameters", padding=5)
        params_frame.pack(fill="x", pady=5)

        # Store widget references for enable/disable
        self._param_widgets = {}

        # Energy budget (Energy Budget only)
        row1 = ttk.Frame(params_frame)
        row1.pack(fill="x", pady=2)
        lbl1 = ttk.Label(row1, text="Energy Budget (J):")
        lbl1.pack(side="left", padx=5)
        self.energy_var = tk.StringVar(value="25000")
        ent1 = ttk.Entry(row1, textvariable=self.energy_var, width=10)
        ent1.pack(side="left", padx=5)
        self._param_widgets['energy_budget'] = (lbl1, ent1)

        # Optimization start (both)
        row2 = ttk.Frame(params_frame)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Opt Start (m):").pack(side="left", padx=5)
        self.opt_start_var = tk.StringVar(value="480")
        ttk.Entry(row2, textvariable=self.opt_start_var, width=10).pack(side="left", padx=5)

        # Segment mode (Redistribution only)
        row_segmode = ttk.Frame(params_frame)
        row_segmode.pack(fill="x", pady=2)
        lbl_segmode = ttk.Label(row_segmode, text="Segment Mode:")
        lbl_segmode.pack(side="left", padx=5)
        self.seg_mode_var = tk.StringVar(value="fixed")
        self.seg_mode_var.trace_add('write', lambda *args: self._on_seg_mode_changed())
        seg_mode_combo = ttk.Combobox(
            row_segmode, textvariable=self.seg_mode_var, width=14,
            values=["fixed", "track_section"], state="readonly"
        )
        seg_mode_combo.pack(side="left", padx=5)
        self._param_widgets['seg_mode'] = (lbl_segmode, seg_mode_combo)

        # Segment length (both, but only used when seg_mode=fixed)
        row3 = ttk.Frame(params_frame)
        row3.pack(fill="x", pady=2)
        lbl3 = ttk.Label(row3, text="Segment Length (m):")
        lbl3.pack(side="left", padx=5)
        self.seg_len_var = tk.StringVar(value="50")
        ent3 = ttk.Entry(row3, textvariable=self.seg_len_var, width=10)
        ent3.pack(side="left", padx=5)
        self._param_widgets['seg_length'] = (lbl3, ent3)

        # Number of samples (both)
        row4 = ttk.Frame(params_frame)
        row4.pack(fill="x", pady=2)
        ttk.Label(row4, text="Samples:").pack(side="left", padx=5)
        self.samples_var = tk.StringVar(value="500")
        ttk.Entry(row4, textvariable=self.samples_var, width=10).pack(side="left", padx=5)

        # Min power fraction (both)
        row5 = ttk.Frame(params_frame)
        row5.pack(fill="x", pady=2)
        ttk.Label(row5, text="Min Power (%):").pack(side="left", padx=5)
        self.min_power_var = tk.StringVar(value="90")
        ttk.Entry(row5, textvariable=self.min_power_var, width=10).pack(side="left", padx=5)

        # Energy levels (Energy Budget only)
        row6 = ttk.Frame(params_frame)
        row6.pack(fill="x", pady=2)
        lbl6 = ttk.Label(row6, text="Energy Levels:")
        lbl6.pack(side="left", padx=5)
        self.energy_levels_var = tk.StringVar(value="10")
        ent6 = ttk.Entry(row6, textvariable=self.energy_levels_var, width=10)
        ent6.pack(side="left", padx=5)
        self._param_widgets['energy_levels'] = (lbl6, ent6)

        # Min standing distance (Energy Budget only)
        row7 = ttk.Frame(params_frame)
        row7.pack(fill="x", pady=2)
        lbl7 = ttk.Label(row7, text="Min Standing (m):")
        lbl7.pack(side="left", padx=5)
        self.min_standing_var = tk.StringVar(value="50")
        ent7 = ttk.Entry(row7, textvariable=self.min_standing_var, width=10)
        ent7.pack(side="left", padx=5)
        self._param_widgets['min_standing'] = (lbl7, ent7)

        # Smoothing (Energy Budget only)
        row8 = ttk.Frame(params_frame)
        row8.pack(fill="x", pady=2)
        lbl8 = ttk.Label(row8, text="Smoothing (m):")
        lbl8.pack(side="left", padx=5)
        self.smoothing_var = tk.StringVar(value="50")
        ent8 = ttk.Entry(row8, textvariable=self.smoothing_var, width=10)
        ent8.pack(side="left", padx=5)
        self._param_widgets['smoothing'] = (lbl8, ent8)

        # Max adjustment (Redistribution only)
        row_maxadj = ttk.Frame(params_frame)
        row_maxadj.pack(fill="x", pady=2)
        lbl_maxadj = ttk.Label(row_maxadj, text="Max Adjust (W):")
        lbl_maxadj.pack(side="left", padx=5)
        self.max_adjust_var = tk.StringVar(value="100")
        ent_maxadj = ttk.Entry(row_maxadj, textvariable=self.max_adjust_var, width=10)
        ent_maxadj.pack(side="left", padx=5)
        self._param_widgets['max_adjust'] = (lbl_maxadj, ent_maxadj)

        # Power increment (Redistribution only)
        row_increment = ttk.Frame(params_frame)
        row_increment.pack(fill="x", pady=2)
        lbl_incr = ttk.Label(row_increment, text="Power Step (W):")
        lbl_incr.pack(side="left", padx=5)
        self.power_increment_var = tk.StringVar(value="10")
        ent_incr = ttk.Entry(row_increment, textvariable=self.power_increment_var, width=10)
        ent_incr.pack(side="left", padx=5)
        self._param_widgets['power_increment'] = (lbl_incr, ent_incr)

        # Timed section mode (Energy Budget only)
        self.timed_frame = ttk.LabelFrame(params_frame, text="Timed 200m Mode", padding=5)
        self.timed_frame.pack(fill="x", pady=5)

        self.timed_mode_var = tk.StringVar(value="FLATOUT")
        self.timed_rb1 = ttk.Radiobutton(
            self.timed_frame, text="FLATOUT (max power curve)",
            variable=self.timed_mode_var, value="FLATOUT"
        )
        self.timed_rb1.pack(anchor="w")
        self.timed_rb2 = ttk.Radiobutton(
            self.timed_frame, text="OPT (optimize allocation)",
            variable=self.timed_mode_var, value="OPT"
        )
        self.timed_rb2.pack(anchor="w")

        # Search space indicator
        self.search_space_var = tk.StringVar(value="Configure parameters to see search space")
        ttk.Label(params_frame, textvariable=self.search_space_var, foreground="blue").pack(anchor="w", pady=2)

        # Bind parameter updates to search space calculation
        for var in [self.opt_start_var, self.seg_len_var, self.energy_levels_var,
                    self.min_standing_var, self.samples_var]:
            var.trace_add('write', lambda *args: self._update_search_space())

        # === Progress ===
        progress_frame = ttk.LabelFrame(parent, text="Progress", padding=5)
        progress_frame.pack(fill="x", pady=5)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var,
            maximum=100, mode='determinate'
        )
        self.progress_bar.pack(fill="x", pady=2)

        self.progress_label = ttk.Label(progress_frame, text="Ready")
        self.progress_label.pack(fill="x")

        # === Actions ===
        actions_frame = ttk.Frame(parent)
        actions_frame.pack(fill="x", pady=10)

        self.run_btn = ttk.Button(actions_frame, text="Run Optimization", command=self._run_optimization)
        self.run_btn.pack(fill="x", pady=2)

        self.stop_btn = ttk.Button(actions_frame, text="Stop", command=self._stop_optimization, state="disabled")
        self.stop_btn.pack(fill="x", pady=2)

        self.export_btn = ttk.Button(actions_frame, text="Export Optimized Profile", command=self._export_profile, state="disabled")
        self.export_btn.pack(fill="x", pady=2)

        self.export_diag_btn = ttk.Button(actions_frame, text="Export Diagnostics", command=self._export_diagnostics, state="disabled")
        self.export_diag_btn.pack(fill="x", pady=2)

        # Initialize parameter enable/disable state
        self.parent.after(200, self._on_mode_changed)

    def _build_results(self, parent: ttk.Frame):
        """Build results panel."""
        # Use notebook for results tabs
        results_notebook = ttk.Notebook(parent)
        results_notebook.pack(fill="both", expand=True)

        # === Tab 1: Summary ===
        summary_tab = ttk.Frame(results_notebook)
        results_notebook.add(summary_tab, text="Summary")

        # Results text
        text_frame = ttk.LabelFrame(summary_tab, text="Results Summary", padding=5)
        text_frame.pack(fill="x", pady=5)

        self.results_text = tk.Text(text_frame, height=10, font=('Consolas', 9))
        self.results_text.pack(fill="x", pady=2)
        self.results_text.insert("1.0", "Run optimization to see results.\n\nRequirements:\n- Load a profile (FIT Analysis or CSV)\n- Power curves are optional but recommended")
        self.results_text.config(state="disabled")

        # Chart in summary tab
        chart_frame = ttk.LabelFrame(summary_tab, text="Power Allocation", padding=5)
        chart_frame.pack(fill="both", expand=True, pady=5)

        self.chart_canvas = ChartCanvas(chart_frame)

        # === Tab 2: Recommendations (clear action items) ===
        rec_tab = ttk.Frame(results_notebook)
        results_notebook.add(rec_tab, text="★ Recommendations")

        # Create recommendations treeview
        rec_columns = ('segment', 'position', 'power_baseline', 'power_opt', 'delta_power', 'action')
        self.rec_tree = ttk.Treeview(rec_tab, columns=rec_columns, show='headings', height=15)

        self.rec_tree.heading('segment', text='Segment')
        self.rec_tree.heading('position', text='Position')
        self.rec_tree.heading('power_baseline', text='Baseline (W)')
        self.rec_tree.heading('power_opt', text='Optimal (W)')
        self.rec_tree.heading('delta_power', text='Change (W)')
        self.rec_tree.heading('action', text='Action')

        self.rec_tree.column('segment', width=120, anchor='w')
        self.rec_tree.column('position', width=80, anchor='center')
        self.rec_tree.column('power_baseline', width=100, anchor='center')
        self.rec_tree.column('power_opt', width=100, anchor='center')
        self.rec_tree.column('delta_power', width=90, anchor='center')
        self.rec_tree.column('action', width=200, anchor='w')

        rec_scroll = ttk.Scrollbar(rec_tab, orient='vertical', command=self.rec_tree.yview)
        self.rec_tree.configure(yscrollcommand=rec_scroll.set)

        self.rec_tree.pack(side='left', fill='both', expand=True)
        rec_scroll.pack(side='right', fill='y')

        # === Tab 3: Detail Table (10m segments) ===
        table_tab = ttk.Frame(results_notebook)
        results_notebook.add(table_tab, text="Detail Table")

        # Treeview for detail table
        columns = ('s_m', 'v_kmh', 'P_W', 'CdA', 'W/CdA', 'BE_W/CdA', 'Ratio')
        self.detail_tree = ttk.Treeview(table_tab, columns=columns, show='headings', height=20)

        # Column headings
        self.detail_tree.heading('s_m', text='Dist (m)')
        self.detail_tree.heading('v_kmh', text='Speed (km/h)')
        self.detail_tree.heading('P_W', text='Power (W)')
        self.detail_tree.heading('CdA', text='CdA (m²)')
        self.detail_tree.heading('W/CdA', text='W/CdA')
        self.detail_tree.heading('BE_W/CdA', text='Breakeven')
        self.detail_tree.heading('Ratio', text='Ratio')

        # Column widths
        self.detail_tree.column('s_m', width=70, anchor='center')
        self.detail_tree.column('v_kmh', width=90, anchor='center')
        self.detail_tree.column('P_W', width=80, anchor='center')
        self.detail_tree.column('CdA', width=70, anchor='center')
        self.detail_tree.column('W/CdA', width=80, anchor='center')
        self.detail_tree.column('BE_W/CdA', width=80, anchor='center')
        self.detail_tree.column('Ratio', width=70, anchor='center')

        # Scrollbar
        tree_scroll = ttk.Scrollbar(table_tab, orient='vertical', command=self.detail_tree.yview)
        self.detail_tree.configure(yscrollcommand=tree_scroll.set)

        self.detail_tree.pack(side='left', fill='both', expand=True)
        tree_scroll.pack(side='right', fill='y')

        # === Tab 3: Time Delta Waterfall ===
        waterfall_tab = ttk.Frame(results_notebook)
        results_notebook.add(waterfall_tab, text="Time Delta")

        self.waterfall_chart_canvas = ChartCanvas(waterfall_tab)

        # === Tab 4: V1-Style Comparison (Speed/Power vs Baseline) ===
        comparison_tab = ttk.Frame(results_notebook)
        results_notebook.add(comparison_tab, text="Comparison")

        self.comparison_chart_canvas = ChartCanvas(comparison_tab)

        # === Tab 5: W/CdA Graphs ===
        graph_tab = ttk.Frame(results_notebook)
        results_notebook.add(graph_tab, text="W/CdA Analysis")

        self.wcda_chart_canvas = ChartCanvas(graph_tab)

        # === Tab 6: Position Timeline (V1-style sit/stand visual) ===
        position_tab = ttk.Frame(results_notebook)
        results_notebook.add(position_tab, text="Position Profile")

        self.position_chart_canvas = ChartCanvas(position_tab)

        # === Tab 7: Power vs Curve Limits ===
        curve_limits_tab = ttk.Frame(results_notebook)
        results_notebook.add(curve_limits_tab, text="Power Limits")

        self.curve_limits_chart_canvas = ChartCanvas(curve_limits_tab)

        # === Tab 8: Section Bar Chart ===
        section_bar_tab = ttk.Frame(results_notebook)
        results_notebook.add(section_bar_tab, text="Section Bars")

        self.section_bar_chart_canvas = ChartCanvas(section_bar_tab)

    def _on_mode_changed(self):
        """Enable/disable parameters based on selected optimizer mode."""
        mode = self.mode_var.get()

        # Define which parameters belong to which mode
        energy_budget_only = ['energy_budget', 'energy_levels', 'min_standing', 'smoothing']
        redistribution_only = ['seg_mode', 'max_adjust', 'power_increment']

        # Enable/disable for Energy Budget mode
        for key in energy_budget_only:
            if key in self._param_widgets:
                for widget in self._param_widgets[key]:
                    try:
                        if mode == 'energy_budget':
                            widget.config(state='normal')
                        else:
                            widget.config(state='disabled')
                    except tk.TclError:
                        pass

        # Enable/disable for Redistribution mode
        for key in redistribution_only:
            if key in self._param_widgets:
                for widget in self._param_widgets[key]:
                    try:
                        if mode == 'redistribution':
                            if isinstance(widget, ttk.Combobox):
                                widget.config(state='readonly')
                            else:
                                widget.config(state='normal')
                        else:
                            widget.config(state='disabled')
                    except tk.TclError:
                        pass

        # Timed 200m Mode frame (Energy Budget only)
        try:
            if mode == 'energy_budget':
                self.timed_rb1.config(state='normal')
                self.timed_rb2.config(state='normal')
            else:
                self.timed_rb1.config(state='disabled')
                self.timed_rb2.config(state='disabled')
        except (tk.TclError, AttributeError):
            pass

        # Segment length - for redistribution, only enabled when seg_mode is 'fixed'
        if mode == 'redistribution':
            seg_mode = self.seg_mode_var.get()
            if 'seg_length' in self._param_widgets:
                for widget in self._param_widgets['seg_length']:
                    try:
                        if seg_mode == 'fixed':
                            widget.config(state='normal')
                        else:
                            widget.config(state='disabled')
                    except tk.TclError:
                        pass

        # Update search space indicator
        self._update_search_space()

    def _on_seg_mode_changed(self):
        """Handle segment mode change for redistribution optimizer."""
        if self.mode_var.get() != 'redistribution':
            return

        seg_mode = self.seg_mode_var.get()
        if 'seg_length' in self._param_widgets:
            for widget in self._param_widgets['seg_length']:
                try:
                    if seg_mode == 'fixed':
                        widget.config(state='normal')
                    else:
                        widget.config(state='disabled')
                except tk.TclError:
                    pass

    def _update_status(self):
        """Update the data status display."""
        status_parts = []

        # Check profile
        if self.session.profile is not None:
            profile = self.session.profile
            y_min, y_max = profile.y_m.min(), profile.y_m.max()
            status_parts.append(f"Profile: {profile.source} ({len(profile.s_m)} pts)")
            if y_min == 0 and y_max == 0:
                status_parts.append("  WARNING: y_m all zeros (track position)")
        else:
            status_parts.append("Profile: NOT LOADED")

        # Check power curves
        if self.session.power_curves is not None:
            pc = self.session.power_curves
            status_parts.append(f"Power Curves: {pc.source_description}")
        else:
            status_parts.append("Power Curves: Not configured (will use defaults)")

        self.status_var.set("\n".join(status_parts))

    def _update_search_space(self):
        """Update search space indicator based on current parameters."""
        try:
            opt_start = float(self.opt_start_var.get())
            seg_len = float(self.seg_len_var.get())
            energy_levels = int(self.energy_levels_var.get())
            samples = int(self.samples_var.get())
            timed_start = 695.0

            # Calculate number of segments
            if self.timed_mode_var.get() == "FLATOUT":
                total_dist = timed_start - opt_start
            else:
                total_dist = timed_start + 200.0 - opt_start

            n_segments = max(1, int(np.ceil(total_dist / seg_len)))

            # Calculate permutations (simplified version)
            # Each segment can have 1 to energy_levels units of energy
            from math import comb
            if n_segments > 0 and energy_levels > 0:
                n_energy_combos = comb(n_segments + energy_levels - 1, n_segments - 1)
            else:
                n_energy_combos = 1

            # Format for display
            if n_energy_combos < 1000:
                combos_str = str(n_energy_combos)
            elif n_energy_combos < 1_000_000:
                combos_str = f"{n_energy_combos/1000:.1f}K"
            else:
                combos_str = f"{n_energy_combos/1_000_000:.1f}M"

            self.search_space_var.set(
                f"{n_segments} segments × {combos_str} combos, sampling {samples}"
            )
        except (ValueError, TypeError):
            self.search_space_var.set("Invalid parameters")

    def _get_params(self) -> Dict:
        """Get optimization parameters."""
        return {
            'energy_budget_J': float(self.energy_var.get()),
            'opt_start_m': float(self.opt_start_var.get()),
            'segment_length_m': float(self.seg_len_var.get()),
            'n_samples': int(self.samples_var.get()),
            'min_power_fraction': float(self.min_power_var.get()) / 100.0,
            'flatout_mode': self.timed_mode_var.get() == "FLATOUT",
            'energy_levels': int(self.energy_levels_var.get()),
            'min_standing_m': float(self.min_standing_var.get()),
            'smoothing_m': float(self.smoothing_var.get()),
        }

    def _get_sim_params(self) -> Dict:
        """Get simulation parameters.

        Uses session's stored params if available to ensure consistency
        with Simulation tab baseline.
        """
        # Start with UI values for mass/rho (user can override)
        params = {
            'M': float(self.mass_var.get()),
            'rho': float(self.rho_var.get()),
        }

        # Use session params for other values if available (ensures consistency)
        session_params = self.session.last_simulation_params or {}

        params['C_RR'] = session_params.get('C_RR', 0.0020)
        params['V0'] = session_params.get('V0', 5.0)
        params['DS'] = session_params.get('DS', 0.25)
        params['drivetrain_eff'] = session_params.get('drivetrain_eff', 0.98)
        params['S_TOTAL'] = session_params.get('S_TOTAL', 895.0)
        params['cda_bend_factor'] = session_params.get('cda_bend_factor', 1.0)

        return params

    def _on_opt_track_changed(self, event=None):
        """Handle optimizer track selection change."""
        from core.track import AVAILABLE_TRACKS, BROMONT_250M, get_standard_pressure_at_altitude
        track_name = self.opt_track_var.get()
        track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)
        # Sync session so simulate_profile uses correct track geometry
        self.session.track = track
        # Update default barometric pressure for the track altitude
        std_pressure = get_standard_pressure_at_altitude(track.altitude_m)
        self.opt_baro_var.set(f"{std_pressure:.0f}")
        self._apply_opt_altitude_correction()

    def _apply_opt_altitude_correction(self):
        """Apply altitude-based air density correction for the optimizer."""
        from core.track import AVAILABLE_TRACKS, BROMONT_250M, get_track_rho
        track_name = self.opt_track_var.get()
        track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)
        rho = get_track_rho(track)
        self.rho_var.set(f"{rho:.4f}")
        self.status_callback(f"Rho set to {rho:.4f} kg/m³ ({track_name} altitude: {track.altitude_m:.0f}m)")

    def _calc_opt_rho_from_conditions(self):
        """Calculate rho from temperature, humidity, and barometric pressure."""
        from tkinter import messagebox
        from core.track import rho_from_conditions
        try:
            temp_c = float(self.opt_temp_var.get())
            humidity_pct = float(self.opt_humidity_var.get())
            pressure_hpa = float(self.opt_baro_var.get())

            rho = rho_from_conditions(temp_c, humidity_pct, pressure_hpa)
            self.rho_var.set(f"{rho:.4f}")
            self.status_callback(
                f"Rho = {rho:.4f} kg/m³ (T={temp_c:.1f}°C, RH={humidity_pct:.0f}%, P={pressure_hpa:.0f}hPa)"
            )
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please enter valid numeric values.\n{str(e)}")

    def _run_optimization(self):
        """Start optimization in background thread."""
        if self.is_running:
            return

        # Validate session has profile data
        if self.session.profile is None:
            messagebox.showwarning(
                "No Profile",
                "No profile loaded.\n\n"
                "Please load a profile from:\n"
                "- FIT Analysis tab (export to session), or\n"
                "- Simulation tab (load CSV)"
            )
            return

        self.is_running = True
        self.stop_requested = False
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

        # Run in background thread
        thread = threading.Thread(target=self._optimization_thread, daemon=True)
        thread.start()

    def _optimization_thread(self):
        """Background optimization thread."""
        try:
            params = self._get_params()
            sim_params = self._get_sim_params()
            mode = self.mode_var.get()

            self._update_progress(0, "Preparing data...")

            # Get profile data
            profile = self.session.profile
            s_total = sim_params['S_TOTAL']
            ds = sim_params['DS']

            # Build grids
            s_grid = np.arange(0.0, s_total + ds, ds)

            # Interpolate profile to grid
            y_grid = np.interp(s_grid, profile.s_m, profile.y_m)
            CdA_grid = np.interp(s_grid, profile.s_m, profile.CdA_m2)
            P_grid = np.interp(s_grid, profile.s_m, profile.P_W)

            # Resolve track geometry early (needed for theta_grid and simulation)
            # Use session track first, fall back to optimizer dropdown selection
            from core.track import AVAILABLE_TRACKS, BROMONT_250M
            track_geometry = self.session.track
            if track_geometry is None:
                opt_track_name = self.opt_track_var.get()
                track_geometry = AVAILABLE_TRACKS.get(opt_track_name)
            self.session.track = track_geometry  # ensure session is in sync

            # Scale y_grid to track width (profile may come from a different-width track)
            if track_geometry is not None:
                from core.track import scale_y_to_track_width
                y_grid = scale_y_to_track_width(y_grid, track_geometry.width_m)

            # Create theta grid from track geometry (recalculated for active track)
            if track_geometry is not None:
                tp = compute_track_params_from_geometry(track_geometry)
                theta_grid = compute_theta_for_track(
                    s_grid,
                    tp['straight_length'],
                    tp['lap_length'],
                    tp['theta_straight_rad'],
                    tp['theta_bend_rad'],
                )
            else:
                theta_grid = np.array([theta_track_blackline(s + S_OFFSET) for s in s_grid])

            # Get CdA values
            cda_seated = float(self.cda_seated_var.get())
            cda_standing = float(self.cda_standing_var.get())

            # Create CdA arrays
            CdA_seated_arr = np.full_like(s_grid, cda_seated)
            CdA_standing_arr = np.full_like(s_grid, cda_standing)

            # Power curves - use session if available, otherwise config defaults
            if self.session.power_curves is not None:
                pc = self.session.power_curves
                power_curve_seated = pc.seated.to_dict()
                power_curve_standing = pc.standing.to_dict()
                power_source = "session"
            else:
                # Use config defaults (no more hidden hardcoded values)
                from core.config import get_default_power_curves, BUILTIN_DEFAULTS
                config_power = get_default_power_curves()
                if config_power:
                    power_curve_seated = {int(k): v for k, v in config_power.get("seated", {}).items()}
                    power_curve_standing = {int(k): v for k, v in config_power.get("standing", {}).items()}
                    power_source = "config defaults"
                else:
                    # Fallback to builtin if config load fails
                    power_curve_seated = BUILTIN_DEFAULTS["power_curves"]["seated"]
                    power_curve_standing = BUILTIN_DEFAULTS["power_curves"]["standing"]
                    power_source = "builtin defaults"

            # Create simulation config and wrapper with track-specific physics
            config = SimulationConfig(
                mass_kg=sim_params['M'],
                rho_kg_m3=sim_params['rho'],
                c_rr=sim_params['C_RR'],
                v0_m_s=sim_params['V0'],
                ds_m=sim_params['DS'],
                drivetrain_efficiency=sim_params['drivetrain_eff'],
                cda_bend_factor=sim_params.get('cda_bend_factor', 1.0),
            )
            # Create simulation wrapper with track-specific physics
            sim_func = create_simulation_wrapper(config, track_geometry=track_geometry)

            # Check if we can use session baseline (from Simulation tab)
            use_session_baseline = False
            mismatch_reason = ""
            if self.session.last_simulation_result is not None:
                # Check if params match reasonably
                session_params = self.session.last_simulation_params or {}

                mass_ok = abs(session_params.get('M', 0) - sim_params['M']) < 0.5
                rho_ok = abs(session_params.get('rho', 0) - sim_params['rho']) < 0.05
                track_ok = session_params.get('track_name', '') == (track_geometry.name if track_geometry else '')
                # Check other physics params that affect results
                crr_ok = abs(session_params.get('C_RR', 0.002) - sim_params['C_RR']) < 0.0001
                eff_ok = abs(session_params.get('drivetrain_eff', 0.98) - sim_params['drivetrain_eff']) < 0.01
                cda_factor_ok = abs(session_params.get('cda_bend_factor', 1.0) - sim_params.get('cda_bend_factor', 1.0)) < 0.01

                if mass_ok and rho_ok and track_ok and crr_ok and eff_ok and cda_factor_ok:
                    use_session_baseline = True
                else:
                    # Build mismatch reason for debugging
                    reasons = []
                    if not mass_ok:
                        reasons.append(f"mass: {session_params.get('M', 0):.1f} vs {sim_params['M']:.1f}")
                    if not rho_ok:
                        reasons.append(f"rho: {session_params.get('rho', 0):.4f} vs {sim_params['rho']:.4f}")
                    if not track_ok:
                        reasons.append(f"track: {session_params.get('track_name', 'None')} vs {track_geometry.name if track_geometry else 'None'}")
                    if not crr_ok:
                        reasons.append(f"C_RR: {session_params.get('C_RR', 0):.4f} vs {sim_params['C_RR']:.4f}")
                    if not eff_ok:
                        reasons.append(f"eff: {session_params.get('drivetrain_eff', 0):.2f} vs {sim_params['drivetrain_eff']:.2f}")
                    if not cda_factor_ok:
                        reasons.append(f"cda_bend: {session_params.get('cda_bend_factor', 1.0):.2f} vs {sim_params.get('cda_bend_factor', 1.0):.2f}")
                    mismatch_reason = ", ".join(reasons)
            else:
                mismatch_reason = "no simulation result in session"

            if use_session_baseline:
                self._update_progress(5, f"Using Simulation Tab baseline (T_200={self.session.last_simulation_result['T_200']:.3f}s)...")
                baseline_result = self.session.last_simulation_result
            else:
                self._update_progress(5, f"Running own baseline ({mismatch_reason})...")
                # Run baseline simulation
                baseline_result = sim_func(y_grid, CdA_grid, P_grid, sim_params, s_grid, theta_grid, "baseline")

            if mode == "energy_budget":
                self._run_energy_budget_optimization(
                    params, sim_params, sim_func, s_grid, theta_grid, y_grid,
                    CdA_seated_arr, CdA_standing_arr, P_grid,
                    power_curve_seated, power_curve_standing, baseline_result
                )
            else:
                self._run_redistribution_optimization(
                    params, sim_params, sim_func, s_grid, theta_grid, y_grid,
                    CdA_grid, P_grid, power_curve_seated, baseline_result
                )

        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n\n{traceback.format_exc()}"
            self.parent.after(0, lambda: messagebox.showerror("Error", error_msg))

        finally:
            self.is_running = False
            self.parent.after(0, self._reset_buttons)

    def _run_energy_budget_optimization(
        self, params, sim_params, sim_func, s_grid, theta_grid, y_grid,
        CdA_seated_arr, CdA_standing_arr, P_baseline,
        power_curve_seated, power_curve_standing, baseline_result
    ):
        """Run energy budget optimization."""
        self._update_progress(10, "Creating Energy Budget optimizer...")

        optimizer = EnergyBudgetOptimizer(
            simulate_func=sim_func,
            params=sim_params,
            s_grid=s_grid,
            theta_grid=theta_grid,
            y_grid=y_grid,
            CdA_standing=CdA_standing_arr,
            CdA_seated=CdA_seated_arr,
            P_baseline=P_baseline,
            power_curve_seated=power_curve_seated,
            power_curve_standing=power_curve_standing,
            total_energy_budget_J=params['energy_budget_J'],
            optimization_start_m=params['opt_start_m'],
            timed_zone_start_m=695.0,
            segment_length_m=params['segment_length_m'],
            min_power_fraction=params['min_power_fraction'],
            flatout_mode=params['flatout_mode'],
        )

        n_samples = params['n_samples']
        energy_levels = params.get('energy_levels', 10)

        def progress_callback(iteration, total, best_time):
            pct = 10 + (iteration / total) * 85
            self._update_progress(pct, f"Iteration {iteration}/{total} | Best: {best_time:.3f}s")

        def stop_check():
            return self.stop_requested

        self._update_progress(15, f"Running optimization ({n_samples} samples, {energy_levels} levels)...")

        result = optimizer.optimize(
            n_samples=n_samples,
            energy_levels=energy_levels,
            progress_callback=progress_callback,
            stop_check=stop_check,
            baseline_result=baseline_result,
        )

        self._update_progress(100, "Optimization complete!")

        # Display result on main thread
        self.parent.after(0, lambda: self._display_energy_budget_result(result, baseline_result))

    def _run_redistribution_optimization(
        self, params, sim_params, sim_func, s_grid, theta_grid, y_grid,
        CdA_grid, P_baseline, power_curve_seated, baseline_result
    ):
        """Run power redistribution optimization."""
        self._update_progress(10, "Creating Power Redistribution optimizer...")

        # Create power curve function for constraint checking
        def power_curve_func(elapsed_time_s):
            durations = sorted(power_curve_seated.keys())
            powers = [power_curve_seated[d] for d in durations]
            return float(np.interp(elapsed_time_s, durations, powers))

        optimizer = PowerRedistributionOptimizer(
            simulate_func=sim_func,
            params=sim_params,
            s_grid=s_grid,
            theta_grid=theta_grid,
            y_grid=y_grid,
            CdA_grid=CdA_grid,
            P_baseline=P_baseline,
            optimization_start_m=params['opt_start_m'],
            finish_m=895.0,
            segment_mode=self.seg_mode_var.get(),
            segment_length_m=params['segment_length_m'],
            power_increment_W=float(self.power_increment_var.get()),
            max_adjustment_W=float(self.max_adjust_var.get()),
            min_power_fraction=params['min_power_fraction'],
            power_curve_func=power_curve_func,
            track_geometry=self.session.track if self.session.track else None,
        )

        # Set baseline result - store for later use in waterfall chart
        optimizer.baseline_result = baseline_result
        optimizer.baseline_time = baseline_result.get('T_200', float('inf'))
        self._redistrib_baseline = baseline_result  # Store for waterfall chart

        n_samples = params['n_samples']

        def progress_callback(iteration, total, best_time):
            pct = 10 + (iteration / total) * 85
            self._update_progress(pct, f"Iteration {iteration}/{total} | Best: {best_time:.3f}s")

        def stop_check():
            return self.stop_requested

        self._update_progress(15, f"Running redistribution ({n_samples} samples)...")

        result = optimizer.optimize_random(
            n_samples=n_samples,
            progress_callback=progress_callback,
            stop_check=stop_check,
        )

        self._update_progress(100, "Optimization complete!")

        # Display result on main thread
        self.parent.after(0, lambda: self._display_redistribution_result(result))

    def _update_progress(self, pct: float, message: str):
        """Update progress display (thread-safe)."""
        def update():
            self.progress_var.set(pct)
            self.progress_label.config(text=message)

        self.parent.after(0, update)

    def _reset_buttons(self):
        """Reset button states."""
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _stop_optimization(self):
        """Request optimization stop."""
        self.stop_requested = True
        self.progress_label.config(text="Stopping...")

    def _display_energy_budget_result(self, result: OptimizationResult, baseline_result: dict):
        """Display energy budget optimization result."""
        self.result = result

        # Update results text
        self.results_text.config(state="normal")
        self.results_text.delete("1.0", tk.END)

        baseline_time = baseline_result.get('T_200', 0)
        improvement = (baseline_time - result.best_time_s) * 1000 if result.success else 0

        summary = result.get_summary()
        summary += f"\n\nBaseline Time: {baseline_time:.3f}s"
        summary += f"\nImprovement: {improvement:.1f}ms"

        self.results_text.insert("1.0", summary)
        self.results_text.config(state="disabled")

        # Enable export buttons
        if result.success:
            self.export_btn.config(state="normal")
            self.export_diag_btn.config(state="normal")

        # Update chart
        if result.success and result.segment_summary:
            self._draw_energy_chart(result)
            self._populate_recommendations_table(result, baseline_result)
            self._draw_v1_comparison_inline(result, baseline_result)
            self._draw_time_delta_waterfall(result, baseline_result)
            self._populate_detail_table(result)
            self._draw_wcda_chart(result)

            # V1-style charts
            self._draw_position_timeline(result, baseline_result)
            self._draw_power_curve_limits(result, baseline_result)
            self._draw_section_bar_chart(result, baseline_result)

            # Store optimized line in session for Track View overlay
            self._store_optimized_line(result, baseline_result)

    def _display_redistribution_result(self, result: RedistributionResult):
        """Display power redistribution result."""
        self.redistrib_result = result

        # Update results text
        self.results_text.config(state="normal")
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert("1.0", result.get_summary())
        self.results_text.config(state="disabled")

        # Enable export buttons
        if result.success:
            self.export_btn.config(state="normal")
            self.export_diag_btn.config(state="normal")

        # Update charts and table
        if result.success and result.segment_summary:
            self._draw_redistribution_chart(result)
            # For redistribution, baseline was stored during optimization
            if hasattr(self, '_redistrib_baseline') and self._redistrib_baseline:
                self._draw_v1_comparison_inline(result, self._redistrib_baseline)
                self._draw_time_delta_waterfall(result, self._redistrib_baseline)
                # V1-style charts (some may not apply to redistribution)
                self._draw_power_curve_limits(result, self._redistrib_baseline)
                self._draw_section_bar_chart(result, self._redistrib_baseline)
                # Store optimized line in session for Track View overlay
                self._store_optimized_line(result, self._redistrib_baseline)
            self._populate_detail_table_redistrib(result)
            self._draw_wcda_chart_redistrib(result)

    def _draw_energy_chart(self, result: OptimizationResult):
        """Draw energy allocation bar chart."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))

        segments = result.segment_summary
        positions = result.positions

        seg_names = [s['name'] for s in segments]
        energies = [s['energy_J'] for s in segments]
        colors = [COLORS.get('standing', '#EF4444') if i < len(positions) and positions[i] == 'standing'
                  else COLORS.get('seated', '#3B82F6') for i in range(len(segments))]

        bars = ax.bar(range(len(segments)), energies, color=colors, alpha=0.7)

        ax.set_xticks(range(len(segments)))
        ax.set_xticklabels(seg_names, rotation=45, ha='right', fontsize=8)
        ax.set_ylabel('Energy (J)')
        ax.set_title(f'Energy Allocation | Best Time: {result.best_time_s:.3f}s')
        ax.grid(True, alpha=0.3, axis='y')

        # Legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor=COLORS.get('standing', '#EF4444'), alpha=0.7, label='Standing'),
            Patch(facecolor=COLORS.get('seated', '#3B82F6'), alpha=0.7, label='Seated'),
        ]
        ax.legend(handles=legend_elements, loc='upper right')

        plt.tight_layout()
        self.chart_canvas.show_figure(fig)

    def _populate_recommendations_table(self, result: OptimizationResult, baseline_result: dict):
        """Populate the recommendations table with clear per-segment actions.

        Shows:
        - Segment name with lap and track segment (e.g., "L2 Turn3 @550m")
        - Recommended position (SEATED/STANDING)
        - Baseline power vs Optimal power
        - Power change
        - Clear action text
        """
        from core.track import get_segment_at_distance

        # Clear existing rows
        for item in self.rec_tree.get_children():
            self.rec_tree.delete(item)

        segments = result.segment_summary
        positions = result.positions

        if not segments:
            return

        # Get baseline power per segment from simulation
        baseline_P = baseline_result.get('P_eff', baseline_result.get('P', np.array([])))
        baseline_s = baseline_result.get('s', baseline_result.get('s_grid', np.array([])))

        # Get optimized power from result
        sim_result = result.simulation_result or {}
        opt_P = sim_result.get('P_eff', np.array([]))
        opt_s = sim_result.get('s', np.array([]))

        track = self.session.track

        for i, seg in enumerate(segments):
            seg_start = seg.get('start_m', 0)
            seg_end = seg.get('end_m', seg_start + 50)
            seg_mid = (seg_start + seg_end) / 2

            # Get proper segment name with lap info
            if track:
                lap_idx, track_seg, _ = get_segment_at_distance(seg_mid, track)
                # Format: "L2 Turn3 @550m" or "L3 Home @850m"
                seg_abbrev = track_seg.name.replace("Straight", "").replace("Turn", "T").strip()
                seg_name = f"L{lap_idx} {seg_abbrev} @{seg_start:.0f}m"
            else:
                seg_name = f"@{seg_start:.0f}-{seg_end:.0f}m"

            # Position
            position = positions[i] if i < len(positions) else 'seated'
            pos_display = 'STANDING' if position == 'standing' else 'Seated'

            # Get average power in this segment for baseline
            if len(baseline_s) > 0 and len(baseline_P) > 0:
                mask = (baseline_s >= seg_start) & (baseline_s < seg_end)
                baseline_power = baseline_P[mask].mean() if mask.any() else 0
            else:
                baseline_power = 0

            # Get average power in this segment for optimized
            if len(opt_s) > 0 and len(opt_P) > 0:
                mask = (opt_s >= seg_start) & (opt_s < seg_end)
                opt_power = opt_P[mask].mean() if mask.any() else seg.get('avg_power_W', 0)
            else:
                opt_power = seg.get('avg_power_W', 0)

            delta = opt_power - baseline_power

            # Create action text
            if position == 'standing':
                action = f"STAND, push {opt_power:.0f}W"
            else:
                action = f"Sit, hold {opt_power:.0f}W"

            if delta > 20:
                action += f" (+{delta:.0f}W more)"
            elif delta < -20:
                action += f" ({delta:.0f}W less)"

            # Add row with alternating colors
            tag = 'standing' if position == 'standing' else 'seated'
            self.rec_tree.insert('', 'end', values=(
                seg_name,
                pos_display,
                f'{baseline_power:.0f}' if baseline_power > 0 else '-',
                f'{opt_power:.0f}' if opt_power > 0 else '-',
                f'{delta:+.0f}' if baseline_power > 0 else '-',
                action
            ), tags=(tag,))

        # Configure tag colors
        self.rec_tree.tag_configure('standing', background='#FEE2E2')  # Light red
        self.rec_tree.tag_configure('seated', background='#DBEAFE')    # Light blue

    def _draw_comparison_chart(self, result: OptimizationResult, baseline_result: dict):
        """Draw V1-style comparison chart: optimized vs baseline speed and power.

        Shows:
        - Top: Speed profile (baseline vs optimized)
        - Bottom: Power profile (baseline vs optimized)
        With segment labels on x-axis.
        """
        import matplotlib.pyplot as plt
        from core.track import get_segment_name

        # Get simulation data
        sim_result = result.simulation_result
        if sim_result is None or not isinstance(sim_result, dict):
            return

        # Get arrays
        s_opt = sim_result.get('s', np.array([]))
        v_opt = sim_result.get('v', np.array([]))
        P_opt = sim_result.get('P_eff', np.array([]))

        s_base = baseline_result.get('s', baseline_result.get('s_grid', np.array([])))
        v_base = baseline_result.get('v', np.array([]))
        P_base = baseline_result.get('P_eff', np.array([]))

        if len(s_opt) == 0 or len(s_base) == 0:
            return

        # Focus on 200m section (s=695 to s=895)
        mask_opt = (s_opt >= 695) & (s_opt <= 895)
        mask_base = (s_base >= 695) & (s_base <= 895)

        s_opt_200 = s_opt[mask_opt]
        v_opt_200 = v_opt[mask_opt] * 3.6  # Convert to km/h
        P_opt_200 = P_opt[mask_opt]

        s_base_200 = s_base[mask_base]
        v_base_200 = v_base[mask_base] * 3.6
        P_base_200 = P_base[mask_base]

        # Create figure with 2 subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

        # Speed comparison
        ax1.plot(s_base_200, v_base_200, 'b-', linewidth=2, label='Baseline', alpha=0.7)
        ax1.plot(s_opt_200, v_opt_200, 'r-', linewidth=2, label='Optimized', alpha=0.9)
        ax1.set_ylabel('Speed (km/h)')
        ax1.set_title(f'Speed Comparison | Baseline: {baseline_result.get("T_200", 0):.3f}s → Optimized: {result.best_time_s:.3f}s')
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)

        # Fill between to show improvement
        if len(s_opt_200) == len(s_base_200):
            ax1.fill_between(s_opt_200, v_base_200, v_opt_200,
                           where=(v_opt_200 > v_base_200),
                           color='green', alpha=0.2, label='Faster')
            ax1.fill_between(s_opt_200, v_base_200, v_opt_200,
                           where=(v_opt_200 < v_base_200),
                           color='red', alpha=0.2, label='Slower')

        # Power comparison
        ax2.plot(s_base_200, P_base_200, 'b-', linewidth=2, label='Baseline', alpha=0.7)
        ax2.plot(s_opt_200, P_opt_200, 'r-', linewidth=2, label='Optimized', alpha=0.9)
        ax2.set_ylabel('Power (W)')
        ax2.set_xlabel('Distance (m)')
        ax2.legend(loc='upper right')
        ax2.grid(True, alpha=0.3)

        # Add segment markers
        track = self.session.track
        if track:
            segment_boundaries = [695, 745, 795, 845, 895]  # Approximate 50m segments
            for s_mark in segment_boundaries[1:-1]:
                ax1.axvline(x=s_mark, color='gray', linestyle='--', alpha=0.3)
                ax2.axvline(x=s_mark, color='gray', linestyle='--', alpha=0.3)

            # Add segment labels at bottom
            segment_mids = [(segment_boundaries[i] + segment_boundaries[i+1]) / 2
                          for i in range(len(segment_boundaries)-1)]
            for s_mid in segment_mids:
                seg_name = get_segment_name(s_mid, track, include_lap=False)
                ax2.text(s_mid, ax2.get_ylim()[0], seg_name,
                        ha='center', va='top', fontsize=7, color='#6B7280')

        plt.tight_layout()

        # Show in a new window (since main chart already has energy allocation)
        from charts import ChartCanvas
        if hasattr(self, 'comparison_window') and self.comparison_window:
            try:
                self.comparison_window.destroy()
            except:
                pass

        self.comparison_window = tk.Toplevel(self.parent)
        self.comparison_window.title("Baseline vs Optimized Comparison")
        self.comparison_window.geometry("800x500")

        comparison_canvas = ChartCanvas(self.comparison_window)
        comparison_canvas.show_figure(fig)

    def _draw_time_delta_waterfall(self, result, baseline_result: dict):
        """Draw segment-by-segment time delta waterfall chart.

        Shows exactly WHERE time is being gained or lost compared to baseline.
        This is the key insight chart for understanding optimization impact.

        Args:
            result: OptimizationResult or RedistributionResult
            baseline_result: Baseline simulation result dict
        """
        import matplotlib.pyplot as plt
        from core.track import get_segment_name

        # Get simulation data
        sim_result = result.simulation_result
        if sim_result is None or not isinstance(sim_result, dict):
            return

        # Get time arrays
        s_opt = sim_result.get('s', np.array([]))
        t_opt = sim_result.get('t', np.array([]))

        s_base = baseline_result.get('s', baseline_result.get('s_grid', np.array([])))
        t_base = baseline_result.get('t', np.array([]))

        if len(s_opt) == 0 or len(s_base) == 0 or len(t_opt) == 0 or len(t_base) == 0:
            return

        # Define segments for the FULL course (0m to 895m)
        # Using 50m segments for the full course
        segment_boundaries = list(range(0, 896, 50))  # [0, 50, 100, ..., 850]
        if segment_boundaries[-1] != 895:
            segment_boundaries.append(895)

        # Calculate time delta for each segment
        segment_names = []
        segment_deltas = []  # Positive = slower (lost time), Negative = faster (gained time)
        cumulative_delta = []

        track = self.session.track

        running_total = 0.0
        for i in range(len(segment_boundaries) - 1):
            s_start = segment_boundaries[i]
            s_end = segment_boundaries[i + 1]
            s_mid = (s_start + s_end) / 2

            # Get time at segment boundaries for baseline
            idx_base_start = np.abs(s_base - s_start).argmin()
            idx_base_end = np.abs(s_base - s_end).argmin()
            t_base_segment = t_base[idx_base_end] - t_base[idx_base_start]

            # Get time at segment boundaries for optimized
            idx_opt_start = np.abs(s_opt - s_start).argmin()
            idx_opt_end = np.abs(s_opt - s_end).argmin()
            t_opt_segment = t_opt[idx_opt_end] - t_opt[idx_opt_start]

            # Delta: positive = slower than baseline, negative = faster
            delta_ms = (t_opt_segment - t_base_segment) * 1000  # Convert to milliseconds

            # Get segment name
            if track:
                seg_name = get_segment_name(s_mid, track, include_lap=False)
            else:
                seg_name = f"{s_start:.0f}m"

            segment_names.append(seg_name)
            segment_deltas.append(delta_ms)
            running_total += delta_ms
            cumulative_delta.append(running_total)

        # Create figure with 2 subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), height_ratios=[2, 1])

        # Top: Waterfall bar chart
        x_pos = np.arange(len(segment_names))
        colors = ['#22C55E' if d < 0 else '#EF4444' for d in segment_deltas]

        bars = ax1.bar(x_pos, segment_deltas, color=colors, alpha=0.8, edgecolor='black', linewidth=0.5)

        # Add value labels on bars
        for i, (bar, delta) in enumerate(zip(bars, segment_deltas)):
            height = bar.get_height()
            label = f"{delta:+.1f}"
            va = 'bottom' if height >= 0 else 'top'
            offset = 0.5 if height >= 0 else -0.5
            ax1.text(bar.get_x() + bar.get_width()/2, height + offset, label,
                    ha='center', va=va, fontsize=8, fontweight='bold')

        ax1.set_xticks(x_pos)
        ax1.set_xticklabels(segment_names, rotation=45, ha='right', fontsize=9)
        ax1.set_ylabel('Time Delta (ms)')
        ax1.axhline(y=0, color='black', linestyle='-', linewidth=1)
        ax1.grid(True, alpha=0.3, axis='y')

        # Title with total improvement
        total_improvement = cumulative_delta[-1] if cumulative_delta else 0
        baseline_t200 = baseline_result.get('T_200', 0)
        opt_t200 = result.best_time_s if hasattr(result, 'best_time_s') else sim_result.get('T_200', 0)

        ax1.set_title(
            f'Time Delta by Segment (Full Course 0-895m)\n'
            f'T_200: {baseline_t200:.3f}s → {opt_t200:.3f}s | '
            f'Net: {total_improvement:+.1f}ms',
            fontsize=11, fontweight='bold'
        )

        # Mark 200m timed section (695m and 895m)
        # Find indices closest to 695m and 895m
        for target_m in [695, 895]:
            for i, name in enumerate(segment_names):
                if str(target_m) in name or (i > 0 and segment_boundaries[i] <= target_m < segment_boundaries[i+1]):
                    ax1.axvline(x=i, color='purple', linestyle='--', linewidth=1.5, alpha=0.7)

        # Add legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#22C55E', alpha=0.8, label='Time Gained (faster)'),
            Patch(facecolor='#EF4444', alpha=0.8, label='Time Lost (slower)'),
        ]
        ax1.legend(handles=legend_elements, loc='upper right')

        # Bottom: Cumulative time delta line
        ax2.plot(x_pos, cumulative_delta, 'b-o', linewidth=2, markersize=6)
        ax2.fill_between(x_pos, cumulative_delta, 0,
                        where=[c < 0 for c in cumulative_delta],
                        color='#22C55E', alpha=0.3)
        ax2.fill_between(x_pos, cumulative_delta, 0,
                        where=[c >= 0 for c in cumulative_delta],
                        color='#EF4444', alpha=0.3)

        ax2.set_xticks(x_pos)
        ax2.set_xticklabels(segment_names, rotation=45, ha='right', fontsize=9)
        ax2.set_ylabel('Cumulative Delta (ms)')
        ax2.set_xlabel('Track Position')
        ax2.axhline(y=0, color='black', linestyle='-', linewidth=1)
        ax2.grid(True, alpha=0.3)
        ax2.set_title('Cumulative Time Delta', fontsize=10)

        # Add final value annotation
        if cumulative_delta:
            ax2.annotate(f'{cumulative_delta[-1]:+.1f}ms',
                        xy=(x_pos[-1], cumulative_delta[-1]),
                        xytext=(10, 0), textcoords='offset points',
                        fontsize=10, fontweight='bold',
                        color='#22C55E' if cumulative_delta[-1] < 0 else '#EF4444')

        plt.tight_layout()
        self.waterfall_chart_canvas.show_figure(fig)

    def _draw_v1_comparison_inline(self, result, baseline_result: dict):
        """Draw V1-style comparison graphs inline in the Comparison tab.

        Shows:
        - Speed vs distance (baseline dashed, optimized solid)
        - Power vs distance (baseline dashed, optimized solid)
        - Time accumulation overlay

        This is the key visualization showing WHERE optimization makes a difference.
        """
        import matplotlib.pyplot as plt
        from core.track import get_segment_name

        # Get simulation data
        sim_result = result.simulation_result
        if sim_result is None or not isinstance(sim_result, dict):
            return

        # Get arrays - optimized
        s_opt = sim_result.get('s', sim_result.get('s_grid', np.array([])))
        v_opt = sim_result.get('v', np.array([]))
        P_opt = sim_result.get('P', sim_result.get('P_eff', np.array([])))
        t_opt = sim_result.get('t', np.array([]))

        # Get arrays - baseline
        s_base = baseline_result.get('s', baseline_result.get('s_grid', np.array([])))
        v_base = baseline_result.get('v', np.array([]))
        P_base = baseline_result.get('P', baseline_result.get('P_eff', np.array([])))
        t_base = baseline_result.get('t', np.array([]))

        if len(s_opt) == 0 or len(s_base) == 0:
            return

        # Show FULL course (0-895m), not just 200m section
        # Use all data points
        s_opt_full = s_opt
        v_opt_full = v_opt * 3.6  # Convert to km/h
        P_opt_full = P_opt if len(P_opt) > 0 else np.zeros_like(s_opt_full)
        t_opt_full = t_opt if len(t_opt) > 0 else np.zeros_like(s_opt_full)

        s_base_full = s_base
        v_base_full = v_base * 3.6  # Convert to km/h
        P_base_full = P_base if len(P_base) > 0 else np.zeros_like(s_base_full)
        t_base_full = t_base if len(t_base) > 0 else np.zeros_like(s_base_full)

        if len(s_opt_full) == 0 or len(s_base_full) == 0:
            return

        # Create figure with 3 subplots
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 9), sharex=True)

        # Get track for segment shading
        track = self.session.track

        # Helper to add segment shading
        def add_segment_shading(ax, s_arr):
            if track is None:
                return
            from core.track import get_segment_at_distance, get_segment_color
            current_seg = None
            seg_start = s_arr[0]
            for s in s_arr:
                _, segment, _ = get_segment_at_distance(s, track)
                if segment.name != current_seg:
                    if current_seg is not None:
                        color = get_segment_color(current_seg)
                        ax.axvspan(seg_start, s, alpha=0.15, color=color)
                    current_seg = segment.name
                    seg_start = s
            # Final segment
            if current_seg is not None:
                color = get_segment_color(current_seg)
                ax.axvspan(seg_start, s_arr[-1], alpha=0.15, color=color)

        # Helper to add 200m timed zone markers
        def add_timed_zone_markers(ax):
            ax.axvline(x=695, color='purple', linestyle='--', linewidth=1.5, alpha=0.7)
            ax.axvline(x=895, color='purple', linestyle='--', linewidth=1.5, alpha=0.7)

        # === Plot 1: Speed vs Distance ===
        add_segment_shading(ax1, s_opt_full)
        ax1.plot(s_base_full, v_base_full, 'b--', linewidth=1.5, alpha=0.7, label='Baseline')
        ax1.plot(s_opt_full, v_opt_full, 'b-', linewidth=2, label='Optimized')

        # Fill between to highlight difference
        v_base_interp = np.interp(s_opt_full, s_base_full, v_base_full)
        ax1.fill_between(s_opt_full, v_base_interp, v_opt_full,
                        where=(v_opt_full > v_base_interp),
                        color='#22C55E', alpha=0.3, label='Faster')
        ax1.fill_between(s_opt_full, v_base_interp, v_opt_full,
                        where=(v_opt_full <= v_base_interp),
                        color='#EF4444', alpha=0.3, label='Slower')

        ax1.set_ylabel('Speed (km/h)')
        ax1.legend(loc='upper right', fontsize=8)
        ax1.grid(True, alpha=0.3)
        add_timed_zone_markers(ax1)
        ax1.set_title('Speed Comparison (Full Course 0-895m)', fontsize=11, fontweight='bold')

        # === Plot 2: Power vs Distance ===
        if len(P_opt_full) > 0 and len(P_base_full) > 0 and P_opt_full.max() > 0:
            add_segment_shading(ax2, s_opt_full)
            ax2.plot(s_base_full, P_base_full, 'r--', linewidth=1.5, alpha=0.7, label='Baseline')
            ax2.plot(s_opt_full, P_opt_full, 'r-', linewidth=2, label='Optimized')

            # Fill between
            P_base_interp = np.interp(s_opt_full, s_base_full, P_base_full)
            ax2.fill_between(s_opt_full, P_base_interp, P_opt_full,
                            where=(P_opt_full > P_base_interp),
                            color='#F97316', alpha=0.3, label='Higher Power')
            ax2.fill_between(s_opt_full, P_base_interp, P_opt_full,
                            where=(P_opt_full <= P_base_interp),
                            color='#6366F1', alpha=0.3, label='Lower Power')

            ax2.set_ylabel('Power (W)')
            ax2.legend(loc='upper right', fontsize=8)
            ax2.grid(True, alpha=0.3)
            add_timed_zone_markers(ax2)
            ax2.set_title('Power Comparison', fontsize=10)

        # === Plot 3: Cumulative Time vs Distance ===
        if len(t_opt_full) > 0 and len(t_base_full) > 0:
            add_segment_shading(ax3, s_opt_full)

            # Time curves
            ax3.plot(s_base_full, t_base_full, 'g--', linewidth=1.5, alpha=0.7, label='Baseline')
            ax3.plot(s_opt_full, t_opt_full, 'g-', linewidth=2, label='Optimized')

            # Time delta on secondary axis
            ax3_twin = ax3.twinx()
            t_base_interp = np.interp(s_opt_full, s_base_full, t_base_full)
            time_delta_ms = (t_opt_full - t_base_interp) * 1000

            ax3_twin.plot(s_opt_full, time_delta_ms, 'purple', linewidth=1.5, alpha=0.8, label='Δt')
            ax3_twin.axhline(y=0, color='purple', linestyle=':', alpha=0.5)
            ax3_twin.set_ylabel('Time Delta (ms)', color='purple')
            ax3_twin.tick_params(axis='y', labelcolor='purple')

            # Fill based on whether we're ahead or behind
            ax3_twin.fill_between(s_opt_full, 0, time_delta_ms,
                                 where=(time_delta_ms < 0),
                                 color='#22C55E', alpha=0.2)
            ax3_twin.fill_between(s_opt_full, 0, time_delta_ms,
                                 where=(time_delta_ms >= 0),
                                 color='#EF4444', alpha=0.2)

            ax3.set_ylabel('Cumulative Time (s)')
            ax3.set_xlabel('Distance (m)')
            ax3.legend(loc='upper left', fontsize=8)
            ax3.grid(True, alpha=0.3)
            add_timed_zone_markers(ax3)

            # Final time annotation
            T_200_base = baseline_result.get('T_200', t_base_full[-1] if len(t_base_full) > 0 else 0)
            T_200_opt = result.best_time_s if hasattr(result, 'best_time_s') else t_opt_full[-1]
            improvement_ms = (T_200_base - T_200_opt) * 1000

            ax3.set_title(
                f'Time Accumulation | T_200: {T_200_base:.3f}s → {T_200_opt:.3f}s | '
                f'Improvement: {improvement_ms:+.0f}ms',
                fontsize=10
            )

        plt.tight_layout()
        self.comparison_chart_canvas.show_figure(fig)

    def _populate_detail_table(self, result: OptimizationResult):
        """Populate detail table with 10m segment W/CdA analysis."""
        from core.physics import (
            calculate_watts_per_cda, calculate_breakeven_watts_per_cda, RHO
        )

        # Clear existing rows
        for item in self.detail_tree.get_children():
            self.detail_tree.delete(item)

        sim_result = result.simulation_result
        if sim_result is None or (isinstance(sim_result, dict) and len(sim_result) == 0):
            # Insert a diagnostic row
            self.detail_tree.insert('', 'end', values=(
                'N/A', 'No simulation data available', '', '', '', '', ''
            ))
            return

        sim_params = self._get_sim_params()
        rho = sim_params.get('rho', RHO)

        # Get data arrays
        s_grid = sim_result.get('s', np.array([]))
        v = sim_result.get('v', np.array([]))
        P_eff = sim_result.get('P_eff', np.array([]))
        CdA = sim_result.get('CdA', np.array([]))

        # Check if arrays are empty
        if len(s_grid) == 0:
            self.detail_tree.insert('', 'end', values=(
                'N/A', f'Empty s_grid array (keys: {list(sim_result.keys())[:5]}...)', '', '', '', '', ''
            ))
            return

        # Build list of distances to sample: 10m intervals plus key distances (695, 895)
        sample_distances = set(np.arange(0, 900, 10))
        sample_distances.add(695)  # 200m start line
        sample_distances.add(895)  # Finish line
        sample_distances = sorted(sample_distances)

        # Configure tags for highlighting key distances
        self.detail_tree.tag_configure('start_line', background='#E3F2FD')  # Light blue
        self.detail_tree.tag_configure('finish_line', background='#C8E6C9')  # Light green

        for s_target in sample_distances:
            idx = np.abs(s_grid - s_target).argmin()
            if idx >= len(s_grid):
                continue

            s_m = s_grid[idx]
            v_ms = v[idx] if idx < len(v) else 0
            P_W = P_eff[idx] if idx < len(P_eff) else 0
            CdA_m2 = CdA[idx] if idx < len(CdA) else 0.25

            # Calculate metrics
            watts_per_cda = calculate_watts_per_cda(P_W, CdA_m2)
            breakeven_w_cda = calculate_breakeven_watts_per_cda(v_ms, rho)
            ratio = watts_per_cda / breakeven_w_cda if breakeven_w_cda > 0 else 0

            # Determine tag for highlighting
            tag = ()
            if abs(s_target - 695) < 1:
                tag = ('start_line',)
            elif abs(s_target - 895) < 1:
                tag = ('finish_line',)

            self.detail_tree.insert('', 'end', values=(
                f'{s_m:.0f}',
                f'{v_ms * 3.6:.1f}',
                f'{P_W:.0f}',
                f'{CdA_m2:.3f}',
                f'{watts_per_cda:.0f}',
                f'{breakeven_w_cda:.0f}',
                f'{ratio:.2f}'
            ), tags=tag)

    def _draw_wcda_chart(self, result: OptimizationResult):
        """Draw W/CdA analysis chart with breakeven line."""
        import matplotlib.pyplot as plt
        from core.physics import (
            calculate_watts_per_cda, calculate_breakeven_watts_per_cda, RHO
        )

        sim_result = result.simulation_result
        if sim_result is None:
            return

        sim_params = self._get_sim_params()
        rho = sim_params.get('rho', RHO)

        # Get data arrays
        s_grid = sim_result.get('s', np.array([]))
        v = sim_result.get('v', np.array([]))
        P_eff = sim_result.get('P_eff', np.array([]))
        CdA = sim_result.get('CdA', np.array([]))

        if len(s_grid) == 0:
            return

        # Calculate W/CdA and breakeven at each point
        wcda_values = []
        breakeven_values = []
        distances = []

        for i in range(0, len(s_grid), 4):  # Sample every 4th point (~1m)
            s_m = s_grid[i]
            v_ms = v[i] if i < len(v) else 0
            P_W = P_eff[i] if i < len(P_eff) else 0
            CdA_m2 = CdA[i] if i < len(CdA) else 0.25

            wcda = calculate_watts_per_cda(P_W, CdA_m2)
            be_wcda = calculate_breakeven_watts_per_cda(v_ms, rho)

            distances.append(s_m)
            wcda_values.append(wcda)
            breakeven_values.append(be_wcda)

        # Create figure with 2 subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

        # Top plot: W/CdA vs Breakeven
        ax1.fill_between(distances, wcda_values, breakeven_values,
                         where=[w > b for w, b in zip(wcda_values, breakeven_values)],
                         color='#22C55E', alpha=0.3, label='Above breakeven (accelerating)')
        ax1.fill_between(distances, wcda_values, breakeven_values,
                         where=[w <= b for w, b in zip(wcda_values, breakeven_values)],
                         color='#EF4444', alpha=0.3, label='Below breakeven (decelerating)')
        ax1.plot(distances, wcda_values, color='#3B82F6', linewidth=2, label='Actual W/CdA')
        ax1.plot(distances, breakeven_values, color='#EF4444', linewidth=2, linestyle='--', label='Breakeven W/CdA')

        ax1.set_ylabel('W/CdA (W/m²)')
        ax1.set_title(f'W/CdA Analysis | Best Time: {result.best_time_s:.3f}s')
        ax1.legend(loc='upper right', fontsize=8)
        ax1.grid(True, alpha=0.3)

        # Add timed zone marker
        ax1.axvline(x=695, color='orange', linestyle=':', alpha=0.7, label='200m Line')
        ax1.axvline(x=895, color='orange', linestyle=':', alpha=0.7)

        # Bottom plot: Ratio (efficiency)
        ratios = [w / b if b > 0 else 0 for w, b in zip(wcda_values, breakeven_values)]
        ax2.fill_between(distances, ratios, 1.0,
                         where=[r > 1.0 for r in ratios],
                         color='#22C55E', alpha=0.3)
        ax2.fill_between(distances, ratios, 1.0,
                         where=[r <= 1.0 for r in ratios],
                         color='#EF4444', alpha=0.3)
        ax2.plot(distances, ratios, color='#3B82F6', linewidth=2)
        ax2.axhline(y=1.0, color='#EF4444', linestyle='--', linewidth=1.5, label='Breakeven (ratio=1)')
        ax2.axvline(x=695, color='orange', linestyle=':', alpha=0.7)
        ax2.axvline(x=895, color='orange', linestyle=':', alpha=0.7)

        ax2.set_xlabel('Distance (m)')
        ax2.set_ylabel('Efficiency Ratio')
        ax2.set_title('Efficiency Ratio (W/CdA ÷ Breakeven)')
        ax2.legend(loc='upper right', fontsize=8)
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim([0, max(ratios) * 1.1 if ratios else 2])

        plt.tight_layout()
        self.wcda_chart_canvas.show_figure(fig)

    def _draw_redistribution_chart(self, result: RedistributionResult):
        """Draw power redistribution bar chart."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))

        segments = result.segment_summary
        seg_names = [s['name'] for s in segments]
        adjustments = [s['adjustment_W'] for s in segments]

        colors = ['#22C55E' if adj >= 0 else '#EF4444' for adj in adjustments]

        bars = ax.bar(range(len(segments)), adjustments, color=colors, alpha=0.7)

        ax.set_xticks(range(len(segments)))
        ax.set_xticklabels(seg_names, rotation=45, ha='right', fontsize=8)
        ax.set_ylabel('Power Adjustment (W)')
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax.set_title(f'Power Redistribution | Improvement: {result.improvement_ms:.1f}ms')
        ax.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()
        self.chart_canvas.show_figure(fig)

    def _populate_detail_table_redistrib(self, result: RedistributionResult):
        """Populate detail table for redistribution results."""
        from core.physics import (
            calculate_watts_per_cda, calculate_breakeven_watts_per_cda, RHO
        )

        # Clear existing rows
        for item in self.detail_tree.get_children():
            self.detail_tree.delete(item)

        sim_result = result.simulation_result
        if sim_result is None or (isinstance(sim_result, dict) and len(sim_result) == 0):
            self.detail_tree.insert('', 'end', values=(
                'N/A', 'No simulation data available', '', '', '', '', ''
            ))
            return

        sim_params = self._get_sim_params()
        rho = sim_params.get('rho', RHO)

        # Get data arrays
        s_grid = sim_result.get('s', np.array([]))
        v = sim_result.get('v', np.array([]))
        P_eff = sim_result.get('P_eff', np.array([]))
        CdA = sim_result.get('CdA', np.array([]))

        if len(s_grid) == 0:
            self.detail_tree.insert('', 'end', values=(
                'N/A', f'Empty s_grid (keys: {list(sim_result.keys())[:5]})', '', '', '', '', ''
            ))
            return

        # Build list of distances to sample: 10m intervals plus key distances (695, 895)
        sample_distances = set(np.arange(0, 900, 10))
        sample_distances.add(695)  # 200m start line
        sample_distances.add(895)  # Finish line
        sample_distances = sorted(sample_distances)

        # Configure tags for highlighting key distances
        self.detail_tree.tag_configure('start_line', background='#E3F2FD')  # Light blue
        self.detail_tree.tag_configure('finish_line', background='#C8E6C9')  # Light green

        for s_target in sample_distances:
            idx = np.abs(s_grid - s_target).argmin()
            if idx >= len(s_grid):
                continue

            s_m = s_grid[idx]
            v_ms = v[idx] if idx < len(v) else 0
            P_W = P_eff[idx] if idx < len(P_eff) else 0
            CdA_m2 = CdA[idx] if idx < len(CdA) else 0.25

            # Calculate metrics
            watts_per_cda = calculate_watts_per_cda(P_W, CdA_m2)
            breakeven_w_cda = calculate_breakeven_watts_per_cda(v_ms, rho)
            ratio = watts_per_cda / breakeven_w_cda if breakeven_w_cda > 0 else 0

            # Determine tag for highlighting
            tag = ()
            if abs(s_target - 695) < 1:
                tag = ('start_line',)
            elif abs(s_target - 895) < 1:
                tag = ('finish_line',)

            self.detail_tree.insert('', 'end', values=(
                f'{s_m:.0f}',
                f'{v_ms * 3.6:.1f}',
                f'{P_W:.0f}',
                f'{CdA_m2:.3f}',
                f'{watts_per_cda:.0f}',
                f'{breakeven_w_cda:.0f}',
                f'{ratio:.2f}'
            ), tags=tag)

    def _draw_wcda_chart_redistrib(self, result: RedistributionResult):
        """Draw W/CdA analysis chart for redistribution results."""
        import matplotlib.pyplot as plt
        from core.physics import (
            calculate_watts_per_cda, calculate_breakeven_watts_per_cda, RHO
        )

        sim_result = result.simulation_result
        if sim_result is None or (isinstance(sim_result, dict) and len(sim_result) == 0):
            return

        sim_params = self._get_sim_params()
        rho = sim_params.get('rho', RHO)

        # Get data arrays
        s_grid = sim_result.get('s', np.array([]))
        v = sim_result.get('v', np.array([]))
        P_eff = sim_result.get('P_eff', np.array([]))
        CdA = sim_result.get('CdA', np.array([]))

        if len(s_grid) == 0:
            return

        # Calculate W/CdA and breakeven at each point
        wcda_values = []
        breakeven_values = []
        distances = []

        for i in range(0, len(s_grid), 4):  # Sample every 4th point (~1m)
            s_m = s_grid[i]
            v_ms = v[i] if i < len(v) else 0
            P_W = P_eff[i] if i < len(P_eff) else 0
            CdA_m2 = CdA[i] if i < len(CdA) else 0.25

            wcda = calculate_watts_per_cda(P_W, CdA_m2)
            be_wcda = calculate_breakeven_watts_per_cda(v_ms, rho)

            distances.append(s_m)
            wcda_values.append(wcda)
            breakeven_values.append(be_wcda)

        # Create figure with 2 subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

        # Top plot: W/CdA vs Breakeven
        ax1.fill_between(distances, wcda_values, breakeven_values,
                         where=[w > b for w, b in zip(wcda_values, breakeven_values)],
                         color='#22C55E', alpha=0.3, label='Above breakeven (accelerating)')
        ax1.fill_between(distances, wcda_values, breakeven_values,
                         where=[w <= b for w, b in zip(wcda_values, breakeven_values)],
                         color='#EF4444', alpha=0.3, label='Below breakeven (decelerating)')
        ax1.plot(distances, wcda_values, color='#3B82F6', linewidth=2, label='Actual W/CdA')
        ax1.plot(distances, breakeven_values, color='#EF4444', linewidth=2, linestyle='--', label='Breakeven W/CdA')

        ax1.set_ylabel('W/CdA (W/m²)')
        ax1.set_title(f'W/CdA Analysis | Best Time: {result.best_time_s:.3f}s | Improvement: {result.improvement_ms:.1f}ms')
        ax1.legend(loc='upper right', fontsize=8)
        ax1.grid(True, alpha=0.3)

        # Add timed zone markers
        ax1.axvline(x=695, color='orange', linestyle=':', alpha=0.7, label='200m Line')
        ax1.axvline(x=895, color='orange', linestyle=':', alpha=0.7)

        # Bottom plot: Ratio (efficiency)
        ratios = [w / b if b > 0 else 0 for w, b in zip(wcda_values, breakeven_values)]
        ax2.fill_between(distances, ratios, 1.0,
                         where=[r > 1.0 for r in ratios],
                         color='#22C55E', alpha=0.3)
        ax2.fill_between(distances, ratios, 1.0,
                         where=[r <= 1.0 for r in ratios],
                         color='#EF4444', alpha=0.3)
        ax2.plot(distances, ratios, color='#3B82F6', linewidth=2)
        ax2.axhline(y=1.0, color='#EF4444', linestyle='--', linewidth=1.5, label='Breakeven (ratio=1)')
        ax2.axvline(x=695, color='orange', linestyle=':', alpha=0.7)
        ax2.axvline(x=895, color='orange', linestyle=':', alpha=0.7)

        ax2.set_xlabel('Distance (m)')
        ax2.set_ylabel('Efficiency Ratio')
        ax2.set_title('Efficiency Ratio (W/CdA ÷ Breakeven)')
        ax2.legend(loc='upper right', fontsize=8)
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim([0, max(ratios) * 1.1 if ratios else 2])

        plt.tight_layout()
        self.wcda_chart_canvas.show_figure(fig)

    def _store_optimized_line(self, result, baseline_result: dict):
        """Store the optimized y_m trajectory in session for Track View overlay.

        Args:
            result: OptimizationResult or RedistributionResult
            baseline_result: Baseline simulation result dict
        """
        sim_result = result.simulation_result
        if sim_result is None or not isinstance(sim_result, dict):
            return

        # Get optimized y_m
        s_opt = sim_result.get('s', sim_result.get('s_grid', np.array([])))
        y_opt = sim_result.get('y', np.array([]))

        if len(s_opt) == 0 or len(y_opt) == 0:
            return

        # Calculate improvement in milliseconds
        baseline_t200 = baseline_result.get('T_200', 0)
        opt_t200 = result.best_time_s if hasattr(result, 'best_time_s') else sim_result.get('T_200', 0)
        improvement_ms = (baseline_t200 - opt_t200) * 1000

        # Scale y_m to track bounds
        track = self.session.track
        if track is not None:
            from core.track import scale_y_to_track_width
            y_opt = scale_y_to_track_width(y_opt, track.width_m)

        # Store in session
        self.session.set_optimized_line(s_opt, y_opt, improvement_ms)
        self.status_callback(f"Optimized line stored ({improvement_ms:+.1f}ms) - view in Track Tab")

    def _export_profile(self):
        """Export optimized power profile to CSV."""
        from tkinter import filedialog
        import pandas as pd

        # Handle both energy budget and redistribution results
        result = self.result if self.result else self.redistrib_result
        if result is None or not result.success:
            messagebox.showwarning("No Results", "Run optimization first")
            return

        filepath = filedialog.asksaveasfilename(
            title="Export Optimized Profile",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not filepath:
            return

        try:
            sim_result = result.simulation_result
            if sim_result is None:
                messagebox.showerror("Error", "No simulation result available")
                return

            # Build profile dataframe
            rows = []
            s_grid = sim_result.get('s', np.array([]))
            v = sim_result.get('v', np.array([]))
            P_eff = sim_result.get('P_eff', np.array([]))
            CdA = sim_result.get('CdA', np.array([]))
            y = sim_result.get('y', np.array([]))

            for i in range(len(s_grid)):
                rows.append({
                    's_m': s_grid[i] if i < len(s_grid) else 0,
                    'y_m': y[i] if i < len(y) else 0,
                    'CdA_m2': CdA[i] if i < len(CdA) else 0,
                    'P_W': P_eff[i] if i < len(P_eff) else 0,
                    'v_ms': v[i] if i < len(v) else 0,
                })

            df = pd.DataFrame(rows)
            df.to_csv(filepath, index=False)
            self.status_callback(f"Exported to {filepath}")
            messagebox.showinfo("Success", f"Profile exported to:\n{filepath}")

        except Exception as e:
            messagebox.showerror("Error", f"Export failed: {str(e)}")

    def _export_diagnostics(self):
        """Export optimization diagnostics including watts/CdA analysis."""
        from tkinter import filedialog
        import pandas as pd
        from core.physics import (
            calculate_watts_per_cda, calculate_breakeven_watts_per_cda,
            calculate_implied_cda, RHO
        )

        # Handle both energy budget and redistribution results
        result = self.result if self.result else self.redistrib_result
        if result is None or not result.success:
            messagebox.showwarning("No Results", "Run optimization first")
            return

        filepath = filedialog.asksaveasfilename(
            title="Export Diagnostics",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not filepath:
            return

        try:
            sim_result = result.simulation_result
            if sim_result is None:
                messagebox.showerror("Error", "No simulation result available")
                return

            sim_params = self._get_sim_params()
            rho = sim_params.get('rho', RHO)

            # Build diagnostics at 10m intervals
            s_grid = sim_result.get('s', np.array([]))
            v = sim_result.get('v', np.array([]))
            P_eff = sim_result.get('P_eff', np.array([]))
            CdA = sim_result.get('CdA', np.array([]))
            t = sim_result.get('t', np.array([]))

            # Sample at 10m intervals
            rows = []
            for s_target in np.arange(0, 900, 10):
                idx = np.abs(s_grid - s_target).argmin() if len(s_grid) > 0 else 0

                if idx >= len(s_grid):
                    continue

                s_m = s_grid[idx]
                v_ms = v[idx] if idx < len(v) else 0
                P_W = P_eff[idx] if idx < len(P_eff) else 0
                CdA_m2 = CdA[idx] if idx < len(CdA) else 0.25
                t_s = t[idx] if idx < len(t) else 0

                # Calculate metrics
                watts_per_cda = calculate_watts_per_cda(P_W, CdA_m2)
                breakeven_w_cda = calculate_breakeven_watts_per_cda(v_ms, rho)
                implied_cda = calculate_implied_cda(P_W, v_ms, rho) if v_ms > 0 else 0

                rows.append({
                    's_m': s_m,
                    't_s': t_s,
                    'v_ms': v_ms,
                    'v_kmh': v_ms * 3.6,
                    'P_W': P_W,
                    'CdA_m2': CdA_m2,
                    'watts_per_CdA': watts_per_cda,
                    'breakeven_W_CdA': breakeven_w_cda,
                    'efficiency_ratio': watts_per_cda / breakeven_w_cda if breakeven_w_cda > 0 else 0,
                    'implied_CdA': implied_cda,
                })

            df = pd.DataFrame(rows)
            df.to_csv(filepath, index=False)
            self.status_callback(f"Diagnostics exported to {filepath}")
            messagebox.showinfo("Success", f"Diagnostics exported to:\n{filepath}")

        except Exception as e:
            import traceback
            messagebox.showerror("Error", f"Export failed: {str(e)}\n{traceback.format_exc()}")

    # =========================================================================
    # V1-STYLE CHARTS (Position, Power Limits, Cadence, Section Bars)
    # =========================================================================

    def _draw_position_timeline(self, result, baseline_result: dict):
        """Draw position timeline chart showing sit/stand over distance.

        V1 Reference: sprint_optimizer_gui.py lines 559-584
        Shows red filled regions for STANDING, blue filled regions for SEATED.
        """
        import matplotlib.pyplot as plt

        # Get segment positions from result
        positions = result.positions if hasattr(result, 'positions') else []
        segments = result.segment_summary if hasattr(result, 'segment_summary') else []

        if not positions or not segments:
            return

        # Create figure with 2 subplots: position timeline and CdA profile
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

        # Build position data over distance
        s_values = []
        position_values = []  # 1 = standing, 0 = seated

        for i, seg in enumerate(segments):
            s_start = seg.get('start_m', i * 50)
            s_end = seg.get('end_m', (i + 1) * 50)
            pos = positions[i] if i < len(positions) else 'seated'

            # Add points for this segment
            s_values.extend([s_start, s_end - 0.1])
            pos_val = 1 if pos == 'standing' else 0
            position_values.extend([pos_val, pos_val])

        if not s_values:
            return

        s_arr = np.array(s_values)
        pos_arr = np.array(position_values)

        # === Plot 1: Position Timeline ===
        # Fill standing regions red, seated regions blue
        ax1.fill_between(s_arr, pos_arr, 0,
                        where=(pos_arr == 1),
                        color='#EF4444', alpha=0.7, label='STANDING', step='pre')
        ax1.fill_between(s_arr, pos_arr, 0,
                        where=(pos_arr == 0),
                        color='#3B82F6', alpha=0.7, label='Seated', step='pre')

        ax1.set_ylim(-0.1, 1.3)
        ax1.set_yticks([0, 1])
        ax1.set_yticklabels(['Seated', 'STANDING'])
        ax1.set_ylabel('Position')
        ax1.set_title('Position Timeline (Sit/Stand by Segment)', fontsize=11, fontweight='bold')
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3, axis='x')

        # Add timed zone markers
        ax1.axvline(x=695, color='purple', linestyle='--', linewidth=2, alpha=0.7, label='200m Start')
        ax1.axvline(x=895, color='purple', linestyle='--', linewidth=2, alpha=0.7)

        # Annotate transitions
        prev_pos = None
        for i, seg in enumerate(segments):
            s_start = seg.get('start_m', i * 50)
            pos = positions[i] if i < len(positions) else 'seated'
            if prev_pos is not None and pos != prev_pos:
                action = "SIT" if pos == 'seated' else "STAND"
                ax1.annotate(action, xy=(s_start, 0.5), fontsize=9, fontweight='bold',
                           ha='center', va='center', color='white',
                           bbox=dict(boxstyle='round', facecolor='black', alpha=0.7))
            prev_pos = pos

        # === Plot 2: CdA Profile with Position Colors ===
        sim_result = result.simulation_result
        if sim_result is not None and isinstance(sim_result, dict):
            s_grid = sim_result.get('s', np.array([]))
            CdA = sim_result.get('CdA', np.array([]))

            if len(s_grid) > 0 and len(CdA) > 0:
                ax2.plot(s_grid, CdA, 'k-', linewidth=2, label='Optimized CdA')

                # Color fill based on position
                for i, seg in enumerate(segments):
                    s_start = seg.get('start_m', i * 50)
                    s_end = seg.get('end_m', (i + 1) * 50)
                    pos = positions[i] if i < len(positions) else 'seated'
                    color = '#EF4444' if pos == 'standing' else '#3B82F6'

                    mask = (s_grid >= s_start) & (s_grid < s_end)
                    if mask.any():
                        ax2.fill_between(s_grid[mask], 0, CdA[mask],
                                       color=color, alpha=0.3)

                ax2.set_ylabel('CdA (m²)')
                ax2.set_xlabel('Distance (m)')
                ax2.set_title('CdA Profile with Position', fontsize=10)
                ax2.grid(True, alpha=0.3)
                ax2.legend(loc='upper right', fontsize=8)

                # Add reference lines for typical CdA values
                cda_seated = float(self.cda_seated_var.get())
                cda_standing = float(self.cda_standing_var.get())
                ax2.axhline(y=cda_seated, color='#3B82F6', linestyle=':', alpha=0.5,
                          label=f'Seated ({cda_seated:.3f})')
                ax2.axhline(y=cda_standing, color='#EF4444', linestyle=':', alpha=0.5,
                          label=f'Standing ({cda_standing:.3f})')

        # Add timed zone markers
        ax2.axvline(x=695, color='purple', linestyle='--', linewidth=2, alpha=0.7)
        ax2.axvline(x=895, color='purple', linestyle='--', linewidth=2, alpha=0.7)

        plt.tight_layout()
        self.position_chart_canvas.show_figure(fig)

    def _draw_power_curve_limits(self, result, baseline_result: dict):
        """Draw instantaneous power vs power curve limits chart.

        Shows:
        - Seated max power curve (blue line) - instantaneous limit at elapsed time t
        - Standing max power curve (red line) - instantaneous limit at elapsed time t
        - Actual instantaneous power from optimization (green)
        - Applicable limit based on position used (orange dashed)

        The constraint is: At elapsed time t with position p, power <= curve_p(t)
        This chart visualizes that exact constraint.
        """
        import matplotlib.pyplot as plt
        from scipy.interpolate import interp1d

        sim_result = result.simulation_result
        if sim_result is None or not isinstance(sim_result, dict):
            return

        # Get time and power arrays
        s_grid = sim_result.get('s', np.array([]))
        t_arr = sim_result.get('t', np.array([]))
        P_eff = sim_result.get('P_eff', np.array([]))
        dt = sim_result.get('dt', np.array([]))

        if len(s_grid) == 0 or len(t_arr) == 0 or len(P_eff) == 0:
            return

        # Get power curves from session or config
        if self.session.power_curves is not None:
            pc = self.session.power_curves
            seated_curve = pc.seated.to_dict()
            standing_curve = pc.standing.to_dict()
        else:
            from core.config import get_default_power_curves, BUILTIN_DEFAULTS
            config_power = get_default_power_curves()
            if config_power:
                seated_curve = {int(k): v for k, v in config_power.get("seated", {}).items()}
                standing_curve = {int(k): v for k, v in config_power.get("standing", {}).items()}
            else:
                seated_curve = BUILTIN_DEFAULTS["power_curves"]["seated"]
                standing_curve = BUILTIN_DEFAULTS["power_curves"]["standing"]

        # Calculate elapsed time from optimization start
        opt_start_m = float(self.opt_start_var.get())
        opt_start_idx = np.searchsorted(s_grid, opt_start_m)

        # Get power and time from opt start onwards
        if len(dt) > 0:
            dt_arr = dt[opt_start_idx:]
        else:
            dt_arr = np.diff(t_arr)
            if opt_start_idx < len(dt_arr):
                dt_arr = dt_arr[opt_start_idx:]

        P_arr = P_eff[opt_start_idx:opt_start_idx + len(dt_arr)]
        s_arr = s_grid[opt_start_idx:opt_start_idx + len(dt_arr)]

        if len(P_arr) == 0 or len(dt_arr) == 0:
            return

        # Elapsed time from sprint start
        elapsed_time = np.cumsum(dt_arr)

        # Create figure
        fig, ax = plt.subplots(figsize=(10, 6))

        # Build interpolators for curves
        seated_durations = sorted(seated_curve.keys())
        seated_powers = [seated_curve[d] for d in seated_durations]
        standing_durations = sorted(standing_curve.keys())
        standing_powers = [standing_curve[d] for d in standing_durations]

        f_seated = None
        f_standing = None
        if len(seated_durations) > 1:
            f_seated = interp1d(seated_durations, seated_powers, kind='linear',
                               fill_value=(seated_powers[0], seated_powers[-1]), bounds_error=False)
        if len(standing_durations) > 1:
            f_standing = interp1d(standing_durations, standing_powers, kind='linear',
                                 fill_value=(standing_powers[0], standing_powers[-1]), bounds_error=False)

        # Plot power curves (the instantaneous limits at each elapsed time)
        durations = np.linspace(1, 30, 100)  # Focus on 1-30s range
        if f_seated is not None:
            seated_limits = f_seated(durations)
            ax.fill_between(durations, seated_limits, alpha=0.15, color='#3B82F6')
            ax.plot(durations, seated_limits, 'b-', linewidth=2, label='Seated Limit', alpha=0.8)
        if f_standing is not None:
            standing_limits = f_standing(durations)
            ax.fill_between(durations, standing_limits, alpha=0.15, color='#EF4444')
            ax.plot(durations, standing_limits, 'r-', linewidth=2, label='Standing Limit', alpha=0.8)

        # Get positions from result to build applicable limit curve
        positions = result.positions if hasattr(result, 'positions') else []
        segments = result.segment_summary if hasattr(result, 'segment_summary') else []

        def get_position_at_distance(s_m):
            """Get position (seated/standing) at distance."""
            for i, seg in enumerate(segments):
                if seg.get('start_m', 0) <= s_m < seg.get('end_m', 1000):
                    return positions[i] if i < len(positions) else 'seated'
            # Default: in timed zone (695+), use seated
            return 'seated'

        # Build applicable limit at each time point based on actual position
        applicable_limits = np.zeros(len(elapsed_time))
        for i, (t, s) in enumerate(zip(elapsed_time, s_arr)):
            pos = get_position_at_distance(s)
            if pos == 'standing' and f_standing is not None:
                applicable_limits[i] = f_standing(max(1.0, t))
            elif f_seated is not None:
                applicable_limits[i] = f_seated(max(1.0, t))
            else:
                applicable_limits[i] = 1200  # Fallback

        # Plot applicable limit (the constraint that was actually applied)
        valid_mask = elapsed_time <= 30
        time_valid = elapsed_time[valid_mask]
        limits_valid = applicable_limits[valid_mask]
        power_valid = P_arr[valid_mask]

        ax.plot(time_valid, limits_valid, '--', color='orange', linewidth=2,
               label='Applicable Limit', alpha=0.9, zorder=4)

        # Plot actual instantaneous power
        ax.plot(time_valid, power_valid,
               'g-', linewidth=2.5, label='Actual Power', zorder=5)

        # Check for violations
        violations = []
        for i, (t, p, limit) in enumerate(zip(time_valid, power_valid, limits_valid)):
            if t >= 1 and p > limit * 1.001:  # Small tolerance
                violations.append((t, p, limit))
                ax.scatter([t], [p], color='red', s=100, zorder=10, marker='x', linewidths=2)

        # Highlight violations
        if violations:
            for t, p, limit in violations:
                ax.annotate(f'+{p-limit:.0f}W', xy=(t, p), xytext=(5, 10),
                          textcoords='offset points', fontsize=8, color='red', fontweight='bold')

        # Add annotations for key time points
        key_times = [5, 10, 15, 20]
        for d in key_times:
            idx = np.abs(elapsed_time - d).argmin()
            if idx < len(P_arr) and elapsed_time[idx] <= 30:
                ax.annotate(f'{P_arr[idx]:.0f}W',
                          xy=(elapsed_time[idx], P_arr[idx]),
                          xytext=(5, 5), textcoords='offset points',
                          fontsize=8, color='green')

        ax.set_xlabel('Elapsed Time (s)')
        ax.set_ylabel('Power (W)')

        # Title shows violation status
        if violations:
            ax.set_title(
                f'⚠️ INSTANTANEOUS POWER EXCEEDS LIMIT ({len(violations)} violations)\n'
                f'Power at time t exceeds curve(t) - optimization invalid!',
                fontsize=11, fontweight='bold', color='red'
            )
        else:
            ax.set_title(
                '✓ Instantaneous Power vs Curve Limits\n'
                'At all times t: power(t) ≤ curve(t, position)',
                fontsize=11, fontweight='bold', color='green'
            )

        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3)
        ax.set_xlim([0, 30])  # Focus on 0-30s range

        # Add T_200 annotation
        t200 = result.best_time_s if hasattr(result, 'best_time_s') else sim_result.get('T_200', 0)
        ax.axvline(x=t200, color='purple', linestyle='--', linewidth=1.5, alpha=0.7)
        ax.annotate(f'T_200: {t200:.2f}s', xy=(t200, ax.get_ylim()[1] * 0.95),
                   fontsize=9, ha='left', color='purple')

        plt.tight_layout()
        self.curve_limits_chart_canvas.show_figure(fig)

    def _draw_section_bar_chart(self, result, baseline_result: dict):
        """Draw section-by-section speed difference bar chart.

        V1 Reference: flying200_gui.py lines 8458-8496
        Shows bar chart per section with value annotations.
        Quick visual scan of where gains/losses are.
        """
        import matplotlib.pyplot as plt
        from core.track import get_segment_at_distance

        sim_result = result.simulation_result
        if sim_result is None or not isinstance(sim_result, dict):
            return

        # Get data arrays
        s_opt = sim_result.get('s', np.array([]))
        v_opt = sim_result.get('v', np.array([]))

        s_base = baseline_result.get('s', baseline_result.get('s_grid', np.array([])))
        v_base = baseline_result.get('v', np.array([]))

        if len(s_opt) == 0 or len(s_base) == 0:
            return

        track = self.session.track

        # Define sections for the full course
        # Use track segments if available, otherwise use fixed 50m segments
        sections = []

        if track:
            # Use track geometry segments
            # Group by lap and segment
            current_section = None
            current_lap = None
            section_start = 0

            for s in np.arange(0, 896, 10):  # Sample every 10m
                lap_idx, segment, _ = get_segment_at_distance(s, track)
                section_key = (lap_idx, segment.name)

                if section_key != (current_lap, current_section):
                    if current_section is not None:
                        sections.append({
                            'start': section_start,
                            'end': s,
                            'name': f"L{current_lap}-{current_section[:4]}"
                        })
                    current_section = segment.name
                    current_lap = lap_idx
                    section_start = s

            # Final section
            if current_section is not None:
                sections.append({
                    'start': section_start,
                    'end': 895,
                    'name': f"L{current_lap}-{current_section[:4]}"
                })
        else:
            # Fixed 50m segments
            for s in range(0, 900, 50):
                sections.append({
                    'start': s,
                    'end': min(s + 50, 895),
                    'name': f"{s}m"
                })

        # Calculate average speed difference per section
        section_names = []
        speed_diffs = []

        for sec in sections:
            s_start, s_end = sec['start'], sec['end']

            # Get speeds in this section
            mask_opt = (s_opt >= s_start) & (s_opt < s_end)
            mask_base = (s_base >= s_start) & (s_base < s_end)

            if mask_opt.any() and mask_base.any():
                v_opt_mean = v_opt[mask_opt].mean() * 3.6
                v_base_mean = v_base[mask_base].mean() * 3.6
                diff = v_opt_mean - v_base_mean

                section_names.append(sec['name'])
                speed_diffs.append(diff)

        if not section_names:
            return

        # Create figure
        fig, ax = plt.subplots(figsize=(14, 6))

        # Bar colors
        colors = ['#22C55E' if d >= 0 else '#EF4444' for d in speed_diffs]

        # Create bars
        x_pos = np.arange(len(section_names))
        bars = ax.bar(x_pos, speed_diffs, color=colors, alpha=0.7, edgecolor='black', linewidth=0.5)

        # Add value annotations
        for bar, val in zip(bars, speed_diffs):
            height = bar.get_height()
            va = 'bottom' if height >= 0 else 'top'
            offset = 0.05 if height >= 0 else -0.05
            ax.annotate(f'{val:+.2f}',
                       xy=(bar.get_x() + bar.get_width() / 2, height + offset),
                       ha='center', va=va, fontsize=7, fontweight='bold',
                       color='#166534' if val >= 0 else '#991B1B')

        ax.set_xticks(x_pos)
        ax.set_xticklabels(section_names, rotation=45, ha='right', fontsize=8)
        ax.set_xlabel('Track Section')
        ax.set_ylabel('Speed Difference (km/h)')
        ax.axhline(y=0, color='black', linewidth=1)
        ax.grid(True, alpha=0.3, axis='y')

        # Title with counts
        n_faster = sum(1 for d in speed_diffs if d > 0)
        n_slower = sum(1 for d in speed_diffs if d < 0)
        n_total = len(speed_diffs)
        baseline_t200 = baseline_result.get('T_200', 0)
        opt_t200 = result.best_time_s if hasattr(result, 'best_time_s') else sim_result.get('T_200', 0)
        improvement_ms = (baseline_t200 - opt_t200) * 1000

        ax.set_title(
            f'Speed Difference by Section (Optimized - Baseline)\n'
            f'T_200: {improvement_ms:+.1f}ms | '
            f'{n_faster}/{n_total} sections faster | '
            f'{n_slower}/{n_total} sections slower',
            fontsize=11, fontweight='bold'
        )

        # Legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#22C55E', alpha=0.7, label='Faster than baseline'),
            Patch(facecolor='#EF4444', alpha=0.7, label='Slower than baseline'),
        ]
        ax.legend(handles=legend_elements, loc='upper right')

        # Mark 200m section
        for i, sec in enumerate(sections):
            if sec['start'] >= 695:
                ax.axvspan(i - 0.4, i + 0.4, alpha=0.1, color='purple')

        plt.tight_layout()
        self.section_bar_chart_canvas.show_figure(fig)
