"""
Flying 200 V2 - FIT Analysis Tab

FIT file analysis workflow:
1. Load FIT file
2. Auto-detect Flying 200 efforts
3. Select effort with confidence score
4. QuickSim preview
5. Convert to distance profile
6. Export to session
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional, List, Callable
import numpy as np
import sys
import os

# Handle imports for both direct and package execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from fit.parser import parse_fit_file, FitFileData, FitRecord
from fit.detector import detect_flying_efforts, create_manual_effort, DetectedEffort
from fit.converter import (
    convert_time_to_distance,
    GearConfig,
    GEAR_55_14,
    GEAR_54_14,
    GEAR_55_15,
    align_to_finish_line,
    extract_effort_profile,
)
from core.session import Session
from charts import ChartCanvas, COLORS


# =============================================================================
# FIT Analysis Tab
# =============================================================================

class FitTab:
    """
    FIT file analysis tab.

    Workflow:
    1. Load FIT file
    2. Auto-detect efforts (shows list with confidence)
    3. Select effort to analyze
    4. Configure gear and convert to distance
    5. QuickSim preview
    6. Export to session for simulation
    """

    def __init__(
        self,
        parent: ttk.Frame,
        session: Session,
        status_callback: Optional[Callable[[str], None]] = None,
        header_callback: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize FIT analysis tab.

        Args:
            parent: Parent frame
            session: Session object
            status_callback: Status update callback
            header_callback: Callback to refresh main header
        """
        self.parent = parent
        self.session = session
        self.status_callback = status_callback or (lambda x: None)
        self.header_callback = header_callback or (lambda: None)

        # Data storage
        self.fit_data: Optional[FitFileData] = None
        self.detected_efforts: List[DetectedEffort] = []
        self.selected_effort: Optional[DetectedEffort] = None
        self.distance_profile = None

        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build the FIT tab UI."""
        # Left panel: Controls
        left_panel = ttk.Frame(self.parent, width=400)
        left_panel.pack(side="left", fill="y", padx=5, pady=5)
        left_panel.pack_propagate(False)

        # Right panel: Charts
        right_panel = ttk.Frame(self.parent)
        right_panel.pack(side="right", fill="both", expand=True, padx=5, pady=5)

        self._build_controls(left_panel)
        self._build_charts(right_panel)

    def _build_controls(self, parent: ttk.Frame):
        """Build control panel."""
        # === File Section ===
        file_frame = ttk.LabelFrame(parent, text="FIT File", padding=5)
        file_frame.pack(fill="x", pady=5)

        ttk.Button(file_frame, text="Load FIT File", command=self._load_fit).pack(fill="x", pady=2)

        self.file_label = ttk.Label(file_frame, text="No file loaded")
        self.file_label.pack(fill="x", pady=2)

        # === Gear Configuration ===
        gear_frame = ttk.LabelFrame(parent, text="Gear Configuration", padding=5)
        gear_frame.pack(fill="x", pady=5)

        ttk.Label(gear_frame, text="Chainring:").pack(side="left", padx=5)
        self.chainring_var = tk.StringVar(value="55")
        ttk.Entry(gear_frame, textvariable=self.chainring_var, width=5).pack(side="left", padx=2)

        ttk.Label(gear_frame, text="Cog:").pack(side="left", padx=5)
        self.cog_var = tk.StringVar(value="12")
        ttk.Entry(gear_frame, textvariable=self.cog_var, width=5).pack(side="left", padx=2)

        # === Detected Efforts ===
        efforts_frame = ttk.LabelFrame(parent, text="Detected Efforts", padding=5)
        efforts_frame.pack(fill="both", expand=True, pady=5)

        # Effort listbox
        self.effort_list = tk.Listbox(efforts_frame, height=8)
        self.effort_list.pack(fill="both", expand=True, pady=2)
        self.effort_list.bind("<<ListboxSelect>>", self._on_effort_selected)

        # Effort details
        self.effort_details = ttk.Label(efforts_frame, text="Select an effort", wraplength=350)
        self.effort_details.pack(fill="x", pady=5)

        # === Manual Override ===
        manual_frame = ttk.LabelFrame(parent, text="Manual Override", padding=5)
        manual_frame.pack(fill="x", pady=5)

        ttk.Label(manual_frame, text="If auto-detect misses the effort,\nenter the final row and click Create.", wraplength=350, font=("", 8)).pack(fill="x", pady=(0, 4))

        row_frame = ttk.Frame(manual_frame)
        row_frame.pack(fill="x")

        ttk.Label(row_frame, text="Final Row:").pack(side="left", padx=5)
        self.final_row_var = tk.StringVar(value="")
        self.final_row_entry = ttk.Entry(row_frame, textvariable=self.final_row_var, width=8)
        self.final_row_entry.pack(side="left", padx=2)

        ttk.Label(row_frame, text="of", font=("", 8)).pack(side="left", padx=2)
        self.total_rows_label = ttk.Label(row_frame, text="--", font=("", 8))
        self.total_rows_label.pack(side="left", padx=2)

        ttk.Button(manual_frame, text="Create Manual Flying 200", command=self._create_manual_effort).pack(fill="x", pady=(4, 0))

        # === Actions ===
        actions_frame = ttk.LabelFrame(parent, text="Actions", padding=5)
        actions_frame.pack(fill="x", pady=5)

        ttk.Button(actions_frame, text="Convert to Distance Profile", command=self._convert_to_distance).pack(fill="x", pady=2)
        ttk.Button(actions_frame, text="Export Profile to CSV", command=self._export_to_csv).pack(fill="x", pady=2)
        ttk.Button(actions_frame, text="Export to Session", command=self._export_to_session).pack(fill="x", pady=2)

    def _build_charts(self, parent: ttk.Frame):
        """Build chart panel."""
        self.chart_frame = ttk.LabelFrame(parent, text="Effort Preview", padding=5)
        self.chart_frame.pack(fill="both", expand=True)

        self.chart_canvas = ChartCanvas(self.chart_frame)

    def _set_gear(self, chainring: int, cog: int):
        """Set gear configuration."""
        self.chainring_var.set(str(chainring))
        self.cog_var.set(str(cog))

    def _get_gear_config(self) -> GearConfig:
        """Get current gear configuration."""
        return GearConfig(
            chainring=int(self.chainring_var.get()),
            cog=int(self.cog_var.get()),
            wheel_circumference_mm=2096
        )

    def _load_fit(self):
        """Load a FIT file."""
        filepath = filedialog.askopenfilename(
            title="Select FIT File",
            filetypes=[("FIT files", "*.fit"), ("All files", "*.*")]
        )

        if not filepath:
            return

        self.status_callback(f"Loading {filepath}...")

        try:
            self.fit_data = parse_fit_file(filepath)
            self.file_label.config(
                text=f"{self.fit_data.filename}\n"
                     f"Duration: {self.fit_data.total_duration_s:.0f}s\n"
                     f"Max Power: {self.fit_data.max_power_W:.0f}W"
            )

            # Show total rows for manual override
            self.total_rows_label.config(text=str(len(self.fit_data.records) - 1))

            # Auto-detect efforts
            self._detect_efforts()

            self.status_callback(f"Loaded {self.fit_data.filename}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load FIT file: {str(e)}")
            self.status_callback(f"Error: {str(e)}")

    def _detect_efforts(self):
        """Detect Flying 200 efforts in loaded FIT data."""
        if self.fit_data is None:
            return

        self.status_callback("Detecting efforts...")

        self.detected_efforts = detect_flying_efforts(
            self.fit_data.records,
            effort_type=200,
            verbose=False
        )

        # Update listbox
        self.effort_list.delete(0, tk.END)

        for i, effort in enumerate(self.detected_efforts):
            confidence_marker = "***" if effort.confidence >= 80 else "**" if effort.confidence >= 60 else "*"
            self.effort_list.insert(
                tk.END,
                f"Effort {i+1}: {effort.duration_s:.0f}s ({effort.confidence}%) {confidence_marker}"
            )

        self.status_callback(f"Found {len(self.detected_efforts)} efforts")

        # Auto-select the first effort
        if self.detected_efforts:
            self.effort_list.selection_set(0)
            self.effort_list.event_generate("<<ListboxSelect>>")

    def _create_manual_effort(self):
        """Create a manual Flying 200 from user-specified final row."""
        if self.fit_data is None:
            messagebox.showwarning("Warning", "Load a FIT file first")
            return

        raw = self.final_row_var.get().strip()
        if not raw:
            messagebox.showwarning("Warning", "Enter a Final Row number")
            return

        try:
            final_row = int(raw)
        except ValueError:
            messagebox.showerror("Error", "Final Row must be a whole number")
            return

        max_row = len(self.fit_data.records) - 1
        if final_row < 0 or final_row > max_row:
            messagebox.showerror("Error", f"Final Row must be between 0 and {max_row}")
            return

        self.status_callback("Creating manual effort...")

        effort = create_manual_effort(
            self.fit_data.records,
            final_row=final_row,
            effort_type=200,
            lookback_s=90.0,
            verbose=True,
        )

        if effort is None:
            messagebox.showerror("Error", "Could not create effort (window too short)")
            return

        # Append to efforts list and select it
        self.detected_efforts.append(effort)
        idx = len(self.detected_efforts) - 1

        self.effort_list.insert(
            tk.END,
            f"Effort {idx+1}: {effort.duration_s:.0f}s (MANUAL) row {final_row}"
        )

        # Select the new manual effort
        self.effort_list.selection_clear(0, tk.END)
        self.effort_list.selection_set(idx)
        self.effort_list.see(idx)
        self.effort_list.event_generate("<<ListboxSelect>>")

        self.status_callback(
            f"Manual effort created: rows {effort.start_index}-{effort.end_index}, "
            f"{effort.duration_s:.0f}s"
        )

    def _on_effort_selected(self, event=None):
        """Handle effort selection."""
        selection = self.effort_list.curselection()
        if not selection:
            return

        idx = selection[0]
        if idx >= len(self.detected_efforts):
            return

        self.selected_effort = self.detected_efforts[idx]
        effort = self.selected_effort

        # Update details
        details = (
            f"Duration: {effort.duration_s:.1f}s\n"
            f"Sprint: {effort.sprint_duration_s:.1f}s, Ramp: {effort.ramp_duration_s:.1f}s\n"
            f"Max Power: {effort.max_power_W:.0f}W\n"
            f"Avg Power (sprint): {effort.sprint_avg_power_W:.0f}W\n"
            f"Confidence: {effort.confidence}%"
        )
        self.effort_details.config(text=details)

        # Show preview chart
        self._show_effort_chart()

    def _show_effort_chart(self):
        """Show chart for selected effort."""
        if self.selected_effort is None or self.fit_data is None:
            return

        import matplotlib.pyplot as plt

        effort = self.selected_effort
        records = self.fit_data.records[effort.start_index:effort.end_index + 1]

        times = [r.elapsed_s - records[0].elapsed_s for r in records]
        powers = [r.power_W for r in records]
        speeds = [r.speed_kph for r in records]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)

        ax1.plot(times, powers, color=COLORS['power'], linewidth=1.5)
        ax1.axvline(effort.sprint_start_s - effort.start_time_s, color='red', linestyle='--', alpha=0.5, label='Sprint Start')
        ax1.set_ylabel('Power (W)')
        ax1.grid(True, alpha=0.3)
        ax1.legend(fontsize=8)

        ax2.plot(times, speeds, color=COLORS['speed'], linewidth=1.5)
        ax2.set_ylabel('Speed (km/h)')
        ax2.set_xlabel('Time (s)')
        ax2.grid(True, alpha=0.3)

        fig.suptitle(f'Effort Preview (Confidence: {effort.confidence}%)', fontsize=10)
        plt.tight_layout()

        self.chart_canvas.show_figure(fig)

    def _convert_to_distance(self):
        """Convert selected effort to distance profile."""
        if self.selected_effort is None or self.fit_data is None:
            messagebox.showwarning("Warning", "Please select an effort first")
            return

        gear = self._get_gear_config()
        self.status_callback("Converting to distance profile...")

        try:
            self.distance_profile = extract_effort_profile(
                self.fit_data.records,
                self.selected_effort.start_index,
                self.selected_effort.end_index,
                gear,
                align_to_finish=True,
                finish_line_m=895.0,
                ds=0.25
            )

            self.status_callback(f"Converted: {self.distance_profile.total_distance_m:.0f}m")

            # Show distance-based chart
            self._show_distance_chart()

        except Exception as e:
            messagebox.showerror("Error", f"Conversion failed: {str(e)}")

    def _show_distance_chart(self):
        """Show distance-based chart."""
        if self.distance_profile is None:
            return

        import matplotlib.pyplot as plt

        profile = self.distance_profile

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)

        ax1.plot(profile.s_m, profile.power_W, color=COLORS['power'], linewidth=1.5)
        ax1.set_ylabel('Power (W)')
        ax1.grid(True, alpha=0.3)

        ax2.plot(profile.s_m, profile.speed_mps * 3.6, color=COLORS['speed'], linewidth=1.5)
        ax2.set_ylabel('Speed (km/h)')
        ax2.set_xlabel('Distance (m)')
        ax2.grid(True, alpha=0.3)

        # Mark 200m zone
        ax1.axvline(695, color='red', linestyle='--', alpha=0.5)
        ax2.axvline(695, color='red', linestyle='--', alpha=0.5, label='200m Start')
        ax2.legend(fontsize=8)

        fig.suptitle(f'Distance Profile ({profile.total_distance_m:.0f}m, {profile.total_time_s:.1f}s)', fontsize=10)
        plt.tight_layout()

        self.chart_canvas.show_figure(fig)

    def _export_to_session(self):
        """Export distance profile to session."""
        if self.distance_profile is None:
            messagebox.showwarning("Warning", "Please convert to distance profile first")
            return

        # Convert DistanceProfile to Session Profile format
        # The simulation needs: s_m, y_m, CdA_m2, P_W
        # From FIT we have: s_m, power_W
        # Load y_m from config (default track positions) if available
        from core.session import Profile
        from core.config import interpolate_y_to_grid, get_default_y_profile, get_aero_defaults

        # Get the s_m grid from the distance profile
        s_m = self.distance_profile.s_m

        # Try to load default y_m positions from config
        s_default, y_default = get_default_y_profile()
        if len(s_default) > 2:
            # Interpolate default positions to our grid
            y_m = np.interp(s_m, s_default, y_default)
            y_source = "config defaults"
            y_range = f"{y_m.min():.1f}m - {y_m.max():.1f}m"
        else:
            # No config available, use black line
            y_m = np.zeros_like(s_m)
            y_source = "black line (no config)"
            y_range = "0m (all black line)"

        # Get default CdA from config
        aero_defaults = get_aero_defaults()
        default_cda = aero_defaults.get("CdA_seated", 0.24)

        profile = Profile(
            s_m=s_m,
            y_m=y_m,
            CdA_m2=np.full_like(s_m, default_cda),  # Use config default CdA
            P_W=self.distance_profile.power_W,
            source=f"FIT: {self.fit_data.filename}" if self.fit_data else "FIT Import",
        )

        # Set on session
        self.session.set_profile(profile)

        # Update main header
        self.header_callback()

        messagebox.showinfo(
            "Export Complete",
            f"Profile exported to session:\n"
            f"  Distance: {self.distance_profile.total_distance_m:.0f}m\n"
            f"  Duration: {self.distance_profile.total_time_s:.1f}s\n\n"
            f"Track positions (y_m): {y_source}\n"
            f"  Range: {y_range}\n\n"
            f"CdA: {default_cda:.2f} (from config)"
        )
        self.status_callback("Profile exported to session")

    def _export_to_csv(self):
        """Export distance profile to CSV file in standard format."""
        if self.distance_profile is None:
            messagebox.showwarning("Warning", "Please convert to distance profile first")
            return

        from core.config import get_default_y_profile, get_aero_defaults

        # Standard blackline positions: 0,10,20...690,695,700...880,890,895
        blackline_positions = [float(i) for i in range(0, 691, 10)] + [695.0] + [float(i) for i in range(700, 891, 10)] + [895.0]
        s_m = np.array(blackline_positions)

        # Interpolate power to standard positions
        profile_s = self.distance_profile.s_m
        profile_power = self.distance_profile.power_W
        s_min = profile_s.min()

        # Interpolate - np.interp will use edge values for out-of-range points
        P_W = np.interp(s_m, profile_s, profile_power)

        # Fill missing early points (before data starts) with first valid value
        if s_min > 0:
            first_valid_idx = np.searchsorted(s_m, s_min)
            if first_valid_idx > 0 and first_valid_idx < len(P_W):
                P_W[:first_valid_idx] = P_W[first_valid_idx]

        # Load default y_m positions from config (covers full 0-895 range)
        s_default, y_default = get_default_y_profile()
        if len(s_default) > 2:
            y_m = np.interp(s_m, s_default, y_default)
        else:
            y_m = np.zeros_like(s_m)

        # Get default CdA from config
        aero_defaults = get_aero_defaults()
        default_cda = aero_defaults.get("CdA_seated", 0.24)
        CdA_m2 = np.full_like(s_m, default_cda)

        # Ask user for save location
        default_name = "profile_f200.csv"
        if self.fit_data and self.fit_data.filename:
            base_name = os.path.splitext(os.path.basename(self.fit_data.filename))[0]
            default_name = f"{base_name}_profile.csv"

        filepath = filedialog.asksaveasfilename(
            title="Export Profile to CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not filepath:
            return

        try:
            # Write CSV in standard format: s_m,y_m,CdA_m2,P_W
            with open(filepath, 'w') as f:
                f.write("s_m,y_m,CdA_m2,P_W\n")
                for i in range(len(s_m)):
                    f.write(f"{int(s_m[i])},{y_m[i]:.2f},{CdA_m2[i]:.2f},{P_W[i]:.2f}\n")

            messagebox.showinfo(
                "Export Complete",
                f"Profile exported to:\n{filepath}\n\n"
                f"Points: {len(s_m)}\n"
                f"Distance: {s_m[0]:.0f}m - {s_m[-1]:.0f}m"
            )
            self.status_callback(f"Profile exported to {os.path.basename(filepath)}")

        except Exception as e:
            messagebox.showerror("Error", f"Export failed: {str(e)}")
