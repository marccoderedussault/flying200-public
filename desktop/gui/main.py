"""
Flying 200 V2 - Main Application Window

Main GUI application with:
- Persistent session header showing current profile and power curve
- Tab-based interface for different workflows
- Integration with all modules
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sys
import os

# Handle imports for both direct and package execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from core.session import Session
from core.track import BROMONT_250M, AVAILABLE_TRACKS, get_track_summary


# =============================================================================
# Main Application
# =============================================================================

class Flying200App:
    """
    Main Flying 200 V2 GUI Application.

    Features:
    - Persistent session header showing active data sources
    - Tab-based workflow: Simulation, FIT Analysis, Optimization
    - Professional charts with segment labels
    """

    def __init__(self, root: tk.Tk):
        """
        Initialize the application.

        Args:
            root: Tkinter root window
        """
        self.root = root
        self.root.title("Flying 200m V2 - Track Cycling Simulation")
        self.root.geometry("1600x900")

        # Start maximized on Windows
        try:
            self.root.state('zoomed')
        except tk.TclError:
            pass  # Not available on all platforms

        # Session state
        self.session = Session()
        self.session.track = BROMONT_250M

        # Build UI
        self._build_ui()

        # Update header
        self._update_header()

    def _build_ui(self):
        """Build the main application UI."""
        # === STATUS BAR (create first so status_callback works during tab init) ===
        self.status_frame = ttk.Frame(self.root)
        self.status_frame.pack(fill="x", side="bottom")

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.status_frame, textvariable=self.status_var).pack(side="left", padx=10)

        # === SESSION HEADER (Always Visible) ===
        self.header_frame = ttk.Frame(self.root, padding=5)
        self.header_frame.pack(fill="x", side="top")

        self._build_header()

        # === MAIN CONTENT (Tabs) ===
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        self._build_tabs()

    def _build_header(self):
        """Build the persistent session header."""
        # Left side: Session info
        info_frame = ttk.Frame(self.header_frame)
        info_frame.pack(side="left", fill="x", expand=True)

        # Session header label (shows current profile, power curve, track)
        self.header_label = ttk.Label(
            info_frame,
            text="",
            font=('Segoe UI', 10, 'bold'),
            foreground='#1F2937'
        )
        self.header_label.pack(side="left", padx=10)

        # Right side: Quick actions
        actions_frame = ttk.Frame(self.header_frame)
        actions_frame.pack(side="right")

        # Track selector with info button
        ttk.Label(actions_frame, text="Track:").pack(side="left", padx=5)
        self.track_var = tk.StringVar(value="Bromont")
        track_combo = ttk.Combobox(
            actions_frame,
            textvariable=self.track_var,
            values=list(AVAILABLE_TRACKS.keys()),
            state="readonly",
            width=12
        )
        track_combo.pack(side="left", padx=5)
        track_combo.bind("<<ComboboxSelected>>", self._on_track_changed)

        ttk.Button(actions_frame, text="?", width=2, command=self._show_track_info).pack(side="left", padx=2)

        # Separator
        ttk.Separator(self.header_frame, orient="horizontal").pack(fill="x", pady=5)

    def _build_tabs(self):
        """Build the main tab interface."""
        # Import tab modules (current_dir already in sys.path)
        from simulation_tab import SimulationTab
        from fit_tab import FitTab
        from power_curve_editor import PowerCurveEditor
        from optimizer_tab import OptimizerTab
        from track_tab import TrackTab
        from calibration_tab import CalibrationTab
        from state_tab import StateTab
        from config_tab import ConfigTab

        # === Tab 1: FIT Analysis (first - prerequisite for simulation) ===
        self.fit_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.fit_tab, text="FIT Analysis")

        self.fit_analysis = FitTab(
            self.fit_tab,
            self.session,
            status_callback=self._update_status,
            header_callback=self._update_header
        )

        # === Tab 2: Track View ===
        self.track_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.track_tab, text="Track View")

        self.track_view = TrackTab(
            self.track_tab,
            self.session,
            status_callback=self._update_status
        )

        # === Tab 3: Power Curves ===
        self.power_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.power_tab, text="Power Curves")

        self.power_editor = PowerCurveEditor(
            self.power_tab,
            self.session,
            status_callback=self._update_status
        )

        # === Tab 4: Simulation ===
        self.sim_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.sim_tab, text="Simulation")

        # === Tab 5: Calibration (create first so simulation can reference it) ===
        self.cal_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.cal_tab, text="Calibration")

        self.calibration = CalibrationTab(
            self.cal_tab,
            self.session,
            status_callback=self._update_status
        )

        # Now create simulation tab with calibration callback
        self.simulation_tab = SimulationTab(
            self.sim_tab,
            self.session,
            status_callback=self._update_status,
            header_callback=self._update_header,
            calibration_callback=self.calibration.set_simulation_result
        )

        # === Tab 6: Optimizer ===
        self.opt_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.opt_tab, text="Optimizer")

        self.optimizer = OptimizerTab(
            self.opt_tab,
            self.session,
            status_callback=self._update_status
        )

        # === Tab 7: Session State ===
        self.state_tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.state_tab_frame, text="State")

        self.state_view = StateTab(
            self.state_tab_frame,
            self.session,
            status_callback=self._update_status
        )

        # === Tab 8: Configuration ===
        self.config_tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.config_tab_frame, text="Config")

        self.config_view = ConfigTab(
            self.config_tab_frame,
            self.session,
            status_callback=self._update_status
        )

    def _on_track_changed(self, event=None):
        """Handle track selection change."""
        track_name = self.track_var.get()
        track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)
        self.session.track = track
        self._update_header()

    def _show_track_info(self):
        """Show information about available tracks."""
        info_lines = ["Available Tracks:\n"]
        for _, track in AVAILABLE_TRACKS.items():
            info_lines.append(f"\n{get_track_summary(track)}\n")

        messagebox.showinfo("Track Information", "".join(info_lines))

    def _update_header(self):
        """Update the session header display."""
        self.header_label.config(text=self.session.header_text)

    def _update_status(self, message: str):
        """Update status bar message."""
        self.status_var.set(message)
        self.root.update()


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """Main entry point for Flying 200 V2 GUI."""
    import signal

    root = tk.Tk()

    # Handle Ctrl+C gracefully
    def on_sigint(_signum, _frame):
        root.quit()
        root.destroy()

    signal.signal(signal.SIGINT, on_sigint)

    # Set theme
    try:
        style = ttk.Style()
        # Use clam theme for cleaner look
        if 'clam' in style.theme_names():
            style.theme_use('clam')
    except tk.TclError:
        pass

    app = Flying200App(root)

    # Periodically check for signals (needed on Windows)
    def check_signals():
        root.after(100, check_signals)
    root.after(100, check_signals)

    root.mainloop()


if __name__ == "__main__":
    main()
