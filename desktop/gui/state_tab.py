"""
Flying 200 V2 - Session State Tab

Shows live session state including:
- Profile summary and data
- Track info
- Power curves status
- Last simulation result with parameters
- Session status

Auto-refreshes when session changes via observer pattern.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
import sys
import os
import numpy as np

# Handle imports for both direct and package execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from core.session import Session


# Standard blackline positions (10m intervals with 695m start marker)
BLACKLINE_POSITIONS = [float(i) for i in range(0, 691, 10)] + [695.0] + [float(i) for i in range(700, 896, 10)]


class StateTab:
    """
    Session state viewer.

    Shows current session state and auto-refreshes when data changes.
    Provides visibility into what data the simulation is using.
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

        # Register as observer
        self.session.add_observer(self._on_session_changed)

        # Build UI
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        """Build the state tab UI with side-by-side layout."""
        # Top bar with refresh button
        top_frame = ttk.Frame(self.parent)
        top_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(top_frame, text="Refresh", command=self._refresh).pack(side="left")
        self.status_label = ttk.Label(top_frame, text="", foreground='#059669')
        self.status_label.pack(side="left", padx=10)

        # Main container - horizontal split
        main_frame = ttk.Frame(self.parent)
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # === LEFT SIDE: Summary panels (scrollable) ===
        left_container = ttk.Frame(main_frame)
        left_container.pack(side="left", fill="y", padx=(0, 5))

        canvas = tk.Canvas(left_container, width=380)
        scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Mouse wheel scrolling for left panel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)

        # === SESSION STATUS ===
        status_frame = ttk.LabelFrame(self.scrollable_frame, text="Session Status", padding=10)
        status_frame.pack(fill="x", padx=5, pady=5)
        self._build_status_section(status_frame)

        # === PROFILE SUMMARY ===
        profile_frame = ttk.LabelFrame(self.scrollable_frame, text="Profile", padding=10)
        profile_frame.pack(fill="x", padx=5, pady=5)
        self._build_profile_section(profile_frame)

        # === TRACK INFO ===
        track_frame = ttk.LabelFrame(self.scrollable_frame, text="Track", padding=10)
        track_frame.pack(fill="x", padx=5, pady=5)
        self._build_track_section(track_frame)

        # === POWER CURVES ===
        power_frame = ttk.LabelFrame(self.scrollable_frame, text="Power Curves", padding=10)
        power_frame.pack(fill="x", padx=5, pady=5)
        self._build_power_section(power_frame)

        # === LAST SIMULATION ===
        sim_frame = ttk.LabelFrame(self.scrollable_frame, text="Last Simulation Result", padding=10)
        sim_frame.pack(fill="x", padx=5, pady=5)
        self._build_simulation_section(sim_frame)

        # === RIGHT SIDE: Data table (always visible, full height) ===
        self.data_frame = ttk.LabelFrame(main_frame, text="Profile Data (10m Blackline Intervals)", padding=10)
        self.data_frame.pack(side="right", fill="both", expand=True)
        self._build_data_section(self.data_frame)

    def _build_status_section(self, parent: ttk.Frame):
        """Build session status display."""
        self.session_status_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.session_status_var, font=('Consolas', 10)).pack(anchor="w")

    def _build_profile_section(self, parent: ttk.Frame):
        """Build profile summary display."""
        self.profile_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.profile_var, font=('Consolas', 10)).pack(anchor="w")

    def _build_track_section(self, parent: ttk.Frame):
        """Build track info display."""
        self.track_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.track_var, font=('Consolas', 10)).pack(anchor="w")

    def _build_power_section(self, parent: ttk.Frame):
        """Build power curves summary display."""
        self.power_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.power_var, font=('Consolas', 10)).pack(anchor="w")

    def _build_simulation_section(self, parent: ttk.Frame):
        """Build last simulation result display."""
        self.sim_result_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.sim_result_var, font=('Consolas', 10)).pack(anchor="w")

        # Simulation parameters
        self.sim_params_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.sim_params_var, font=('Consolas', 9), foreground='#6B7280').pack(anchor="w", pady=(5, 0))

    def _build_data_section(self, parent: ttk.Frame):
        """Build data table (always visible on right side)."""
        # Treeview for data with wider columns
        columns = ("s_m", "y_m", "CdA_m2", "P_W")
        self.data_tree = ttk.Treeview(parent, columns=columns, show="headings")

        # Column headers with better widths
        col_widths = {"s_m": 80, "y_m": 100, "CdA_m2": 100, "P_W": 100}
        for col in columns:
            self.data_tree.heading(col, text=col)
            self.data_tree.column(col, width=col_widths.get(col, 100), anchor="center", stretch=True)

        # Scrollbars
        v_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.data_tree.yview)
        h_scroll = ttk.Scrollbar(parent, orient="horizontal", command=self.data_tree.xview)
        self.data_tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        # Grid layout for proper expansion
        self.data_tree.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

    def _populate_data_table(self):
        """Populate the data table with profile data at standard blackline intervals."""
        # Clear existing
        for item in self.data_tree.get_children():
            self.data_tree.delete(item)

        if self.session.profile is None:
            self.data_tree.insert("", "end", values=("No profile loaded", "", "", ""))
            return

        profile = self.session.profile

        # Interpolate profile data to standard blackline positions
        blackline_s = np.array(BLACKLINE_POSITIONS)

        # Filter to profile's actual range
        s_min, s_max = profile.s_m.min(), profile.s_m.max()
        valid_positions = blackline_s[(blackline_s >= s_min) & (blackline_s <= s_max)]

        # Interpolate each field to blackline positions
        y_interp = np.interp(valid_positions, profile.s_m, profile.y_m)
        cda_interp = np.interp(valid_positions, profile.s_m, profile.CdA_m2)
        p_interp = np.interp(valid_positions, profile.s_m, profile.P_W)

        for i, s in enumerate(valid_positions):
            values = (
                f"{s:.0f}",
                f"{y_interp[i]:.2f}",
                f"{cda_interp[i]:.4f}",
                f"{p_interp[i]:.0f}",
            )
            self.data_tree.insert("", "end", values=values)

    def _on_session_changed(self):
        """Called when session data changes."""
        self._refresh()

    def _refresh(self):
        """Refresh all displays."""
        # Session status
        self.session_status_var.set(self.session.status_text)

        # Profile
        if self.session.profile:
            p = self.session.profile
            y_min, y_max = p.y_m.min(), p.y_m.max()
            cda_min, cda_max = p.CdA_m2.min(), p.CdA_m2.max()
            p_min, p_max = p.P_W.min(), p.P_W.max()

            profile_text = (
                f"Source: {p.source}\n"
                f"Points: {len(p.s_m)}\n"
                f"Distance: {p.s_m[0]:.0f}m - {p.s_m[-1]:.0f}m\n"
                f"y_m range: {y_min:.2f}m - {y_max:.2f}m\n"
                f"CdA range: {cda_min:.4f} - {cda_max:.4f} m2\n"
                f"Power range: {p_min:.0f}W - {p_max:.0f}W"
            )
        else:
            profile_text = "(No profile loaded)"

        self.profile_var.set(profile_text)

        # Track
        track = self.session.track
        track_text = (
            f"Name: {track.name}\n"
            f"Length: {track.length_m:.0f}m\n"
            f"Straights: {track.straight_length_m:.1f}m\n"
            f"Turn radius: {track.turn_radius_m:.2f}m\n"
            f"Banking: {track.banking_straight_deg:.1f} deg (straight), {track.banking_turn_deg:.1f} deg (turn)\n"
            f"Width: {track.width_m:.1f}m"
        )
        self.track_var.set(track_text)

        # Power curves
        if self.session.power_curves:
            pc = self.session.power_curves
            seated_pts = len(pc.seated.durations_s)
            standing_pts = len(pc.standing.durations_s)
            power_text = (
                f"Source: {pc.source_description}\n"
                f"Seated: {seated_pts} points\n"
                f"Standing: {standing_pts} points"
            )
        else:
            power_text = "(No power curves loaded - will use config defaults)"

        self.power_var.set(power_text)

        # Last simulation
        if self.session.last_simulation_result:
            r = self.session.last_simulation_result
            sim_text = (
                f"T_200: {r['T_200']:.3f} s\n"
                f"T_total: {r['T_total']:.3f} s\n"
                f"Entry Speed: {r['v_200_entry'] * 3.6:.1f} km/h\n"
                f"Exit Speed: {r['v_200_exit'] * 3.6:.1f} km/h\n"
                f"Avg Power (200m): {r['P_avg_sprint']:.0f} W\n"
                f"Line Cost: {r['line_cost_200']:.4f} s"
            )
            self.sim_result_var.set(sim_text)

            # Params
            if self.session.last_simulation_params:
                p = self.session.last_simulation_params
                params_text = (
                    f"Parameters: M={p.get('M', '?')}kg, rho={p.get('rho', '?')}, "
                    f"C_rr={p.get('C_RR', '?')}, CdA_bend={p.get('cda_bend_factor', '?')}, "
                    f"Track={p.get('track_name', '?')}"
                )
                self.sim_params_var.set(params_text)
            else:
                self.sim_params_var.set("")
        else:
            self.sim_result_var.set("(No simulation run yet)")
            self.sim_params_var.set("")

        # Refresh data table (always visible)
        self._populate_data_table()

        # Update status
        self.status_label.config(text="Updated")
        self.parent.after(2000, lambda: self.status_label.config(text=""))
