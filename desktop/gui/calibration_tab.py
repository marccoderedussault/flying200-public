"""
Flying 200 V2 - Calibration Table Tab

Compare model-predicted times with actual measured times from timing system.
Calculate implied CdA and validate model accuracy.
"""

import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict, Callable, List
import sys
import os

# Handle imports for both direct and package execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from core.physics import (
    SimulationResult,
    calculate_line_cost,
    calculate_implied_cda,
    S_200_START,
    S_TOTAL,
    G,
)
from core.track import BROMONT_250M, AVAILABLE_TRACKS, get_segment_name
from core.session import Session


# =============================================================================
# Segment Definitions - Multiple Granularities
# =============================================================================

def generate_segment_definitions(granularity: str) -> List[Dict]:
    """
    Generate segment definitions based on selected granularity.

    Args:
        granularity: One of "10m", "50m", "100m", "200m"

    Returns:
        List of segment definitions with name, s_start, s_end
    """
    segments = []

    if granularity == "10m":
        # 20 x 10m segments
        for i in range(20):
            start = S_200_START + i * 10
            end = start + 10
            segments.append({
                "name": f"{i*10}-{(i+1)*10}m",
                "s_start": start,
                "s_end": end,
            })
    elif granularity == "50m":
        # 4 x 50m segments
        for i in range(4):
            start = S_200_START + i * 50
            end = start + 50
            segments.append({
                "name": f"{i*50}-{(i+1)*50}m",
                "s_start": start,
                "s_end": end,
            })
    elif granularity == "100m":
        # 2 x 100m segments
        for i in range(2):
            start = S_200_START + i * 100
            end = start + 100
            segments.append({
                "name": f"{i*100}-{(i+1)*100}m",
                "s_start": start,
                "s_end": end,
            })
    else:  # "200m"
        # 1 x 200m (total)
        segments.append({
            "name": "0-200m",
            "s_start": S_200_START,
            "s_end": S_200_START + 200,
        })

    return segments


GRANULARITY_OPTIONS = {
    "10m (20 segments)": "10m",
    "50m (4 segments)": "50m",
    "100m (2 segments)": "100m",
    "200m (total only)": "200m",
}


