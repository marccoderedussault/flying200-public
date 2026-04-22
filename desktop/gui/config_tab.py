"""
Flying 200 V2 - Configuration Tab

Central location for ALL default values.
No hidden hardcoded fallbacks - everything is visible and editable here.

Sections:
- Environment Parameters (rho, C_rr, drivetrain_eff, mass)
- Aero Defaults (CdA seated/standing, bend factor)
- Simulation Parameters (ds, v0, s_total)
- Default Track
- Default Power Curves
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable, Dict
import sys
import os

# Handle imports for both direct and package execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from core.config import (
    get_environment_defaults, save_environment_defaults,
    get_aero_defaults, save_aero_defaults,
    get_simulation_defaults, save_simulation_defaults,
    get_default_track, save_default_track,
    get_default_power_curves, save_power_curves_to_config,
    reset_to_builtin_defaults, BUILTIN_DEFAULTS,
    get_config_path,
)
from core.track import AVAILABLE_TRACKS
from core.session import Session


class ConfigTab:
    """
    Configuration tab for all default values.

    Shows all configurable defaults in one place so users know
    exactly what values are being used when no explicit value is set.
    """

    def __init__(
        self,
        parent: ttk.Frame,
        session: Session,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        self.parent = parent
        self.session = session
        self.status_callback = status_callback or (lambda x: None)

        # Build UI
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        """Build the configuration tab UI."""
        # Main scrollable container
        canvas = tk.Canvas(self.parent)
        scrollbar = ttk.Scrollbar(self.parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Config file info
        info_frame = ttk.Frame(scrollable_frame)
        info_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(
            info_frame,
            text=f"Config file: {get_config_path()}",
            font=('Segoe UI', 9),
            foreground='#6B7280'
        ).pack(side="left")

        # === ENVIRONMENT PARAMETERS ===
        env_frame = ttk.LabelFrame(scrollable_frame, text="Environment Parameters", padding=10)
        env_frame.pack(fill="x", padx=10, pady=5)
        self._build_environment_section(env_frame)

        # === AERO DEFAULTS ===
        aero_frame = ttk.LabelFrame(scrollable_frame, text="Aero Defaults", padding=10)
        aero_frame.pack(fill="x", padx=10, pady=5)
        self._build_aero_section(aero_frame)

        # === SIMULATION PARAMETERS ===
        sim_frame = ttk.LabelFrame(scrollable_frame, text="Simulation Parameters", padding=10)
        sim_frame.pack(fill="x", padx=10, pady=5)
        self._build_simulation_section(sim_frame)

        # === TRACK DEFAULTS ===
        track_frame = ttk.LabelFrame(scrollable_frame, text="Default Track", padding=10)
        track_frame.pack(fill="x", padx=10, pady=5)
        self._build_track_section(track_frame)

        # === POWER CURVES ===
        power_frame = ttk.LabelFrame(scrollable_frame, text="Default Power Curves", padding=10)
        power_frame.pack(fill="x", padx=10, pady=5)
        self._build_power_curves_section(power_frame)

        # === BUTTONS ===
        buttons_frame = ttk.Frame(scrollable_frame)
        buttons_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(buttons_frame, text="Save All", command=self._save_all).pack(side="left", padx=5)
        ttk.Button(buttons_frame, text="Reload", command=self._load_values).pack(side="left", padx=5)
        ttk.Button(buttons_frame, text="Reset to Built-in Defaults", command=self._reset_to_defaults).pack(side="left", padx=5)

    def _build_environment_section(self, parent: ttk.Frame):
        """Build environment parameters section."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)

        # Air density
        ttk.Label(row, text="Air Density (kg/m3):").pack(side="left", padx=5)
        self.rho_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.rho_var, width=10).pack(side="left", padx=5)

        # Rolling resistance
        ttk.Label(row, text="C_rr:").pack(side="left", padx=15)
        self.crr_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.crr_var, width=10).pack(side="left", padx=5)

        row2 = ttk.Frame(parent)
        row2.pack(fill="x", pady=2)

        # Drivetrain efficiency
        ttk.Label(row2, text="Drivetrain Eff:").pack(side="left", padx=5)
        self.eff_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.eff_var, width=10).pack(side="left", padx=5)

        # Rider mass
        ttk.Label(row2, text="System Mass (kg):").pack(side="left", padx=15)
        self.mass_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.mass_var, width=10).pack(side="left", padx=5)

    def _build_aero_section(self, parent: ttk.Frame):
        """Build aero defaults section."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)

        # CdA seated
        ttk.Label(row, text="CdA Seated (m2):").pack(side="left", padx=5)
        self.cda_seated_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.cda_seated_var, width=10).pack(side="left", padx=5)

        # CdA standing
        ttk.Label(row, text="CdA Standing (m2):").pack(side="left", padx=15)
        self.cda_standing_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.cda_standing_var, width=10).pack(side="left", padx=5)

        # Bend factor
        ttk.Label(row, text="Bend Factor:").pack(side="left", padx=15)
        self.cda_bend_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.cda_bend_var, width=10).pack(side="left", padx=5)

        # Explanation
        note = ttk.Label(
            parent,
            text="Note: Bend factor < 1 means lower CdA in bends (tucked position). Profile CdA is for bends; straights = CdA / bend_factor.",
            font=('Segoe UI', 8),
            foreground='#6B7280',
            wraplength=500
        )
        note.pack(anchor="w", padx=5, pady=5)

    def _build_simulation_section(self, parent: ttk.Frame):
        """Build simulation parameters section."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)

        # Grid resolution
        ttk.Label(row, text="Grid Resolution (m):").pack(side="left", padx=5)
        self.ds_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.ds_var, width=10).pack(side="left", padx=5)

        # Initial velocity
        ttk.Label(row, text="Initial V0 (m/s):").pack(side="left", padx=15)
        self.v0_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.v0_var, width=10).pack(side="left", padx=5)

        # Total distance
        ttk.Label(row, text="Total Distance (m):").pack(side="left", padx=15)
        self.s_total_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.s_total_var, width=10).pack(side="left", padx=5)

    def _build_track_section(self, parent: ttk.Frame):
        """Build track defaults section."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)

        ttk.Label(row, text="Default Track:").pack(side="left", padx=5)
        self.track_var = tk.StringVar()
        track_combo = ttk.Combobox(
            row,
            textvariable=self.track_var,
            values=list(AVAILABLE_TRACKS.keys()),
            state="readonly",
            width=15
        )
        track_combo.pack(side="left", padx=5)

    def _build_power_curves_section(self, parent: ttk.Frame):
        """Build power curves section with editable tables.

        Durations: 1-15s in 1s intervals, then 20, 25, 30, 40, 50, 60, 70, 80, 90s
        """
        # Note about power curves
        note = ttk.Label(
            parent,
            text="Power curves define max power at each duration. Used by Optimizer when no power curves loaded in session.",
            font=('Segoe UI', 8),
            foreground='#6B7280',
            wraplength=500
        )
        note.pack(anchor="w", padx=5, pady=5)

        # Full duration list: 1-15s (1s intervals) + extended durations
        durations = list(range(1, 16)) + [20, 25, 30, 40, 50, 60, 70, 80, 90]

        # Scrollable container for the two columns
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True, pady=5)

        # Canvas with scrollbar for the power curve tables
        canvas = tk.Canvas(container, height=300)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Two columns for seated and standing
        cols_frame = ttk.Frame(scrollable)
        cols_frame.pack(fill="x", pady=5)

        # Seated column
        seated_frame = ttk.LabelFrame(cols_frame, text="Seated", padding=5)
        seated_frame.pack(side="left", fill="both", expand=True, padx=5)

        self.seated_entries = {}
        for duration in durations:
            row = ttk.Frame(seated_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"{duration}s:", width=5).pack(side="left")
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=8).pack(side="left", padx=2)
            ttk.Label(row, text="W").pack(side="left")
            self.seated_entries[duration] = var

        # Standing column
        standing_frame = ttk.LabelFrame(cols_frame, text="Standing", padding=5)
        standing_frame.pack(side="left", fill="both", expand=True, padx=5)

        self.standing_entries = {}
        for duration in durations:
            row = ttk.Frame(standing_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"{duration}s:", width=5).pack(side="left")
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=8).pack(side="left", padx=2)
            ttk.Label(row, text="W").pack(side="left")
            self.standing_entries[duration] = var

        # Buttons for power curves
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", pady=10)

        ttk.Button(
            btn_frame, text="Import from Config",
            command=self._import_power_curves_from_config
        ).pack(side="left", padx=5)

        ttk.Button(
            btn_frame, text="Apply to Session",
            command=self._apply_power_curves_to_session
        ).pack(side="left", padx=5)

        ttk.Button(
            btn_frame, text="Save to Config",
            command=self._save_power_curves_only
        ).pack(side="left", padx=5)

    def _load_values(self):
        """Load all values from config."""
        # Environment
        env = get_environment_defaults()
        self.rho_var.set(str(env.get("rho_kg_m3", 1.1627)))
        self.crr_var.set(str(env.get("c_rr", 0.002)))
        self.eff_var.set(str(env.get("drivetrain_eff", 0.98)))
        self.mass_var.set(str(env.get("rider_mass_kg", 92.0)))

        # Aero
        aero = get_aero_defaults()
        self.cda_seated_var.set(str(aero.get("CdA_seated", 0.24)))
        self.cda_standing_var.set(str(aero.get("CdA_standing", 0.38)))
        self.cda_bend_var.set(str(aero.get("CdA_bend_factor", 0.97)))

        # Simulation
        sim = get_simulation_defaults()
        self.ds_var.set(str(sim.get("ds_m", 0.25)))
        self.v0_var.set(str(sim.get("v0_m_s", 5.0)))
        self.s_total_var.set(str(sim.get("s_total_m", 895.0)))

        # Track
        self.track_var.set(get_default_track())

        # Power curves
        power = get_default_power_curves()
        if power is None:
            power = BUILTIN_DEFAULTS["power_curves"]

        seated = power.get("seated", {})
        standing = power.get("standing", {})

        for duration, var in self.seated_entries.items():
            # Handle both int and str keys from JSON
            val = seated.get(duration) or seated.get(str(duration), 0)
            var.set(str(int(val)))

        for duration, var in self.standing_entries.items():
            val = standing.get(duration) or standing.get(str(duration), 0)
            var.set(str(int(val)))

        self.status_callback("Config loaded")

    def _save_all(self):
        """Save all values to config."""
        try:
            # Environment
            save_environment_defaults({
                "rho_kg_m3": float(self.rho_var.get()),
                "c_rr": float(self.crr_var.get()),
                "drivetrain_eff": float(self.eff_var.get()),
                "rider_mass_kg": float(self.mass_var.get()),
            })

            # Aero
            save_aero_defaults({
                "CdA_seated": float(self.cda_seated_var.get()),
                "CdA_standing": float(self.cda_standing_var.get()),
                "CdA_bend_factor": float(self.cda_bend_var.get()),
            })

            # Simulation
            save_simulation_defaults({
                "ds_m": float(self.ds_var.get()),
                "v0_m_s": float(self.v0_var.get()),
                "s_total_m": float(self.s_total_var.get()),
            })

            # Track
            save_default_track(self.track_var.get())

            # Power curves
            seated = {d: int(var.get()) for d, var in self.seated_entries.items()}
            standing = {d: int(var.get()) for d, var in self.standing_entries.items()}
            save_power_curves_to_config(seated, standing)

            self.status_callback("All config saved")
            messagebox.showinfo("Saved", "Configuration saved successfully.")

        except ValueError as e:
            messagebox.showerror("Invalid Value", f"Please enter valid numbers:\n{e}")

    def _reset_to_defaults(self):
        """Reset all values to built-in defaults."""
        if messagebox.askyesno("Reset to Defaults", "Reset all config to built-in defaults?"):
            reset_to_builtin_defaults()
            self._load_values()
            self.status_callback("Reset to built-in defaults")

    def _import_power_curves_from_config(self):
        """Import power curves from saved config into the editor."""
        power = get_default_power_curves()
        if power is None:
            power = BUILTIN_DEFAULTS["power_curves"]

        seated = power.get("seated", {})
        standing = power.get("standing", {})

        for duration, var in self.seated_entries.items():
            val = seated.get(duration) or seated.get(str(duration), 0)
            var.set(str(int(val)))

        for duration, var in self.standing_entries.items():
            val = standing.get(duration) or standing.get(str(duration), 0)
            var.set(str(int(val)))

        self.status_callback("Power curves imported from config")

    def _apply_power_curves_to_session(self):
        """Apply edited power curves to the current session."""
        from core.session import PowerCurves, PowerCurve

        try:
            seated = {d: int(var.get()) for d, var in self.seated_entries.items()}
            standing = {d: int(var.get()) for d, var in self.standing_entries.items()}

            power_curves = PowerCurves(
                seated=PowerCurve.from_dict(seated, source="config_tab"),
                standing=PowerCurve.from_dict(standing, source="config_tab")
            )
            self.session.power_curves = power_curves
            self.status_callback("Power curves applied to session")
            messagebox.showinfo("Applied", "Power curves applied to current session.\nOptimizer will use these values.")

        except ValueError as e:
            messagebox.showerror("Invalid Value", f"Please enter valid numbers:\n{e}")

    def _save_power_curves_only(self):
        """Save only power curves to config (not other settings)."""
        try:
            seated = {d: int(var.get()) for d, var in self.seated_entries.items()}
            standing = {d: int(var.get()) for d, var in self.standing_entries.items()}
            save_power_curves_to_config(seated, standing)
            self.status_callback("Power curves saved to config")

        except ValueError as e:
            messagebox.showerror("Invalid Value", f"Please enter valid numbers:\n{e}")
