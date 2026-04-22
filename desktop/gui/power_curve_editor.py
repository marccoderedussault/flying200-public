"""
Flying 200 V2 - Power Curve Editor

Build power curves from:
1. Manual entry
2. Import from FIT file
3. Composite building from multiple efforts

Supports separate curves for seated and standing positions.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Dict, Optional, Callable, List
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

from fit.parser import parse_fit_file, extract_power_curve
from core.session import Session


# Standard power curve durations: every second 1-30, then 40, 50, 60, 70
STANDARD_DURATIONS = list(range(1, 31)) + [40, 50, 60, 70]


# =============================================================================
# Power Curve Editor Tab
# =============================================================================

class PowerCurveEditor:
    """
    Power curve editor for building athlete power profiles.

    Features:
    - Manual entry for each duration
    - Import best powers from FIT files
    - Composite building from multiple sources
    - Separate seated/standing curves
    """

    def __init__(
        self,
        parent: ttk.Frame,
        session: Session,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize power curve editor.

        Args:
            parent: Parent frame
            session: Session object
            status_callback: Status update callback
        """
        self.parent = parent
        self.session = session
        self.status_callback = status_callback or (lambda x: None)

        # Power curve data
        self.seated_curve: Dict[int, float] = {}
        self.standing_curve: Dict[int, float] = {}

        # Entry widgets
        self.seated_entries: Dict[int, tk.Entry] = {}
        self.standing_entries: Dict[int, tk.Entry] = {}

        # Build UI
        self._build_ui()

    def _build_ui(self):
        """Build the power curve editor UI."""
        # Main container with scrolling
        canvas = tk.Canvas(self.parent)
        scrollbar = ttk.Scrollbar(self.parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, padding=10)

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

        # === Header with description ===
        header_frame = ttk.Frame(scrollable_frame)
        header_frame.pack(fill="x", pady=5)

        ttk.Label(
            header_frame,
            text="Power Curve Editor",
            font=('Segoe UI', 12, 'bold')
        ).pack(anchor="w")

        ttk.Label(
            header_frame,
            text="Enter your maximum sustainable power (watts) for each duration.\n"
                 "Seated = aero position, Standing = out of saddle for max power.",
            font=('Segoe UI', 9),
            foreground='#666666'
        ).pack(anchor="w", pady=(2, 10))

        # === Entry Grid ===
        grid_frame = ttk.LabelFrame(scrollable_frame, text="Power Values (Watts)", padding=10)
        grid_frame.pack(fill="x", pady=10)

        self._build_entry_grid(grid_frame)

        # === Import Section ===
        import_frame = ttk.LabelFrame(scrollable_frame, text="Import from FIT File", padding=10)
        import_frame.pack(fill="x", pady=10)

        self._build_import_section(import_frame)

        # === Actions ===
        actions_frame = ttk.LabelFrame(scrollable_frame, text="Actions", padding=10)
        actions_frame.pack(fill="x", pady=10)

        ttk.Label(
            actions_frame,
            text="Apply: Save curves to current session for simulation\n"
                 "Load/Save: Import or export power curves as CSV files",
            font=('Segoe UI', 9),
            foreground='#666666'
        ).pack(anchor="w", pady=(0, 5))

        btn_row = ttk.Frame(actions_frame)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Apply to Session", command=self._apply_to_session).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Clear All", command=self._clear_all).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Load from File", command=self._load_from_file).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Save to File", command=self._save_to_file).pack(side="left", padx=5)

    def _build_entry_grid(self, parent: ttk.Frame):
        """Build the power entry grid in multi-column layout."""
        # Organize durations into groups for better layout
        # 1-10s, 11-20s, 21-30s, then 40-70s
        groups = [
            ("1-10s", STANDARD_DURATIONS[0:10]),
            ("11-20s", STANDARD_DURATIONS[10:20]),
            ("21-30s", STANDARD_DURATIONS[20:30]),
            ("Extended", STANDARD_DURATIONS[30:]),  # 40, 50, 60, 70
        ]

        # Create a frame for each group, laid out horizontally
        for group_idx, (group_name, durations) in enumerate(groups):
            group_frame = ttk.LabelFrame(parent, text=group_name, padding=5)
            group_frame.grid(row=0, column=group_idx, padx=5, pady=5, sticky="n")

            # Header row
            ttk.Label(group_frame, text="Dur", font=('Segoe UI', 8, 'bold'), width=4).grid(row=0, column=0, padx=2, pady=1)
            ttk.Label(group_frame, text="Seated", font=('Segoe UI', 8, 'bold'), width=6).grid(row=0, column=1, padx=2, pady=1)
            ttk.Label(group_frame, text="Stand", font=('Segoe UI', 8, 'bold'), width=6).grid(row=0, column=2, padx=2, pady=1)

            # Entry rows
            for i, duration in enumerate(durations, start=1):
                # Duration label
                ttk.Label(group_frame, text=f"{duration}s", width=4).grid(row=i, column=0, padx=2, pady=1)

                # Seated entry
                seated_entry = ttk.Entry(group_frame, width=6)
                seated_entry.grid(row=i, column=1, padx=2, pady=1)
                self.seated_entries[duration] = seated_entry

                # Standing entry
                standing_entry = ttk.Entry(group_frame, width=6)
                standing_entry.grid(row=i, column=2, padx=2, pady=1)
                self.standing_entries[duration] = standing_entry

    def _build_import_section(self, parent: ttk.Frame):
        """Build FIT import section."""
        # Description
        ttk.Label(
            parent,
            text="Extract best power values from a FIT file effort.\n"
                 "Import multiple FIT files to build a composite power curve.",
            font=('Segoe UI', 9),
            foreground='#666666'
        ).pack(anchor="w", pady=(0, 5))

        # Import button
        row1 = ttk.Frame(parent)
        row1.pack(fill="x", pady=2)

        ttk.Button(row1, text="Import from FIT File...", command=self._import_from_fit).pack(side="left", padx=5)

        # Target position selection
        row2 = ttk.Frame(parent)
        row2.pack(fill="x", pady=2)

        ttk.Label(row2, text="Import to position:").pack(side="left", padx=5)
        self.import_mode_var = tk.StringVar(value="seated")
        ttk.Radiobutton(row2, text="Seated", variable=self.import_mode_var, value="seated").pack(side="left", padx=5)
        ttk.Radiobutton(row2, text="Standing", variable=self.import_mode_var, value="standing").pack(side="left", padx=5)
        ttk.Radiobutton(row2, text="Both", variable=self.import_mode_var, value="both").pack(side="left", padx=5)

        # Merge mode
        row3 = ttk.Frame(parent)
        row3.pack(fill="x", pady=2)

        ttk.Label(row3, text="When values exist:").pack(side="left", padx=5)
        self.merge_mode_var = tk.StringVar(value="max")
        ttk.Radiobutton(row3, text="Keep Maximum", variable=self.merge_mode_var, value="max").pack(side="left", padx=5)
        ttk.Radiobutton(row3, text="Replace All", variable=self.merge_mode_var, value="replace").pack(side="left", padx=5)

        ttk.Label(
            parent,
            text="Keep Maximum: useful for building composite curves from multiple efforts",
            font=('Segoe UI', 8, 'italic'),
            foreground='#888888'
        ).pack(anchor="w", pady=(2, 0))

        # Info label (shows import status)
        self.import_info = ttk.Label(parent, text="", foreground='#006600')
        self.import_info.pack(fill="x", pady=5)

    def _import_from_fit(self):
        """Import power curve from FIT file."""
        filepath = filedialog.askopenfilename(
            title="Select FIT File",
            filetypes=[("FIT files", "*.fit"), ("All files", "*.*")]
        )

        if not filepath:
            return

        self.status_callback(f"Importing from {filepath}...")

        try:
            fit_data = parse_fit_file(filepath)
            power_curve = extract_power_curve(fit_data.records, STANDARD_DURATIONS)

            mode = self.import_mode_var.get()
            merge = self.merge_mode_var.get()

            imported = 0
            for duration, power in power_curve.items():
                if power <= 0:
                    continue

                if mode in ("seated", "both"):
                    self._set_power_value("seated", duration, power, merge)
                    imported += 1

                if mode in ("standing", "both"):
                    self._set_power_value("standing", duration, power, merge)
                    imported += 1

            self.import_info.config(text=f"Imported {imported} values from {fit_data.filename}")
            self.status_callback(f"Imported {imported} power values")

        except Exception as e:
            messagebox.showerror("Error", f"Import failed: {str(e)}")
            self.status_callback(f"Error: {str(e)}")

    def _set_power_value(self, curve_type: str, duration: int, power: float, merge: str = "max"):
        """Set a power value in the specified curve."""
        if curve_type == "seated":
            entries = self.seated_entries
            curve = self.seated_curve
        else:
            entries = self.standing_entries
            curve = self.standing_curve

        if duration not in entries:
            return

        current_val = 0
        try:
            current_val = float(entries[duration].get())
        except (ValueError, AttributeError):
            pass

        if merge == "max":
            new_val = max(current_val, power)
        else:
            new_val = power

        entries[duration].delete(0, tk.END)
        entries[duration].insert(0, f"{new_val:.0f}")
        curve[duration] = new_val

    def _get_curve_from_entries(self, entries: Dict[int, tk.Entry]) -> Dict[int, float]:
        """Extract power curve from entry widgets."""
        curve = {}
        for duration, entry in entries.items():
            try:
                val = float(entry.get())
                if val > 0:
                    curve[duration] = val
            except (ValueError, AttributeError):
                pass
        return curve

    def _apply_to_session(self):
        """Apply power curves to session."""
        self.seated_curve = self._get_curve_from_entries(self.seated_entries)
        self.standing_curve = self._get_curve_from_entries(self.standing_entries)

        if not self.seated_curve and not self.standing_curve:
            messagebox.showwarning("Warning", "No power values entered")
            return

        # Use the Session's set_power_curves method
        self.session.set_power_curves(
            seated_dict=self.seated_curve,
            standing_dict=self.standing_curve,
            source="Manual/FIT Import"
        )

        messagebox.showinfo("Success", "Power curves applied to session")
        self.status_callback("Power curves applied")

    def _clear_all(self):
        """Clear all power values."""
        for entry in self.seated_entries.values():
            entry.delete(0, tk.END)
        for entry in self.standing_entries.values():
            entry.delete(0, tk.END)

        self.seated_curve = {}
        self.standing_curve = {}

        self.status_callback("Power curves cleared")

    def _load_from_file(self):
        """Load power curves from CSV file."""
        filepath = filedialog.askopenfilename(
            title="Load Power Curve",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not filepath:
            return

        try:
            import pandas as pd
            df = pd.read_csv(filepath)

            for _, row in df.iterrows():
                duration = int(row.get('duration_s', 0))
                if duration <= 0:
                    continue

                if 'seated_W' in df.columns and duration in self.seated_entries:
                    val = row.get('seated_W', 0)
                    if val > 0:
                        self.seated_entries[duration].delete(0, tk.END)
                        self.seated_entries[duration].insert(0, f"{val:.0f}")

                if 'standing_W' in df.columns and duration in self.standing_entries:
                    val = row.get('standing_W', 0)
                    if val > 0:
                        self.standing_entries[duration].delete(0, tk.END)
                        self.standing_entries[duration].insert(0, f"{val:.0f}")

            self.status_callback(f"Loaded from {filepath}")

        except Exception as e:
            messagebox.showerror("Error", f"Load failed: {str(e)}")

    def _save_to_file(self):
        """Save power curves to CSV file."""
        filepath = filedialog.asksaveasfilename(
            title="Save Power Curve",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not filepath:
            return

        try:
            seated = self._get_curve_from_entries(self.seated_entries)
            standing = self._get_curve_from_entries(self.standing_entries)

            rows = []
            for duration in STANDARD_DURATIONS:
                rows.append({
                    'duration_s': duration,
                    'seated_W': seated.get(duration, 0),
                    'standing_W': standing.get(duration, 0),
                })

            import pandas as pd
            df = pd.DataFrame(rows)
            df.to_csv(filepath, index=False)

            self.status_callback(f"Saved to {filepath}")

        except Exception as e:
            messagebox.showerror("Error", f"Save failed: {str(e)}")