class CalibrationTab:
    """
    Calibration tab for comparing model predictions with actual times.

    Features:
    - Shows model-predicted segment times
    - Allows input of actual measured times
    - Calculates delta (real - model)
    - Calculates line cost for each segment
    - Calculates implied CdA from actual performance
    - Multiple granularity options: 10m, 50m, 100m, 200m
    """

    def __init__(
        self,
        parent: ttk.Frame,
        session: Session,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize calibration tab.

        Args:
            parent: Parent frame
            session: Session object
            status_callback: Status update callback
        """
        self.parent = parent
        self.session = session
        self.status_callback = status_callback or (lambda x: None)

        # Simulation result reference (set by main GUI after simulation)
        self.sim_result: Optional[SimulationResult] = None
        self.s_grid: Optional[np.ndarray] = None
        self.y_grid: Optional[np.ndarray] = None
        self.config: Optional[dict] = None

        # Current granularity
        self.current_granularity = "10m"  # Default to 10m like original

        # Segment data storage
        self.segment_data: List[Dict] = []
        self.segment_definitions: List[Dict] = []

        # UI element storage
        self.real_time_entries: Dict[int, ttk.Entry] = {}
        self.delta_labels: Dict[int, tk.StringVar] = {}
        self.real_v_labels: Dict[int, tk.StringVar] = {}
        self.line_cost_labels: Dict[int, tk.StringVar] = {}
        self.implied_cda_labels: Dict[int, tk.StringVar] = {}

        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build the calibration tab UI with two-column layout."""
        # Import chart canvas
        from charts import ChartCanvas

        # === Top Section: Header, Paste, Granularity ===
        top_frame = ttk.Frame(self.parent, padding=5)
        top_frame.pack(fill="x", side="top")

        # Header
        ttk.Label(
            top_frame,
            text="Model Calibration Table",
            font=('Segoe UI', 12, 'bold')
        ).pack(anchor="w")

        # Paste Input Section (compact)
        paste_frame = ttk.Frame(top_frame)
        paste_frame.pack(fill="x", pady=2)

        ttk.Label(paste_frame, text="Paste Times:").pack(side="left", padx=2)
        self.paste_entry = ttk.Entry(paste_frame, width=60)
        self.paste_entry.pack(side="left", padx=2, fill="x", expand=True)
        ttk.Button(paste_frame, text="Apply", command=self._apply_pasted_times, width=8).pack(side="left", padx=2)

        # Granularity Selection (compact)
        gran_frame = ttk.Frame(top_frame)
        gran_frame.pack(fill="x", pady=2)

        ttk.Label(gran_frame, text="Granularity:").pack(side="left", padx=2)
        self.granularity_var = tk.StringVar(value="10m (20 segments)")
        for label, value in GRANULARITY_OPTIONS.items():
            ttk.Radiobutton(
                gran_frame,
                text=label,
                variable=self.granularity_var,
                value=label,
                command=self._on_granularity_changed
            ).pack(side="left", padx=5)

        # Actions (compact, inline)
        ttk.Button(gran_frame, text="Refresh", command=self._refresh_data, width=8).pack(side="right", padx=2)
        ttk.Button(gran_frame, text="Clear", command=self._clear_real_times, width=8).pack(side="right", padx=2)
        ttk.Button(gran_frame, text="Export", command=self._export_csv, width=8).pack(side="right", padx=2)

        # === Main Content: Two Columns ===
        main_frame = ttk.Frame(self.parent)
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Left Column: Table (with scroll)
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side="left", fill="both", expand=True)

        # Scrollable table container with both vertical and horizontal scrolling
        table_container = ttk.Frame(left_frame)
        table_container.pack(fill="both", expand=True)

        # Create canvas with larger minimum width for all columns
        canvas = tk.Canvas(table_container, width=900)
        v_scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=canvas.yview)
        h_scrollbar = ttk.Scrollbar(table_container, orient="horizontal", command=canvas.xview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # Pack scrollbars and canvas
        h_scrollbar.pack(side="bottom", fill="x")
        v_scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Mouse wheel scrolling (vertical)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Shift+mouse wheel for horizontal scrolling
        def _on_shift_mousewheel(event):
            canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<Shift-MouseWheel>", _on_shift_mousewheel)

        # Table Frame (inside scrollable)
        self.table_frame = ttk.Frame(self.scrollable_frame)
        self.table_frame.pack(fill="x", pady=2)

        # Build initial table with 10m segments
        self._rebuild_table()

        # Totals Frame (below table, in left column)
        self.totals_frame = ttk.LabelFrame(left_frame, text="Summary Statistics", padding=5)
        self.totals_frame.pack(fill="x", pady=5)

        self._build_totals_section()

        # Right Column: Charts
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side="right", fill="both", expand=True, padx=(10, 0))

        # Speed Comparison Chart
        speed_chart_frame = ttk.LabelFrame(right_frame, text="Speed Comparison", padding=5)
        speed_chart_frame.pack(fill="both", expand=True, pady=(0, 5))

        self.speed_chart_canvas = ChartCanvas(speed_chart_frame)

        # Delta Chart
        delta_chart_frame = ttk.LabelFrame(right_frame, text="Time Delta by Segment", padding=5)
        delta_chart_frame.pack(fill="both", expand=True, pady=(5, 0))

        self.delta_chart_canvas = ChartCanvas(delta_chart_frame)

    def _on_granularity_changed(self):
        """Handle granularity selection change."""
        label = self.granularity_var.get()
        self.current_granularity = GRANULARITY_OPTIONS.get(label, "10m")
        self._rebuild_table()
        if self.sim_result is not None:
            self._refresh_data()
        self._update_charts()

    def _update_charts(self):
        """Update the speed and delta charts."""
        self._draw_speed_chart()
        self._draw_delta_chart()

    def _draw_speed_chart(self):
        """Draw speed comparison chart (model vs real)."""
        import matplotlib.pyplot as plt

        if not self.segment_data:
            return

        fig, ax = plt.subplots(figsize=(6, 3.5))

        # Collect data
        seg_names = []
        model_speeds = []
        real_speeds = []

        for i, seg_data in enumerate(self.segment_data):
            seg_def = seg_data["def"]
            seg_names.append(seg_def["name"].replace("m", ""))

            # Model speed
            try:
                model_v = float(seg_data["model_v_var"].get())
                model_speeds.append(model_v)
            except (ValueError, AttributeError):
                model_speeds.append(0)

            # Real speed
            try:
                real_v_str = self.real_v_labels[i].get()
                if real_v_str and real_v_str != "--":
                    real_speeds.append(float(real_v_str))
                else:
                    real_speeds.append(None)
            except (ValueError, KeyError):
                real_speeds.append(None)

        x = np.arange(len(seg_names))
        width = 0.35

        # Model bars
        bars1 = ax.bar(x - width/2, model_speeds, width, label='Model', color='#3B82F6', alpha=0.8)

        # Real bars (only where data exists)
        real_values = [v if v is not None else 0 for v in real_speeds]
        real_colors = ['#22C55E' if v is not None else '#CCCCCC' for v in real_speeds]
        bars2 = ax.bar(x + width/2, real_values, width, label='Real', color=real_colors, alpha=0.8)

        ax.set_ylabel('Speed (km/h)')
        ax.set_xlabel('Segment')
        ax.set_title('Speed Comparison: Model vs Real')
        ax.set_xticks(x)
        ax.set_xticklabels(seg_names, rotation=45, ha='right', fontsize=7)
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(True, alpha=0.3, axis='y')

        # Set y-axis limits with some padding
        all_speeds = model_speeds + [v for v in real_speeds if v is not None]
        if all_speeds:
            ax.set_ylim([min(all_speeds) * 0.95, max(all_speeds) * 1.02])

        plt.tight_layout()
        self.speed_chart_canvas.show_figure(fig)

    def _draw_delta_chart(self):
        """Draw time delta bar chart."""
        import matplotlib.pyplot as plt

        if not self.segment_data:
            return

        fig, ax = plt.subplots(figsize=(6, 3.5))

        # Collect data
        seg_names = []
        deltas = []
        has_data = []

        for i, seg_data in enumerate(self.segment_data):
            seg_def = seg_data["def"]
            seg_names.append(seg_def["name"].replace("m", ""))

            try:
                delta_str = self.delta_labels[i].get()
                if delta_str and delta_str != "--":
                    delta_val = float(delta_str.replace("+", ""))
                    deltas.append(delta_val)
                    has_data.append(True)
                else:
                    deltas.append(0)
                    has_data.append(False)
            except (ValueError, KeyError):
                deltas.append(0)
                has_data.append(False)

        x = np.arange(len(seg_names))

        # Color by delta sign: red = slower, green = faster
        colors = []
        for d, has in zip(deltas, has_data):
            if not has:
                colors.append('#CCCCCC')
            elif d > 0.001:
                colors.append('#EF4444')  # Red = slower (positive delta)
            elif d < -0.001:
                colors.append('#22C55E')  # Green = faster (negative delta)
            else:
                colors.append('#6B7280')  # Gray = neutral

        bars = ax.bar(x, deltas, color=colors, alpha=0.8)

        ax.axhline(y=0, color='black', linewidth=0.5)
        ax.set_ylabel('Delta (seconds)')
        ax.set_xlabel('Segment')
        ax.set_title('Time Delta (Real - Model) | Red=Slower, Green=Faster')
        ax.set_xticks(x)
        ax.set_xticklabels(seg_names, rotation=45, ha='right', fontsize=7)
        ax.grid(True, alpha=0.3, axis='y')

        # Set y-axis limits symmetrically
        max_delta = max(abs(d) for d in deltas) if any(has_data) else 0.05
        ax.set_ylim([-max_delta * 1.2, max_delta * 1.2])

        # Add cumulative delta annotation
        total_delta = sum(d for d, has in zip(deltas, has_data) if has)
        if any(has_data):
            sign = "+" if total_delta > 0 else ""
            ax.annotate(
                f'Total: {sign}{total_delta:.3f}s',
                xy=(0.98, 0.95), xycoords='axes fraction',
                ha='right', va='top',
                fontsize=9, fontweight='bold',
                color='#EF4444' if total_delta > 0 else '#22C55E'
            )

        plt.tight_layout()
        self.delta_chart_canvas.show_figure(fig)

    def _apply_pasted_times(self):
        """Parse pasted times, auto-detect granularity, and fill entries."""
        input_str = self.paste_entry.get().strip()
        if not input_str:
            self.status_callback("No times entered")
            return

        # Parse the input (comma, space, or tab separated)
        times = []
        for part in input_str.replace(',', ' ').replace('\t', ' ').split():
            try:
                times.append(float(part.strip()))
            except ValueError:
                continue

        if not times:
            self.status_callback("No valid times found")
            return

        # Auto-detect granularity based on count
        count = len(times)
        if count >= 20:
            target_granularity = "10m"
            target_label = "10m (20 segments)"
        elif count >= 4:
            target_granularity = "50m"
            target_label = "50m (4 segments)"
        elif count >= 2:
            target_granularity = "100m"
            target_label = "100m (2 segments)"
        else:
            target_granularity = "200m"
            target_label = "200m (total only)"

        # Switch granularity if needed
        if self.current_granularity != target_granularity:
            self.current_granularity = target_granularity
            self.granularity_var.set(target_label)
            self._rebuild_table()
            if self.sim_result is not None:
                self._refresh_data()

        # Fill entries with times
        num_segments = len(self.segment_definitions)
        for i, time_val in enumerate(times[:num_segments]):
            if i in self.real_time_entries:
                self.real_time_entries[i].delete(0, tk.END)
                self.real_time_entries[i].insert(0, f"{time_val:.3f}")
                self._on_real_time_changed(i)

        self._update_charts()
        self.status_callback(f"Applied {min(len(times), num_segments)} times ({target_granularity} segments)")

    def _rebuild_table(self):
        """Rebuild the table with current granularity."""
        # Clear existing table
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        # Clear storage
        self.segment_data = []
        self.real_time_entries = {}
        self.delta_labels = {}
        self.real_v_labels = {}
        self.line_cost_labels = {}
        self.implied_cda_labels = {}

        # Generate new segment definitions
        self.segment_definitions = generate_segment_definitions(self.current_granularity)

        # Rebuild header and rows
        self._build_table_header()
        self._build_table_rows()

    def _build_table_header(self):
        """Build the table header row."""
        headers = [
            ("Segment", 10),
            ("Section", 15),
            ("Model v (kph)", 12),
            ("Model dt (s)", 10),
            ("Real dt (s)", 10),
            ("Real v (kph)", 12),
            ("Delta (s)", 10),
            ("Line Cost (s)", 12),
            ("Model CdA", 10),
            ("Implied CdA", 10),
        ]

        for col, (header, width) in enumerate(headers):
            label = ttk.Label(
                self.table_frame,
                text=header,
                font=('Segoe UI', 9, 'bold'),
                borderwidth=1,
                relief="solid",
                anchor="center",
                width=width,
            )
            label.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)

    def _build_table_rows(self):
        """Build the table data rows."""
        for i, seg_def in enumerate(self.segment_definitions):
            row_idx = i + 1

            # Segment name
            ttk.Label(
                self.table_frame,
                text=seg_def["name"],
                borderwidth=1, relief="solid",
                anchor="center", width=10
            ).grid(row=row_idx, column=0, sticky="nsew", padx=1, pady=1)

            # Section (track location) - will be updated
            section_var = tk.StringVar(value="--")
            ttk.Label(
                self.table_frame,
                textvariable=section_var,
                borderwidth=1, relief="solid",
                anchor="center", width=15
            ).grid(row=row_idx, column=1, sticky="nsew", padx=1, pady=1)

            # Model velocity
            model_v_var = tk.StringVar(value="--")
            ttk.Label(
                self.table_frame,
                textvariable=model_v_var,
                borderwidth=1, relief="solid",
                anchor="center", width=12
            ).grid(row=row_idx, column=2, sticky="nsew", padx=1, pady=1)

            # Model time
            model_t_var = tk.StringVar(value="--")
            ttk.Label(
                self.table_frame,
                textvariable=model_t_var,
                borderwidth=1, relief="solid",
                anchor="center", width=10
            ).grid(row=row_idx, column=3, sticky="nsew", padx=1, pady=1)

            # Real time entry
            real_time_entry = ttk.Entry(self.table_frame, width=10, justify="center")
            real_time_entry.grid(row=row_idx, column=4, sticky="nsew", padx=1, pady=1)
            real_time_entry.bind("<KeyRelease>", lambda e, idx=i: self._on_real_time_changed(idx))
            self.real_time_entries[i] = real_time_entry

            # Real velocity
            real_v_var = tk.StringVar(value="--")
            self.real_v_labels[i] = real_v_var
            ttk.Label(
                self.table_frame,
                textvariable=real_v_var,
                borderwidth=1, relief="solid",
                anchor="center", width=12
            ).grid(row=row_idx, column=5, sticky="nsew", padx=1, pady=1)

            # Delta
            delta_var = tk.StringVar(value="--")
            self.delta_labels[i] = delta_var
            delta_label = ttk.Label(
                self.table_frame,
                textvariable=delta_var,
                borderwidth=1, relief="solid",
                anchor="center", width=10
            )
            delta_label.grid(row=row_idx, column=6, sticky="nsew", padx=1, pady=1)

            # Line cost
            line_cost_var = tk.StringVar(value="--")
            self.line_cost_labels[i] = line_cost_var
            ttk.Label(
                self.table_frame,
                textvariable=line_cost_var,
                borderwidth=1, relief="solid",
                anchor="center", width=12
            ).grid(row=row_idx, column=7, sticky="nsew", padx=1, pady=1)

            # Model CdA
            model_cda_var = tk.StringVar(value="--")
            ttk.Label(
                self.table_frame,
                textvariable=model_cda_var,
                borderwidth=1, relief="solid",
                anchor="center", width=10
            ).grid(row=row_idx, column=8, sticky="nsew", padx=1, pady=1)

            # Implied CdA
            implied_cda_var = tk.StringVar(value="--")
            self.implied_cda_labels[i] = implied_cda_var
            ttk.Label(
                self.table_frame,
                textvariable=implied_cda_var,
                borderwidth=1, relief="solid",
                anchor="center", width=10
            ).grid(row=row_idx, column=9, sticky="nsew", padx=1, pady=1)

            # Store references for updating
            self.segment_data.append({
                "def": seg_def,
                "section_var": section_var,
                "model_v_var": model_v_var,
                "model_t_var": model_t_var,
                "model_cda_var": model_cda_var,
            })

    def _build_totals_section(self):
        """Build the totals section with summary statistics."""
        # Row 1: Time totals
        row1 = ttk.Frame(self.totals_frame)
        row1.pack(fill="x", pady=2)

        ttk.Label(row1, text="Time Totals:", font=('Segoe UI', 9, 'bold'), width=12).pack(side="left", padx=5)

        self.total_model_var = tk.StringVar(value="Model: --")
        ttk.Label(row1, textvariable=self.total_model_var, width=15).pack(side="left", padx=5)

        self.total_real_var = tk.StringVar(value="Real: --")
        ttk.Label(row1, textvariable=self.total_real_var, width=15).pack(side="left", padx=5)

        self.total_delta_var = tk.StringVar(value="Delta: --")
        ttk.Label(row1, textvariable=self.total_delta_var, width=15).pack(side="left", padx=5)

        self.total_line_cost_var = tk.StringVar(value="Line Cost: --")
        ttk.Label(row1, textvariable=self.total_line_cost_var, width=18).pack(side="left", padx=5)

        # Row 2: Velocity averages
        row2 = ttk.Frame(self.totals_frame)
        row2.pack(fill="x", pady=2)

        ttk.Label(row2, text="Velocity Avg:", font=('Segoe UI', 9, 'bold'), width=12).pack(side="left", padx=5)

        self.avg_model_v_var = tk.StringVar(value="Model: --")
        ttk.Label(row2, textvariable=self.avg_model_v_var, width=15).pack(side="left", padx=5)

        self.avg_real_v_var = tk.StringVar(value="Real: --")
        ttk.Label(row2, textvariable=self.avg_real_v_var, width=15).pack(side="left", padx=5)

        self.delta_v_var = tk.StringVar(value="Delta: --")
        ttk.Label(row2, textvariable=self.delta_v_var, width=15).pack(side="left", padx=5)

        # Row 3: CdA averages
        row3 = ttk.Frame(self.totals_frame)
        row3.pack(fill="x", pady=2)

        ttk.Label(row3, text="CdA Average:", font=('Segoe UI', 9, 'bold'), width=12).pack(side="left", padx=5)

        self.avg_model_cda_var = tk.StringVar(value="Model (time-wtd): --")
        ttk.Label(row3, textvariable=self.avg_model_cda_var, width=18).pack(side="left", padx=5)

        self.avg_implied_cda_var = tk.StringVar(value="Implied (time-wtd): --")
        ttk.Label(row3, textvariable=self.avg_implied_cda_var, width=20).pack(side="left", padx=5)

        self.cda_delta_var = tk.StringVar(value="Delta: --")
        ttk.Label(row3, textvariable=self.cda_delta_var, width=15).pack(side="left", padx=5)

        # Row 4: Statistics
        row4 = ttk.Frame(self.totals_frame)
        row4.pack(fill="x", pady=2)

        ttk.Label(row4, text="Summary:", font=('Segoe UI', 9, 'bold'), width=12).pack(side="left", padx=5)

        self.perf_ratio_var = tk.StringVar(value="Perf Ratio: --")
        ttk.Label(row4, textvariable=self.perf_ratio_var, width=15).pack(side="left", padx=5)

        self.equiv_cda_var = tk.StringVar(value="Equiv CdA for real time: --")
        ttk.Label(row4, textvariable=self.equiv_cda_var, width=25).pack(side="left", padx=5)

    def set_simulation_result(
        self,
        result: SimulationResult,
        s_grid: np.ndarray,
        y_grid: np.ndarray,
        config: dict,
    ):
        """
        Set simulation result for calibration comparison.

        Called by main GUI after simulation completes.
        """
        self.sim_result = result
        self.s_grid = s_grid
        self.y_grid = y_grid
        self.config = config
        self._refresh_data()

    def _refresh_data(self):
        """Refresh table data from simulation result."""
        if self.sim_result is None:
            self.status_callback("No simulation result available. Run simulation first.")
            return

        track = self.session.track or BROMONT_250M
        result = self.sim_result

        # Update each segment
        for i, seg_data in enumerate(self.segment_data):
            seg_def = seg_data["def"]
            s_start = seg_def["s_start"]
            s_end = seg_def["s_end"]

            # Get section name at midpoint
            s_mid = (s_start + s_end) / 2
            section_name = get_segment_name(s_mid, track, include_lap=True)
            seg_data["section_var"].set(section_name)

            # Calculate model time for segment
            t_start = np.interp(s_start, result.s_grid, result.t)
            t_end = np.interp(s_end, result.s_grid, result.t)
            model_time = t_end - t_start
            seg_data["model_t_var"].set(f"{model_time:.3f}")

            # Calculate model velocity
            segment_dist = s_end - s_start
            model_v_ms = segment_dist / model_time if model_time > 0 else 0
            model_v_kph = model_v_ms * 3.6
            seg_data["model_v_var"].set(f"{model_v_kph:.1f}")

            # Get model CdA at midpoint
            model_cda = np.interp(s_mid, result.s_grid, result.CdA)
            seg_data["model_cda_var"].set(f"{model_cda:.3f}")

            # Calculate line cost for segment
            if self.s_grid is not None and self.y_grid is not None:
                line_cost = calculate_line_cost(
                    self.s_grid, self.y_grid, result.v,
                    s_start, s_end,
                    straight_length=track.straight_length_m,
                    lap_length=track.length_m,
                    radius_bend=track.turn_radius_m,
                    s_offset=track.straight_length_m + track.arc_length_m + 0.5 * track.straight_length_m,
                )
                self.line_cost_labels[i].set(f"{line_cost:+.4f}")
            else:
                self.line_cost_labels[i].set("--")

            # Store segment data for implied CdA calculation
            seg_data["model_time"] = model_time
            seg_data["segment_dist"] = segment_dist
            seg_data["model_cda"] = model_cda
            seg_data["t_start"] = t_start
            seg_data["t_end"] = t_end

            # Get power for segment
            mask = (result.s_grid >= s_start) & (result.s_grid <= s_end)
            if mask.any():
                seg_data["p_avg"] = np.mean(result.P_eff[mask])
                seg_data["theta_avg"] = np.mean(result.theta[mask])
            else:
                seg_data["p_avg"] = 0
                seg_data["theta_avg"] = 0

            # Get height change
            y_start = np.interp(s_start, result.s_grid, result.y)
            y_end = np.interp(s_end, result.s_grid, result.y)
            theta_start = np.interp(s_start, result.s_grid, result.theta)
            theta_end = np.interp(s_end, result.s_grid, result.theta)
            h_start = y_start * np.sin(theta_start)
            h_end = y_end * np.sin(theta_end)
            seg_data["dh"] = h_end - h_start

            # Get velocities
            seg_data["v_start"] = np.interp(s_start, result.s_grid, result.v)
            seg_data["v_end"] = np.interp(s_end, result.s_grid, result.v)

        # Update totals
        self.total_model_var.set(f"Model: {result.T_200:.3f} s")
        self.total_line_cost_var.set(f"Line Cost: {result.line_cost_200:+.4f} s")

        # Update charts
        self._update_charts()

        self.status_callback("Calibration table updated from simulation")

    def _on_real_time_changed(self, idx: int):
        """Handle change in real time entry."""
        if self.sim_result is None or idx >= len(self.segment_data):
            return

        try:
            real_time_str = self.real_time_entries[idx].get().strip()
            if not real_time_str:
                self.delta_labels[idx].set("--")
                self.real_v_labels[idx].set("--")
                self.implied_cda_labels[idx].set("--")
                self._update_totals()
                return

            real_time = float(real_time_str)
            seg_data = self.segment_data[idx]
            model_time = seg_data.get("model_time", 0)
            segment_dist = seg_data.get("segment_dist", 50)

            # Calculate delta
            delta = real_time - model_time
            if abs(delta) > 0.001:
                if delta > 0:
                    self.delta_labels[idx].set(f"+{delta:.3f}")
                else:
                    self.delta_labels[idx].set(f"{delta:.3f}")
            else:
                self.delta_labels[idx].set("0.000")

            # Calculate real velocity
            real_v_ms = segment_dist / real_time if real_time > 0 else 0
            real_v_kph = real_v_ms * 3.6
            self.real_v_labels[idx].set(f"{real_v_kph:.1f}")

            # Calculate implied CdA
            if hasattr(self, 'config') and self.config:
                implied = calculate_implied_cda(
                    segment_distance=segment_dist,
                    real_time=real_time,
                    power_avg=seg_data.get("p_avg", 0),
                    mass=self.config.get('M', 92),
                    rho=self.config.get('rho', 1.1627),
                    c_rr=self.config.get('C_RR', 0.002),
                    drivetrain_eff=self.config.get('drivetrain_eff', 0.98),
                    theta_avg=seg_data.get("theta_avg", 0),
                    dh=seg_data.get("dh", 0),
                    v_start=seg_data.get("v_start", real_v_ms),
                    v_end=seg_data.get("v_end", real_v_ms),
                )
                if implied is not None:
                    self.implied_cda_labels[idx].set(f"{implied:.3f}")
                else:
                    self.implied_cda_labels[idx].set("--")
            else:
                self.implied_cda_labels[idx].set("--")

            self._update_totals()

        except ValueError:
            self.delta_labels[idx].set("--")
            self.real_v_labels[idx].set("--")
            self.implied_cda_labels[idx].set("--")

    def _update_totals(self):
        """Update totals section with comprehensive summary statistics."""
        total_real = 0.0
        total_model = 0.0
        all_entered = True

        # Collect data for weighted averages
        real_times = []
        model_times = []
        model_cdas = []
        implied_cdas = []
        segment_dists = []

        for i in range(len(self.segment_definitions)):
            seg_data = self.segment_data[i] if i < len(self.segment_data) else {}

            # Get model time
            model_time = seg_data.get("model_time", 0)
            model_times.append(model_time)
            total_model += model_time

            # Get model CdA
            model_cda = seg_data.get("model_cda", 0)
            model_cdas.append(model_cda)

            # Get segment distance
            segment_dist = seg_data.get("segment_dist", 10)
            segment_dists.append(segment_dist)

            # Get real time
            try:
                real_time_str = self.real_time_entries[i].get().strip()
                if real_time_str:
                    real_time = float(real_time_str)
                    real_times.append(real_time)
                    total_real += real_time
                else:
                    all_entered = False
                    real_times.append(None)
            except (ValueError, KeyError):
                all_entered = False
                real_times.append(None)

            # Get implied CdA
            try:
                implied_cda_str = self.implied_cda_labels[i].get()
                if implied_cda_str and implied_cda_str != "--":
                    implied_cdas.append((float(implied_cda_str), real_times[-1] if real_times[-1] else 0))
            except (ValueError, KeyError):
                pass

        # === Update Time Totals ===
        if all_entered and self.sim_result is not None:
            self.total_real_var.set(f"Real: {total_real:.3f} s")
            total_delta = total_real - self.sim_result.T_200
            if total_delta > 0:
                self.total_delta_var.set(f"Delta: +{total_delta:.3f} s")
            else:
                self.total_delta_var.set(f"Delta: {total_delta:.3f} s")

            # Performance ratio (model/real time - higher is better)
            if total_real > 0:
                perf_ratio = self.sim_result.T_200 / total_real
                self.perf_ratio_var.set(f"Perf Ratio: {perf_ratio:.3f}")
            else:
                self.perf_ratio_var.set("Perf Ratio: --")
        else:
            self.total_real_var.set("Real: --")
            self.total_delta_var.set("Delta: --")
            self.perf_ratio_var.set("Perf Ratio: --")

        # === Update Velocity Averages ===
        # Model average velocity (distance / time)
        total_distance = sum(segment_dists)
        if total_model > 0:
            avg_model_v = (total_distance / total_model) * 3.6  # kph
            self.avg_model_v_var.set(f"Model: {avg_model_v:.1f} kph")
        else:
            self.avg_model_v_var.set("Model: --")

        if all_entered and total_real > 0:
            avg_real_v = (total_distance / total_real) * 3.6  # kph
            self.avg_real_v_var.set(f"Real: {avg_real_v:.1f} kph")

            if total_model > 0:
                delta_v = avg_real_v - avg_model_v
                if delta_v >= 0:
                    self.delta_v_var.set(f"Delta: +{delta_v:.1f} kph")
                else:
                    self.delta_v_var.set(f"Delta: {delta_v:.1f} kph")
            else:
                self.delta_v_var.set("Delta: --")
        else:
            self.avg_real_v_var.set("Real: --")
            self.delta_v_var.set("Delta: --")

        # === Update CdA Averages ===
        # Model CdA (time-weighted average)
        if sum(model_times) > 0 and model_cdas:
            wtd_model_cda = sum(cda * t for cda, t in zip(model_cdas, model_times)) / sum(model_times)
            self.avg_model_cda_var.set(f"Model: {wtd_model_cda:.4f}")
        else:
            self.avg_model_cda_var.set("Model: --")

        # Implied CdA (time-weighted average)
        if implied_cdas:
            total_weight = sum(t for _, t in implied_cdas if t > 0)
            if total_weight > 0:
                wtd_implied_cda = sum(cda * t for cda, t in implied_cdas) / total_weight
                self.avg_implied_cda_var.set(f"Implied: {wtd_implied_cda:.4f}")

                # CdA delta
                if sum(model_times) > 0 and model_cdas:
                    cda_delta = wtd_implied_cda - wtd_model_cda
                    if cda_delta >= 0:
                        self.cda_delta_var.set(f"Delta: +{cda_delta:.4f}")
                    else:
                        self.cda_delta_var.set(f"Delta: {cda_delta:.4f}")
                else:
                    self.cda_delta_var.set("Delta: --")
            else:
                self.avg_implied_cda_var.set("Implied: --")
                self.cda_delta_var.set("Delta: --")
        else:
            self.avg_implied_cda_var.set("Implied: --")
            self.cda_delta_var.set("Delta: --")

        # === Equivalent CdA ===
        # What CdA would the model need to match real time?
        if all_entered and total_real > 0 and total_model > 0 and sum(model_cdas) > 0:
            # Rough estimate: CdA scales with time^2 at constant power
            time_ratio = total_real / total_model
            equiv_cda = wtd_model_cda * (time_ratio ** 2)
            self.equiv_cda_var.set(f"Equiv CdA: {equiv_cda:.4f}")
        else:
            self.equiv_cda_var.set("Equiv CdA: --")

        # Update charts when totals change
        self._update_charts()

    def _clear_real_times(self):
        """Clear all real time entries and summary fields."""
        for entry in self.real_time_entries.values():
            entry.delete(0, tk.END)

        for i in range(len(self.segment_definitions)):
            if i in self.delta_labels:
                self.delta_labels[i].set("--")
            if i in self.real_v_labels:
                self.real_v_labels[i].set("--")
            if i in self.implied_cda_labels:
                self.implied_cda_labels[i].set("--")

        # Clear summary fields
        self.total_real_var.set("Real: --")
        self.total_delta_var.set("Delta: --")
        self.avg_real_v_var.set("Real: --")
        self.delta_v_var.set("Delta: --")
        self.avg_implied_cda_var.set("Implied: --")
        self.cda_delta_var.set("Delta: --")
        self.perf_ratio_var.set("Perf Ratio: --")
        self.equiv_cda_var.set("Equiv CdA: --")

        # Update charts
        self._update_charts()

        self.status_callback("Real times cleared")

    def _export_csv(self):
        """Export calibration table to CSV."""
        if self.sim_result is None:
            messagebox.showwarning("Warning", "No simulation data to export")
            return

        from tkinter import filedialog

        filepath = filedialog.asksaveasfilename(
            title="Export Calibration Data",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not filepath:
            return

        try:
            lines = ["Segment,Section,Model_v_kph,Model_dt_s,Real_dt_s,Real_v_kph,Delta_s,Line_Cost_s,Model_CdA,Implied_CdA"]

            for i, seg_data in enumerate(self.segment_data):
                seg_def = seg_data["def"]
                section = seg_data["section_var"].get()
                model_v = seg_data["model_v_var"].get()
                model_t = seg_data["model_t_var"].get()
                model_cda = seg_data["model_cda_var"].get()

                real_t = self.real_time_entries[i].get() or "--"
                real_v = self.real_v_labels[i].get()
                delta = self.delta_labels[i].get()
                line_cost = self.line_cost_labels[i].get()
                implied_cda = self.implied_cda_labels[i].get()

                lines.append(f"{seg_def['name']},{section},{model_v},{model_t},{real_t},{real_v},{delta},{line_cost},{model_cda},{implied_cda}")

            # Add totals row
            lines.append(f"TOTAL,--,--,{self.sim_result.T_200:.3f},{self.total_real_var.get().replace('Real: ', '')},--,{self.total_delta_var.get().replace('Delta: ', '')},{self.sim_result.line_cost_200:+.4f},--,--")

            # Add summary statistics section
            lines.append("")
            lines.append("SUMMARY STATISTICS")
            lines.append(f"Time Totals,{self.total_model_var.get()},{self.total_real_var.get()},{self.total_delta_var.get()},{self.total_line_cost_var.get()}")
            lines.append(f"Velocity Avg,{self.avg_model_v_var.get()},{self.avg_real_v_var.get()},{self.delta_v_var.get()}")
            lines.append(f"CdA Average,{self.avg_model_cda_var.get()},{self.avg_implied_cda_var.get()},{self.cda_delta_var.get()}")
            lines.append(f"Summary,{self.perf_ratio_var.get()},{self.equiv_cda_var.get()}")

            with open(filepath, 'w') as f:
                f.write('\n'.join(lines))

            self.status_callback(f"Exported to {filepath}")

        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export: {str(e)}")
