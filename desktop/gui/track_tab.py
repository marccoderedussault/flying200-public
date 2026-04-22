"""
Flying 200 V2 - Track Visualization Tab

Full track viewer with:
- Overhead velodrome view with markers
- Draggable position markers
- Load/save positions
- Lap visibility toggles
- Marker position table
- Marker calculations table
- Power breakdown analysis
- Profile graphs (angle, altitude, speed vs distance)
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.markers
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional, Dict, List, Tuple, Callable
from dataclasses import dataclass
import pandas as pd
import os
import sys

# Handle imports for both direct and package execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from core.track import TrackGeometry, BROMONT_250M, AVAILABLE_TRACKS, scale_y_to_track_width
from core.session import Session


# =============================================================================
# Track Model - Geometry and Coordinate System
# =============================================================================

class TrackModel:
    """
    Track model for coordinate calculations.

    Handles conversion between:
    - Profile distance (s_m): 0-895m along black line, s=895 is finish
    - Track distance: 0-250m around one lap
    - X,Y coordinates for visualization

    Track layout (counter-clockwise):
    - Home straight (0 to straight_len)
    - Turn 1+2 (straight_len to straight_len + arc_len)
    - Back straight (straight_len + arc_len to 2*straight_len + arc_len)
    - Turn 3+4 (2*straight_len + arc_len to lap_len)

    Profile coordinate system:
    - s=0 at pursuit line (middle of back straight)
    - s=695 at 200m start line
    - s=895 at finish line (on home straight)
    """

    def __init__(self, track: TrackGeometry):
        """
        Initialize track model.

        Args:
            track: TrackGeometry object
        """
        self.track = track
        self.lap_len = track.length_m
        self.straight_len = track.straight_length_m
        self.radius = track.turn_radius_m
        self.arc_len = track.arc_length_m
        self.track_width = track.width_m  # Use track-specific width

        # Profile reference points
        self.profile_finish = 895.0  # Profile distance at finish line

        # Calculate finish line track distance
        # Mid back straight (pursuit line) is at: straight_len + arc_len + straight_len/2
        self.pursuit_track_dist = self.straight_len + self.arc_len + self.straight_len / 2

        # Use explicit finish_line_dist_m from track config if available,
        # otherwise derive from pursuit line + 895m
        if track.finish_line_dist_m is not None:
            self.finish_distance = track.finish_line_dist_m
        else:
            self.finish_distance = (self.pursuit_track_dist + self.profile_finish) % self.lap_len

        # Calculate number of points for smooth rendering
        self.num_points = 1000

        # Pre-calculate track outline
        self._calculate_track_outline()

    def _calculate_track_outline(self):
        """Pre-calculate track outline points."""
        self.outline_x = []
        self.outline_y = []

        for i in range(self.num_points + 1):
            t = i / self.num_points
            dist = t * self.lap_len
            x, y, _, _ = self._distance_to_xy(dist, 0)
            self.outline_x.append(x)
            self.outline_y.append(y)

    def _distance_to_xy(self, track_dist: float, y_offset: float = 0) -> Tuple[float, float, float, float]:
        """
        Convert track distance to X,Y coordinates.

        Track layout (counter-clockwise when viewed from above):
        - Home Straight (0 to straight_len): Bottom, left to right
        - Turn 1+2 (straight_len to straight_len + arc): Right semicircle
        - Back Straight: Top, right to left
        - Turn 3+4: Left semicircle

        Args:
            track_dist: Distance along track (0-250m)
            y_offset: Lateral offset from black line (0=black, positive=outward)

        Returns:
            (x, y, nx, ny) - position and normal vector
        """
        x, y, _, _, nx, ny = self._distance_to_xy_with_normal(track_dist, y_offset)
        return x, y, nx, ny

    def _distance_to_xy_with_normal(self, track_dist: float, y_offset: float = 0) -> Tuple[float, float, float, float, float, float]:
        """
        Convert track distance to X,Y coordinates with full normal vector.

        Args:
            track_dist: Distance along track (0-250m)
            y_offset: Lateral offset from black line (0=black, positive=outward)

        Returns:
            (x, y, tx, ty, nx, ny) - position, tangent vector, and normal vector
        """
        dist = track_dist % self.lap_len

        # Segment boundaries
        home_end = self.straight_len
        turn12_end = self.straight_len + self.arc_len
        back_end = turn12_end + self.straight_len

        if dist < home_end:
            # Home straight (bottom)
            t = dist / self.straight_len
            x = -self.straight_len / 2 + t * self.straight_len
            y = -self.radius
            nx, ny = 0, -1  # Normal points down (outward from track center)

        elif dist < turn12_end:
            # Turn 1+2 (right semicircle)
            arc_dist = dist - home_end
            angle = -np.pi / 2 + (arc_dist / self.arc_len) * np.pi
            x = self.straight_len / 2 + self.radius * np.cos(angle)
            y = self.radius * np.sin(angle)
            nx = np.cos(angle)  # Normal points outward from center
            ny = np.sin(angle)

        elif dist < back_end:
            # Back straight (top)
            t = (dist - turn12_end) / self.straight_len
            x = self.straight_len / 2 - t * self.straight_len
            y = self.radius
            nx, ny = 0, 1  # Normal points up (outward from track center)

        else:
            # Turn 3+4 (left semicircle)
            arc_dist = dist - back_end
            angle = np.pi / 2 + (arc_dist / self.arc_len) * np.pi
            x = -self.straight_len / 2 + self.radius * np.cos(angle)
            y = self.radius * np.sin(angle)
            nx = np.cos(angle)
            ny = np.sin(angle)

        # Calculate tangent (perpendicular to normal, counter-clockwise direction)
        tx = -ny
        ty = nx

        # Apply lateral offset using normal
        x += nx * y_offset
        y += ny * y_offset

        return x, y, tx, ty, nx, ny

    def profile_to_track_distance(self, s_profile: float) -> float:
        """
        Convert profile distance to track distance.

        Profile: s=0 at pursuit line (mid back straight), s=895 at finish
        Track: 0 at finish line, wraps at 250m
        """
        # Profile finish (895m) maps to track distance 0 (finish line)
        track_dist = (self.finish_distance + (s_profile - self.profile_finish)) % self.lap_len
        return track_dist

    def profile_to_xy(self, s_profile: float, y_offset: float = 0) -> Tuple[float, float, float, float, float, float]:
        """
        Convert profile distance and y offset to X,Y coordinates.

        Args:
            s_profile: Profile distance (0-895m)
            y_offset: Lateral offset from black line

        Returns:
            (x, y, tx, ty, nx, ny) - position, tangent, and normal vectors
        """
        track_dist = self.profile_to_track_distance(s_profile)
        return self._distance_to_xy_with_normal(track_dist, y_offset)

    def get_segment_name(self, track_dist: float) -> str:
        """Get segment name at track distance."""
        dist = track_dist % self.lap_len

        home_end = self.straight_len
        turn12_end = self.straight_len + self.arc_len
        back_end = turn12_end + self.straight_len

        if dist < home_end:
            return "Home Straight"
        elif dist < turn12_end:
            half_turn = home_end + self.arc_len / 2
            return "Turn 1" if dist < half_turn else "Turn 2"
        elif dist < back_end:
            return "Back Straight"
        else:
            half_turn = back_end + self.arc_len / 2
            return "Turn 3" if dist < half_turn else "Turn 4"

    def get_banking_angle(self, s_profile: float) -> float:
        """Get banking angle at profile distance (radians).

        Uses the same transition model as v1: linear interpolation over
        TRANS_LEN = ARC_LEN / 2 (half the bend length) at entry/exit.
        """
        track_dist = self.profile_to_track_distance(s_profile)
        dist = track_dist % self.lap_len

        # Segment boundaries
        home_end = self.straight_len
        turn12_end = self.straight_len + self.arc_len
        back_end = turn12_end + self.straight_len

        straight_bank = np.deg2rad(self.track.banking_straight_deg)
        turn_bank = np.deg2rad(self.track.banking_turn_deg)

        # Transition length = half the arc (matching v1 model)
        trans_len = self.arc_len / 2

        def theta_bend_with_transition(s_in_bend: float) -> float:
            """Banking angle in a bend, including entry/exit transitions.
            Matches v1 flying200_model.py exactly.
            """
            if trans_len > 0.0:
                if s_in_bend < trans_len:
                    # Entry transition: linear ramp up
                    f = s_in_bend / trans_len
                    return straight_bank + f * (turn_bank - straight_bank)
                elif s_in_bend > self.arc_len - trans_len:
                    # Exit transition: linear ramp down
                    f = (self.arc_len - s_in_bend) / trans_len
                    return straight_bank + f * (turn_bank - straight_bank)
            return turn_bank

        # Check which segment we're in
        if dist < home_end:
            # Home straight
            return straight_bank
        elif dist < turn12_end:
            # Turn 1+2 (with transitions)
            s_in_bend = dist - home_end
            return theta_bend_with_transition(s_in_bend)
        elif dist < back_end:
            # Back straight
            return straight_bank
        else:
            # Turn 3+4 (with transitions)
            s_in_bend = dist - back_end
            return theta_bend_with_transition(s_in_bend)


# =============================================================================
# Track Renderer
# =============================================================================

class TrackRenderer:
    """Renders velodrome track visualization."""

    def __init__(self, model: TrackModel):
        self.model = model

    def draw_track(self, ax: plt.Axes):
        """Draw the track outline and features."""
        ax.clear()

        # Draw track surface (outer edge)
        outer_x, outer_y = [], []
        for i in range(self.model.num_points + 1):
            t = i / self.model.num_points
            dist = t * self.model.lap_len
            x, y, _, _ = self.model._distance_to_xy(dist, self.model.track_width)
            outer_x.append(x)
            outer_y.append(y)

        # Fill track surface
        ax.fill(outer_x, outer_y, color='#E5E7EB', alpha=0.5, zorder=0)

        # Draw black line (measurement line)
        ax.plot(self.model.outline_x, self.model.outline_y,
                color='#1F2937', linewidth=2, label='Black Line', zorder=1)

        # Draw outer edge
        ax.plot(outer_x, outer_y, color='#9CA3AF', linewidth=1, zorder=1)

        # Draw red line (sprinter's line, 0.85m from black)
        red_x, red_y = [], []
        for i in range(self.model.num_points + 1):
            t = i / self.model.num_points
            dist = t * self.model.lap_len
            x, y, _, _ = self.model._distance_to_xy(dist, 0.85)
            red_x.append(x)
            red_y.append(y)
        ax.plot(red_x, red_y, color='#DC2626', linewidth=1, linestyle='--', alpha=0.5, zorder=1)

        # Draw blue line (stayer's line, 2.5m from black)
        blue_x, blue_y = [], []
        for i in range(self.model.num_points + 1):
            t = i / self.model.num_points
            dist = t * self.model.lap_len
            x, y, _, _ = self.model._distance_to_xy(dist, 2.5)
            blue_x.append(x)
            blue_y.append(y)
        ax.plot(blue_x, blue_y, color='#2563EB', linewidth=1, linestyle='--', alpha=0.5, zorder=1)

        # Draw markers using profile coordinates converted to track coordinates
        # This ensures consistency with how rider positions are drawn

        # FINISH LINE at profile s=895
        finish_track_dist = self.model.finish_distance
        fx, fy, _, _, fnx, fny = self.model._distance_to_xy_with_normal(finish_track_dist, 0)
        ax.plot([fx, fx + fnx * self.model.track_width],
                [fy, fy + fny * self.model.track_width],
                color='red', linewidth=3, label='Finish Line (s=895)', zorder=2)

        # PURSUIT LINE at profile s=0 (mid back straight)
        pursuit_track_dist = self.model.pursuit_track_dist
        px, py, _, _, pnx, pny = self.model._distance_to_xy_with_normal(pursuit_track_dist, 0)
        ax.plot([px, px + pnx * self.model.track_width],
                [py, py + pny * self.model.track_width],
                color='blue', linewidth=2, linestyle='--', label='Pursuit Line (s=0)', zorder=2)

        # 200m START LINE at profile s=695
        start_200_track_dist = self.model.profile_to_track_distance(695.0)
        sx, sy, _, _, snx, sny = self.model._distance_to_xy_with_normal(start_200_track_dist, 0)
        ax.plot([sx, sx + snx * self.model.track_width],
                [sy, sy + sny * self.model.track_width],
                color='green', linewidth=2, linestyle='--', label='200m Start (s=695)', zorder=2)

        # Add segment labels
        self._add_segment_labels(ax)

        # Styling
        ax.set_aspect('equal', adjustable='box')
        margin = 5
        w = self.model.straight_len / 2 + self.model.radius + self.model.track_width + margin
        h = self.model.radius + self.model.track_width + margin
        ax.set_xlim(-w, w)
        ax.set_ylim(-h, h)
        ax.axis('off')
        ax.set_title(f"Track View: {self.model.track.name}", fontsize=11)

    def _add_segment_labels(self, ax: plt.Axes):
        """Add segment name labels to the track."""
        r = self.model.radius
        s = self.model.straight_len

        ax.text(0, -r - 8, 'Home Straight', ha='center', fontsize=8, color='#374151')
        ax.text(0, r + 8, 'Back Straight', ha='center', fontsize=8, color='#374151')
        ax.text(s / 2 + r + 8, 0, 'Turn 1/2', ha='left', fontsize=8, color='#374151')
        ax.text(-s / 2 - r - 8, 0, 'Turn 3/4', ha='right', fontsize=8, color='#374151')


# =============================================================================
# Track Tab
# =============================================================================

class TrackTab:
    """
    Track visualization tab with full marker editing functionality.

    Features:
    - Overhead track view
    - Draggable position markers
    - Lap visibility toggles
    - Marker position table
    - Marker data calculations
    """

    # Lap colors
    LAP_COLORS = {
        0: '#3B82F6',  # Blue - Lap 0 (to pursuit)
        1: '#10B981',  # Green - Lap 1 (full lap)
        2: '#F59E0B',  # Amber - Lap 2 (to 200m start)
        3: '#EF4444',  # Red - Timed 200m
    }

    LAP_NAMES = {
        0: 'Lap 0 (to pursuit)',
        1: 'Lap 1 (full lap)',
        2: 'Lap 2 (to 200m)',
        3: 'Timed 200m',
    }

    def __init__(
        self,
        parent: ttk.Frame,
        session: Session,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize track tab.

        Args:
            parent: Parent frame
            session: Session object
            status_callback: Status update callback
        """
        self.parent = parent
        self.session = session
        self.status_callback = status_callback or (lambda x: None)

        # Track model
        self.track_model = TrackModel(session.track or BROMONT_250M)
        self.track_renderer = TrackRenderer(self.track_model)

        # Position data: {lap_num: [(s_m, y_m), ...]}
        self.track_positions: Dict[int, List[Tuple[float, float]]] = {0: [], 1: [], 2: [], 3: []}

        # Marker state
        self.markers: List = []  # Matplotlib marker artists
        self.marker_data: List[Tuple[int, int, float]] = []  # (lap, idx, s_m)
        self.dragging_marker: Optional[int] = None
        self.marker_entries: List[Tuple[int, int, tk.StringVar]] = []

        # Current CSV file
        self.current_csv: Optional[str] = None

        # Build UI
        self._build_ui()

        # Register as session observer to update optimized line status
        self.session.add_observer(self._on_session_changed)

    def _get_lap_boundaries(self):
        """Compute lap boundaries from current track geometry.

        Returns (lap_len, pursuit1, pursuit2, start_200).
        pursuit1 = first pursuit crossing (half a lap from start).
        pursuit2 = second pursuit crossing (1.5 laps from start).
        """
        lap_len = self.track_model.lap_len
        pursuit1 = lap_len / 2.0
        pursuit2 = lap_len * 1.5
        start_200 = 695.0
        return lap_len, pursuit1, pursuit2, start_200

    def _build_ui(self):
        """Build the track tab UI."""
        # Main paned window: left controls, right visualization
        paned = ttk.PanedWindow(self.parent, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # Left panel: Controls
        left_frame = ttk.Frame(paned, width=320)
        paned.add(left_frame, weight=0)

        # Right panel: Track + Tables
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self._build_left_panel(left_frame)
        self._build_right_panel(right_frame)

    def _build_left_panel(self, parent: ttk.Frame):
        """Build left control panel."""
        # === Track Controls ===
        controls_frame = ttk.LabelFrame(parent, text="Track Controls", padding=5)
        controls_frame.pack(fill="x", padx=5, pady=5)

        ttk.Button(controls_frame, text="Load Profile CSV",
                   command=self._load_profile).pack(fill="x", pady=2)
        ttk.Button(controls_frame, text="Load from Session",
                   command=self._load_from_session).pack(fill="x", pady=2)
        ttk.Button(controls_frame, text="Save Positions to CSV",
                   command=self._save_positions).pack(fill="x", pady=2)

        # Track selector
        track_row = ttk.Frame(controls_frame)
        track_row.pack(fill="x", pady=5)
        ttk.Label(track_row, text="Track:").pack(side="left", padx=5)
        self.track_var = tk.StringVar(value="Bromont")
        track_combo = ttk.Combobox(
            track_row, textvariable=self.track_var,
            values=list(AVAILABLE_TRACKS.keys()),
            state="readonly", width=12
        )
        track_combo.pack(side="left", padx=5)
        track_combo.bind("<<ComboboxSelected>>", self._on_track_changed)

        # === Lap Visibility ===
        lap_frame = ttk.LabelFrame(parent, text="Lap Visibility", padding=5)
        lap_frame.pack(fill="x", padx=5, pady=5)

        self.show_lap_vars = {}
        for lap_num, name in self.LAP_NAMES.items():
            var = tk.BooleanVar(value=True)
            self.show_lap_vars[lap_num] = var
            ttk.Checkbutton(lap_frame, text=name, variable=var,
                           command=self._update_display).pack(anchor="w")

        # === Optimized Line Overlay ===
        overlay_frame = ttk.LabelFrame(parent, text="Optimizer Overlay", padding=5)
        overlay_frame.pack(fill="x", padx=5, pady=5)

        self.show_optimized_var = tk.BooleanVar(value=False)  # Off by default for performance
        ttk.Checkbutton(overlay_frame, text="Show Optimized Line",
                       variable=self.show_optimized_var).pack(anchor="w")

        self.optimized_info_var = tk.StringVar(value="No optimization result")
        ttk.Label(overlay_frame, textvariable=self.optimized_info_var,
                 foreground='#059669', font=('Segoe UI', 9)).pack(anchor="w", pady=2)

        # Buttons row
        btn_row = ttk.Frame(overlay_frame)
        btn_row.pack(fill="x", pady=2)
        ttk.Button(btn_row, text="Refresh", width=8,
                  command=self._update_display).pack(side="left", padx=(0, 2))
        ttk.Button(btn_row, text="Apply Line",
                  command=self._apply_optimized_line).pack(side="left", fill="x", expand=True)

        # === Info Display ===
        info_frame = ttk.LabelFrame(parent, text="Status", padding=5)
        info_frame.pack(fill="x", padx=5, pady=5)

        self.info_var = tk.StringVar(value="Load a profile to see positions")
        ttk.Label(info_frame, textvariable=self.info_var, wraplength=280).pack()

        # === Marker Position Table ===
        marker_frame = ttk.LabelFrame(parent, text="Marker Positions (y_m)", padding=5)
        marker_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Apply button at top
        btn_frame = ttk.Frame(marker_frame)
        btn_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(btn_frame, text="Apply Changes",
                   command=self._apply_marker_changes).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Reset",
                   command=self._reset_marker_entries).pack(side="left", padx=2)

        # Scrollable canvas for markers
        canvas = tk.Canvas(marker_frame, height=200)
        scrollbar = ttk.Scrollbar(marker_frame, orient="vertical", command=canvas.yview)
        self.marker_table_frame = ttk.Frame(canvas)

        self.marker_table_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.marker_table_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Header
        header = ttk.Frame(self.marker_table_frame)
        header.pack(fill="x", pady=2)
        ttk.Label(header, text="Lap", width=8).pack(side="left")
        ttk.Label(header, text="s_m", width=8).pack(side="left")
        ttk.Label(header, text="y_m", width=10).pack(side="left")

        # Store entry widgets for tab navigation
        self.marker_entry_widgets: List[ttk.Entry] = []

    def _build_right_panel(self, parent: ttk.Frame):
        """Build right panel with track view, profile graphs, and tables."""
        # Vertical paned: visualization on top, tables on bottom
        paned = ttk.PanedWindow(parent, orient="vertical")
        paned.pack(fill="both", expand=True)

        # Top: Tabbed visualization (Track View + Profile Graphs)
        viz_notebook = ttk.Notebook(paned)
        paned.add(viz_notebook, weight=3)

        # Tab 1: Track visualization
        track_frame = ttk.Frame(viz_notebook)
        viz_notebook.add(track_frame, text="Track View")

        self.fig, self.ax = plt.subplots(1, 1, figsize=(10, 7))
        self.fig.tight_layout(pad=2.0)

        self.canvas = FigureCanvasTkAgg(self.fig, master=track_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Connect mouse events for dragging
        self.fig.canvas.mpl_connect('button_press_event', self._on_click)
        self.fig.canvas.mpl_connect('motion_notify_event', self._on_drag)
        self.fig.canvas.mpl_connect('button_release_event', self._on_release)

        # Draw initial track
        self._draw_track()

        # Tab 2: Profile Graphs (angle, altitude, speed vs distance)
        graphs_frame = ttk.Frame(viz_notebook)
        viz_notebook.add(graphs_frame, text="Profile Graphs")

        self._build_profile_graphs(graphs_frame)

        # Tab 3: Optimizer Comparison (initial vs optimized y_m)
        comparison_frame = ttk.Frame(viz_notebook)
        viz_notebook.add(comparison_frame, text="Optimizer Comparison")

        self._build_optimizer_comparison(comparison_frame)

        # Bottom: Marker data table
        table_frame = ttk.LabelFrame(paned, text="Marker Calculations", padding=5)
        paned.add(table_frame, weight=1)

        self._build_marker_table(table_frame)

    def _build_marker_table(self, parent: ttk.Frame):
        """Build the marker data table (calculations)."""
        columns = ('lap', 's_m', 'y_m', 'segment', 'bank_deg', 'altitude_m')
        self.data_tree = ttk.Treeview(parent, columns=columns, show='headings', height=6)

        self.data_tree.heading('lap', text='Lap')
        self.data_tree.heading('s_m', text='s_m')
        self.data_tree.heading('y_m', text='y_m')
        self.data_tree.heading('segment', text='Segment')
        self.data_tree.heading('bank_deg', text='Bank (°)')
        self.data_tree.heading('altitude_m', text='Alt (m)')

        self.data_tree.column('lap', width=60, anchor='center')
        self.data_tree.column('s_m', width=70, anchor='center')
        self.data_tree.column('y_m', width=60, anchor='center')
        self.data_tree.column('segment', width=100, anchor='center')
        self.data_tree.column('bank_deg', width=70, anchor='center')
        self.data_tree.column('altitude_m', width=80, anchor='center')

        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.data_tree.yview)
        self.data_tree.configure(yscrollcommand=scrollbar.set)

        self.data_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _build_profile_graphs(self, parent: ttk.Frame):
        """Build the profile graphs panel with angle, altitude, and speed charts."""
        # Create figure with 3 subplots sharing x-axis
        # Use constrained_layout instead of tight_layout for shared axes
        self.profile_fig, self.profile_axes = plt.subplots(
            3, 1, figsize=(12, 8), sharex=True,
            constrained_layout=True
        )
        self.profile_fig.patch.set_facecolor('#FFFFFF')

        # Label the axes
        self.ax_angle = self.profile_axes[0]
        self.ax_altitude = self.profile_axes[1]
        self.ax_speed = self.profile_axes[2]

        # Initial setup for each subplot
        self.ax_angle.set_ylabel('Banking Angle (°)', fontsize=9)
        self.ax_angle.grid(True, alpha=0.3, color='#E5E7EB')
        self.ax_angle.set_title('Track Profile: Unraveled Trajectory (0-895m)', fontsize=11, pad=10)

        self.ax_altitude.set_ylabel('Altitude (m)', fontsize=9)
        self.ax_altitude.grid(True, alpha=0.3, color='#E5E7EB')

        self.ax_speed.set_ylabel('Speed (km/h)', fontsize=9)
        self.ax_speed.set_xlabel('Blackline Distance (m)', fontsize=9)
        self.ax_speed.grid(True, alpha=0.3, color='#E5E7EB')

        # Embed in tkinter
        self.profile_canvas = FigureCanvasTkAgg(self.profile_fig, master=parent)
        self.profile_canvas.get_tk_widget().pack(fill="both", expand=True)

        # Draw initial empty graphs
        self._update_profile_graphs()

    def _update_profile_graphs(self):
        """Update the profile graphs with current track and position data."""
        # Clear all axes
        self.ax_angle.clear()
        self.ax_altitude.clear()
        self.ax_speed.clear()

        # Setup axes labels and grid
        self.ax_angle.set_ylabel('Banking Angle (°)', fontsize=9)
        self.ax_angle.grid(True, alpha=0.3, color='#E5E7EB')
        self.ax_angle.set_title(
            f'Track Profile: {self.track_model.track.name} (0-895m)',
            fontsize=11, pad=10
        )

        self.ax_altitude.set_ylabel('Altitude (m)', fontsize=9)
        self.ax_altitude.grid(True, alpha=0.3, color='#E5E7EB')

        self.ax_speed.set_ylabel('Speed (km/h)', fontsize=9)
        self.ax_speed.set_xlabel('Blackline Distance (m)', fontsize=9)
        self.ax_speed.grid(True, alpha=0.3, color='#E5E7EB')

        # Generate distance array (0-895m, 1m intervals)
        s_grid = np.arange(0, 896, 1)

        # === Graph 1: Banking Angle vs Distance ===
        angles_deg = []
        for s in s_grid:
            angle_rad = self.track_model.get_banking_angle(s)
            angles_deg.append(np.degrees(angle_rad))

        self.ax_angle.plot(s_grid, angles_deg, color='#9333EA', linewidth=1.5, label='Banking Angle')
        self.ax_angle.fill_between(s_grid, angles_deg, alpha=0.2, color='#9333EA')

        # Add segment shading
        self._add_segment_shading_to_axis(self.ax_angle, s_grid)

        self.ax_angle.set_xlim(0, 895)
        self.ax_angle.legend(loc='upper right', fontsize=8)

        # === Graph 2: Altitude vs Distance ===
        # Get y_m values from track positions, interpolated
        all_points = []
        for lap_positions in self.track_positions.values():
            all_points.extend(lap_positions)

        if all_points:
            all_points.sort(key=lambda p: p[0])
            s_arr = np.array([p[0] for p in all_points])
            y_arr = np.array([p[1] for p in all_points])

            # Interpolate y_m to full grid
            y_grid = np.interp(s_grid, s_arr, y_arr)

            # Calculate altitude: altitude = y_m * sin(banking_angle)
            altitudes = []
            for i, s in enumerate(s_grid):
                angle_rad = self.track_model.get_banking_angle(s)
                alt = y_grid[i] * np.sin(angle_rad)
                altitudes.append(alt)

            self.ax_altitude.plot(s_grid, altitudes, color='#16A34A', linewidth=1.5, label='Altitude')
            self.ax_altitude.fill_between(s_grid, altitudes, alpha=0.2, color='#16A34A')
        else:
            # No position data - show altitude at black line (y=0)
            self.ax_altitude.axhline(y=0, color='#16A34A', linewidth=1.5,
                                     linestyle='--', label='Altitude (no profile)')
            self.ax_altitude.text(447.5, 0.1, 'Load profile to see altitude',
                                  ha='center', fontsize=9, color='#6B7280')

        self._add_segment_shading_to_axis(self.ax_altitude, s_grid)
        self.ax_altitude.set_xlim(0, 895)
        self.ax_altitude.legend(loc='upper right', fontsize=8)

        # === Graph 3: Speed vs Distance ===
        # Try to get speed from session simulation result
        speed_available = False

        if (self.session.last_simulation_result is not None and
            'v' in self.session.last_simulation_result and
            's_grid' in self.session.last_simulation_result):

            sim_s = self.session.last_simulation_result['s_grid']
            sim_v = self.session.last_simulation_result['v']

            if len(sim_s) > 0 and len(sim_v) > 0:
                # Interpolate simulation speed to our grid
                v_grid = np.interp(s_grid, sim_s, sim_v)
                v_kph = v_grid * 3.6  # Convert m/s to km/h

                self.ax_speed.plot(s_grid, v_kph, color='#2563EB', linewidth=1.5, label='Speed')
                self.ax_speed.fill_between(s_grid, v_kph, alpha=0.2, color='#2563EB')
                speed_available = True

        if not speed_available:
            # No simulation data - show message
            self.ax_speed.axhline(y=0, color='#2563EB', linewidth=1.5,
                                  linestyle='--', alpha=0.5)
            self.ax_speed.text(447.5, 5, 'Run simulation to see speed profile',
                              ha='center', fontsize=9, color='#6B7280')
            self.ax_speed.set_ylim(0, 100)

        self._add_segment_shading_to_axis(self.ax_speed, s_grid)
        self.ax_speed.set_xlim(0, 895)
        if speed_available:
            self.ax_speed.legend(loc='upper right', fontsize=8)

        # Add key distance markers (200m start at 695, finish at 895)
        for ax in self.profile_axes:
            ax.axvline(x=695, color='#059669', linewidth=1.5, linestyle='--', alpha=0.7)
            ax.axvline(x=895, color='#DC2626', linewidth=1.5, linestyle='--', alpha=0.7)

        # Add labels for markers on top plot only
        self.ax_angle.annotate('200m Start', xy=(695, self.ax_angle.get_ylim()[1]),
                               fontsize=7, ha='center', va='bottom', color='#059669')
        self.ax_angle.annotate('Finish', xy=(895, self.ax_angle.get_ylim()[1]),
                               fontsize=7, ha='center', va='bottom', color='#DC2626')

        self.profile_canvas.draw()

    def _add_segment_shading_to_axis(self, ax: plt.Axes, s_grid: np.ndarray):
        """Add alternating background shading for track segments."""
        # Segment transitions based on track geometry
        # We need to identify turn vs straight sections
        s_min, s_max = s_grid.min(), s_grid.max()

        # Get segment boundaries by checking banking angle changes
        prev_in_turn = None
        segment_start = s_min

        for s in s_grid:
            angle_rad = self.track_model.get_banking_angle(s)
            in_turn = angle_rad > np.deg2rad(self.track_model.track.banking_straight_deg + 5)

            if prev_in_turn is not None and in_turn != prev_in_turn:
                # Segment boundary
                if prev_in_turn:
                    # Was in turn, now in straight - shade turn
                    ax.axvspan(segment_start, s, alpha=0.08, color='#F59E0B', zorder=0)
                segment_start = s

            prev_in_turn = in_turn

        # Shade final segment if it was a turn
        if prev_in_turn:
            ax.axvspan(segment_start, s_max, alpha=0.08, color='#F59E0B', zorder=0)

    def _build_optimizer_comparison(self, parent: ttk.Frame):
        """Build the optimizer comparison panel showing initial vs optimized y_m."""
        # Info label at top
        info_frame = ttk.Frame(parent)
        info_frame.pack(fill="x", padx=5, pady=5)

        self.comparison_info_var = tk.StringVar(
            value="Load a profile and run optimizer to see comparison"
        )
        ttk.Label(info_frame, textvariable=self.comparison_info_var,
                 font=('Segoe UI', 9)).pack(anchor="w")

        # Treeview for comparison table
        columns = ('s_m', 'segment', 'initial_y', 'optimized_y', 'delta_y')
        self.comparison_tree = ttk.Treeview(parent, columns=columns, show='headings', height=20)

        self.comparison_tree.heading('s_m', text='s_m')
        self.comparison_tree.heading('segment', text='Segment')
        self.comparison_tree.heading('initial_y', text='Initial y_m')
        self.comparison_tree.heading('optimized_y', text='Optimized y_m')
        self.comparison_tree.heading('delta_y', text='Δ y_m')

        self.comparison_tree.column('s_m', width=70, anchor='center')
        self.comparison_tree.column('segment', width=100, anchor='center')
        self.comparison_tree.column('initial_y', width=100, anchor='center')
        self.comparison_tree.column('optimized_y', width=100, anchor='center')
        self.comparison_tree.column('delta_y', width=100, anchor='center')

        # Scrollbar
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.comparison_tree.yview)
        self.comparison_tree.configure(yscrollcommand=scrollbar.set)

        self.comparison_tree.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        scrollbar.pack(side="right", fill="y", padx=(0, 5), pady=5)

        # Configure tag colors for positive/negative deltas
        self.comparison_tree.tag_configure('positive', foreground='#059669')  # Green - moved outward
        self.comparison_tree.tag_configure('negative', foreground='#DC2626')  # Red - moved inward
        self.comparison_tree.tag_configure('neutral', foreground='#6B7280')   # Gray - no change

    def _update_optimizer_comparison(self):
        """Update the optimizer comparison table with current vs optimized y_m values."""
        # Clear existing items
        for item in self.comparison_tree.get_children():
            self.comparison_tree.delete(item)

        # Check if we have both current positions and optimized data
        has_positions = any(len(positions) > 0 for positions in self.track_positions.values())
        has_optimized = (self.session.last_optimized_y_m is not None and
                        self.session.last_optimized_s_m is not None)

        if not has_positions:
            self.comparison_info_var.set("Load a profile to see marker positions")
            return

        if not has_optimized:
            self.comparison_info_var.set("Run optimizer to see comparison")
            # Still show current positions with N/A for optimized
            self._populate_comparison_without_optimized()
            return

        # Get optimized data, scaled to current track width
        opt_s = self.session.last_optimized_s_m
        opt_y = scale_y_to_track_width(self.session.last_optimized_y_m, self.track_model.track_width)

        # Collect all current marker positions
        all_markers = []
        for lap_num in range(4):
            positions = self.track_positions.get(lap_num, [])
            for s, y in positions:
                all_markers.append((s, y))

        # Sort by s_m
        all_markers.sort(key=lambda m: m[0])

        # Calculate statistics
        total_delta = 0.0
        positive_count = 0
        negative_count = 0

        for s, initial_y in all_markers:
            # Get segment name
            track_dist = self.track_model.profile_to_track_distance(s)
            segment = self.track_model.get_segment_name(track_dist)

            # Interpolate optimized y at this s
            if s < opt_s.min() or s > opt_s.max():
                optimized_y = initial_y  # Use initial if outside range
            else:
                optimized_y = float(np.interp(s, opt_s, opt_y))

            delta_y = optimized_y - initial_y
            total_delta += abs(delta_y)

            # Determine tag based on delta
            if delta_y > 0.01:
                tag = 'positive'
                positive_count += 1
                delta_str = f"+{delta_y:.3f}"
            elif delta_y < -0.01:
                tag = 'negative'
                negative_count += 1
                delta_str = f"{delta_y:.3f}"
            else:
                tag = 'neutral'
                delta_str = f"{delta_y:.3f}"

            values = (
                f"{s:.0f}",
                segment,
                f"{initial_y:.3f}",
                f"{optimized_y:.3f}",
                delta_str,
            )
            self.comparison_tree.insert('', 'end', values=values, tags=(tag,))

        # Update info label
        improvement = self.session.last_optimization_improvement_ms
        avg_delta = total_delta / len(all_markers) if all_markers else 0
        self.comparison_info_var.set(
            f"Optimization: Δ{-improvement:+.0f}ms | "
            f"Avg |Δy|: {avg_delta:.3f}m | "
            f"Outward: {positive_count} | Inward: {negative_count}"
        )

    def _populate_comparison_without_optimized(self):
        """Populate comparison table when no optimized data is available."""
        all_markers = []
        for lap_num in range(4):
            positions = self.track_positions.get(lap_num, [])
            for s, y in positions:
                all_markers.append((s, y))

        all_markers.sort(key=lambda m: m[0])

        for s, initial_y in all_markers:
            track_dist = self.track_model.profile_to_track_distance(s)
            segment = self.track_model.get_segment_name(track_dist)

            values = (
                f"{s:.0f}",
                segment,
                f"{initial_y:.3f}",
                "—",
                "—",
            )
            self.comparison_tree.insert('', 'end', values=values, tags=('neutral',))

    def _on_track_changed(self, event=None):
        """Handle track selection change."""
        track_name = self.track_var.get()
        track = AVAILABLE_TRACKS.get(track_name, BROMONT_250M)
        self.session.track = track
        self.track_model = TrackModel(track)
        self.track_renderer = TrackRenderer(self.track_model)

        # Load trajectory from JSON config if available
        from core.track import TRACK_TRAJECTORIES
        if track_name in TRACK_TRAJECTORIES:
            traj = TRACK_TRAJECTORIES[track_name]
            _, pursuit1, pursuit2, start_200 = self._get_lap_boundaries()
            self.track_positions = {0: [], 1: [], 2: [], 3: []}
            for pt in traj:
                s, y = pt["s_m"], pt["y_m"]
                if s < pursuit1:
                    self.track_positions[0].append((s, y))
                elif s < pursuit2:
                    self.track_positions[1].append((s, y))
                elif s < start_200:
                    self.track_positions[2].append((s, y))
                else:
                    self.track_positions[3].append((s, y))
            total = sum(len(v) for v in self.track_positions.values())
            self.status_callback(f"Loaded {total} trajectory markers for {track.name}")

        self._update_display()

    def _draw_track(self):
        """Draw the track outline."""
        self.track_renderer.draw_track(self.ax)
        self.canvas.draw()

    def _load_profile(self):
        """Load position data from CSV file."""
        filepath = filedialog.askopenfilename(
            title="Select Profile CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not filepath:
            return

        try:
            self.current_csv = filepath
            profile = pd.read_csv(filepath)
            profile.columns = profile.columns.str.strip()

            if 's_m' not in profile.columns or 'y_m' not in profile.columns:
                messagebox.showerror("Error", "CSV must have 's_m' and 'y_m' columns")
                return

            s_arr = profile['s_m'].values
            y_arr = profile['y_m'].values.copy()

            # Scale y_m to current track width if profile comes from a wider track
            y_arr = scale_y_to_track_width(y_arr, self.track_model.track_width)

            # Calculate lap boundaries from current track geometry
            lap_len, pursuit1, pursuit2, start_200 = self._get_lap_boundaries()
            finish = 895.0

            # Clear existing positions
            self.track_positions = {0: [], 1: [], 2: [], 3: []}

            # Assign points to laps
            for s, y in zip(s_arr, y_arr):
                if s < pursuit1:
                    self.track_positions[0].append((s, y))
                elif s < pursuit2:
                    self.track_positions[1].append((s, y))
                elif s < start_200:
                    self.track_positions[2].append((s, y))
                else:
                    self.track_positions[3].append((s, y))

            # Update display
            self._update_display()

            lap_counts = [len(self.track_positions[i]) for i in range(4)]
            self.info_var.set(
                f"Loaded: {os.path.basename(filepath)}\n"
                f"L0={lap_counts[0]}, L1={lap_counts[1]}, L2={lap_counts[2]}, Timed={lap_counts[3]}"
            )
            self.status_callback(f"Loaded {filepath}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load: {str(e)}")
            self.info_var.set(f"Error: {str(e)}")

    def _save_positions(self):
        """Save current positions back to CSV."""
        if not self.current_csv:
            messagebox.showwarning("Warning", "No CSV file loaded")
            return

        filepath = filedialog.asksaveasfilename(
            title="Save Profile CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=os.path.basename(self.current_csv)
        )

        if not filepath:
            return

        try:
            # Read original CSV
            profile = pd.read_csv(self.current_csv)
            profile.columns = profile.columns.str.strip()

            # Build lookup of new y values
            new_y_lookup = {}
            for lap_num, positions in self.track_positions.items():
                for s, y in positions:
                    new_y_lookup[round(s, 2)] = y

            # Update y_m values
            updated = 0
            for idx, row in profile.iterrows():
                s_key = round(row['s_m'], 2)
                if s_key in new_y_lookup:
                    profile.at[idx, 'y_m'] = new_y_lookup[s_key]
                    updated += 1

            # Save
            profile.to_csv(filepath, index=False)
            self.info_var.set(f"Saved {updated} positions to {os.path.basename(filepath)}")
            self.status_callback(f"Saved to {filepath}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {str(e)}")

    def _update_display(self):
        """Redraw track with current position data."""
        self._draw_track()

        # Clear markers
        self.markers = []
        self.marker_data = []

        # Draw paths and markers for each visible lap
        for lap_num in range(4):
            if not self.show_lap_vars[lap_num].get():
                continue

            positions = self.track_positions.get(lap_num, [])
            if not positions:
                continue

            color = self.LAP_COLORS[lap_num]

            # Draw path
            xs, ys = [], []
            for s, y in positions:
                x_pos, y_pos, _, _, _, _ = self.track_model.profile_to_xy(s, y)
                xs.append(x_pos)
                ys.append(y_pos)

            self.ax.plot(xs, ys, color=color, linewidth=2.5,
                        label=self.LAP_NAMES[lap_num], zorder=3)

            # Draw markers
            for idx, (s, y) in enumerate(positions):
                x_pos, y_pos, tx, ty, nx, ny = self.track_model.profile_to_xy(s, y)

                # Arrow marker pointing in direction of travel
                arrow_angle = np.degrees(np.arctan2(ty, tx))
                arrow_marker = matplotlib.markers.MarkerStyle(marker='>')
                arrow_marker._transform = arrow_marker.get_transform().rotate_deg(arrow_angle)

                marker = self.ax.scatter([x_pos], [y_pos], color=color,
                                         s=100, marker=arrow_marker, zorder=5,
                                         edgecolors='black', linewidths=0.5, picker=5)
                self.markers.append(marker)
                self.marker_data.append((lap_num, idx, s))

        # Draw optimized line overlay if available and enabled
        if (self.show_optimized_var.get() and
            self.session.last_optimized_y_m is not None and
            self.session.last_optimized_s_m is not None):

            opt_s = self.session.last_optimized_s_m
            opt_y = scale_y_to_track_width(self.session.last_optimized_y_m, self.track_model.track_width)

            # Draw the optimized line as dashed green
            opt_xs, opt_ys = [], []
            for s, y in zip(opt_s, opt_y):
                x_pos, y_pos, _, _, _, _ = self.track_model.profile_to_xy(s, y)
                opt_xs.append(x_pos)
                opt_ys.append(y_pos)

            self.ax.plot(opt_xs, opt_ys, color='#059669', linewidth=2.5,
                        linestyle='--', label='Optimized Line', zorder=4, alpha=0.8)

            # Add delta annotations at key points (200m start and mid-timed)
            # Show y_m difference at s=695 (200m start) and s=795 (mid timed)
            for check_s in [695.0, 795.0]:
                # Find y values at this s
                opt_y_at_s = np.interp(check_s, opt_s, opt_y)

                # Find current y value if we have positions
                current_y_at_s = None
                for lap_num, positions in self.track_positions.items():
                    for s, y in positions:
                        if abs(s - check_s) < 5:  # Within 5m
                            current_y_at_s = y
                            break
                    if current_y_at_s is not None:
                        break

                # Also try interpolating from all positions
                if current_y_at_s is None:
                    all_points = []
                    for lap_positions in self.track_positions.values():
                        all_points.extend(lap_positions)
                    if all_points:
                        all_points.sort(key=lambda p: p[0])
                        s_arr = [p[0] for p in all_points]
                        y_arr = [p[1] for p in all_points]
                        if min(s_arr) <= check_s <= max(s_arr):
                            current_y_at_s = np.interp(check_s, s_arr, y_arr)

                if current_y_at_s is not None:
                    delta_y = opt_y_at_s - current_y_at_s
                    if abs(delta_y) > 0.05:  # Only show if difference > 5cm
                        x_ann, y_ann, _, _, _, _ = self.track_model.profile_to_xy(check_s, opt_y_at_s)
                        sign = '+' if delta_y > 0 else ''
                        self.ax.annotate(f'{sign}{delta_y:.2f}m',
                                        xy=(x_ann, y_ann), fontsize=7,
                                        color='#059669', fontweight='bold',
                                        ha='center', va='bottom',
                                        xytext=(0, 5), textcoords='offset points')

        self.ax.legend(loc='upper right', fontsize=8)
        self.canvas.draw()

        # Update marker table
        self._update_marker_table()

        # Update data table
        self._update_data_table()

        # Update profile graphs
        self._update_profile_graphs()

        # Update optimizer comparison table
        self._update_optimizer_comparison()

    def _update_marker_table(self):
        """Update the marker position table in left panel."""
        # Clear existing entries (keep header)
        for widget in list(self.marker_table_frame.winfo_children())[1:]:
            widget.destroy()
        self.marker_entries = []
        self.marker_entry_widgets = []

        for lap_num in range(4):
            positions = self.track_positions.get(lap_num, [])
            for idx, (s, y) in enumerate(positions):
                row = ttk.Frame(self.marker_table_frame)
                row.pack(fill="x", pady=1)

                # Lap label with color indicator
                lap_label = ttk.Label(row, text=f"L{lap_num}", width=8)
                lap_label.pack(side="left")

                # s_m display
                ttk.Label(row, text=f"{s:.0f}", width=8).pack(side="left")

                # y_m entry (editable) - no auto-update, use Apply button
                y_var = tk.StringVar(value=f"{y:.2f}")
                entry = ttk.Entry(row, textvariable=y_var, width=8)
                entry.pack(side="left")

                self.marker_entries.append((lap_num, idx, y_var))
                self.marker_entry_widgets.append(entry)

        # Set up tab navigation between entries
        for i, entry in enumerate(self.marker_entry_widgets):
            entry.bind("<Tab>", lambda e, idx=i: self._focus_next_entry(idx))
            entry.bind("<Shift-Tab>", lambda e, idx=i: self._focus_prev_entry(idx))

    def _update_data_table(self):
        """Update the marker data table with calculations."""
        # Clear existing
        for item in self.data_tree.get_children():
            self.data_tree.delete(item)

        # Collect all markers
        all_markers = []
        for lap_num in range(4):
            positions = self.track_positions.get(lap_num, [])
            for idx, (s, y) in enumerate(positions):
                all_markers.append({
                    'lap': lap_num,
                    'idx': idx,
                    's_m': s,
                    'y_m': y,
                })

        if not all_markers:
            return

        # Sort by s_m
        all_markers.sort(key=lambda m: m['s_m'])

        # Calculate values and add to table
        for m in all_markers:
            s, y = m['s_m'], m['y_m']

            # Get segment name
            track_dist = self.track_model.profile_to_track_distance(s)
            segment = self.track_model.get_segment_name(track_dist)

            # Get banking angle
            bank_rad = self.track_model.get_banking_angle(s)
            bank_deg = np.degrees(bank_rad)

            # Calculate altitude (height above datum)
            altitude = y * np.sin(bank_rad)

            # Add row
            values = (
                f"L{m['lap']}",
                f"{s:.1f}",
                f"{y:.2f}",
                segment,
                f"{bank_deg:.1f}",
                f"{altitude:.3f}",
            )
            self.data_tree.insert('', 'end', values=values)

    def _focus_next_entry(self, current_idx: int):
        """Focus the next entry in the marker table and select all text."""
        if current_idx + 1 < len(self.marker_entry_widgets):
            entry = self.marker_entry_widgets[current_idx + 1]
            entry.focus_set()
            entry.select_range(0, tk.END)
            return "break"  # Prevent default Tab behavior

    def _focus_prev_entry(self, current_idx: int):
        """Focus the previous entry in the marker table and select all text."""
        if current_idx > 0:
            entry = self.marker_entry_widgets[current_idx - 1]
            entry.focus_set()
            entry.select_range(0, tk.END)
            return "break"  # Prevent default Shift-Tab behavior

    def _apply_marker_changes(self):
        """Apply all marker y_m changes from the entry fields."""
        updated_count = 0
        for lap, idx, y_var in self.marker_entries:
            try:
                new_y = float(y_var.get())
                new_y = max(0, min(self.track_model.track_width, new_y))  # Clamp to track bounds

                if lap in self.track_positions and idx < len(self.track_positions[lap]):
                    old_s, old_y = self.track_positions[lap][idx]
                    if abs(new_y - old_y) > 0.001:  # Only count actual changes
                        self.track_positions[lap][idx] = (old_s, new_y)
                        updated_count += 1
            except ValueError:
                pass  # Skip invalid entries

        if updated_count > 0:
            self._update_display()
            # Sync changes to session profile
            self._sync_to_session()
            self.info_var.set(f"Applied {updated_count} marker change(s) - synced to session")
        else:
            self.info_var.set("No changes to apply")

    def _sync_to_session(self):
        """Sync track_positions to session.profile.y_m.

        This allows changes made in TrackTab to be reflected in SimulationTab
        without requiring CSV save/reload.
        """
        if not self.session.profile:
            # No profile to sync to
            return

        # Flatten track_positions to sorted (s, y) arrays
        all_points = []
        for lap_positions in self.track_positions.values():
            all_points.extend(lap_positions)

        if not all_points:
            return

        all_points.sort(key=lambda p: p[0])
        s_arr = np.array([p[0] for p in all_points])
        y_arr = np.array([p[1] for p in all_points])

        # Update session profile
        self.session.update_profile_y_m(s_arr, y_arr)
        self.status_callback("Track positions synced to session")

    def _load_from_session(self):
        """Load positions from session.profile if available.

        This allows loading the profile data that was exported from FIT Analysis
        without having to save and reload from CSV.

        Uses standard blackline positions (10m intervals + key markers) instead
        of raw simulation grid points for performance.
        """
        if not self.session.profile:
            messagebox.showinfo("No Profile", "No profile loaded in session.\n\n"
                              "Load a profile from:\n"
                              "- FIT Analysis tab (export profile), or\n"
                              "- Load Profile CSV button")
            return

        # Standard blackline positions: 10m intervals + 695 (200m start) + 895 (finish)
        # 0, 10, 20, ... 690, 695, 700, 710, ... 890, 895
        blackline_positions = [float(i) for i in range(0, 691, 10)]  # 0-690 in 10m
        blackline_positions.append(695.0)  # 200m start line
        blackline_positions.extend([float(i) for i in range(700, 891, 10)])  # 700-890 in 10m
        blackline_positions.append(895.0)  # Finish line

        # Interpolate y_m from session profile to standard positions
        s_profile = self.session.profile.s_m
        y_profile = self.session.profile.y_m.copy()

        # Scale y_m to current track width if profile comes from a wider track
        y_profile = scale_y_to_track_width(y_profile, self.track_model.track_width)

        # Calculate lap boundaries from current track geometry
        _, pursuit1, pursuit2, start_200 = self._get_lap_boundaries()

        # Clear existing positions
        self.track_positions = {0: [], 1: [], 2: [], 3: []}

        # Interpolate and assign to laps
        for s in blackline_positions:
            # Skip positions outside profile range
            if s < s_profile.min() or s > s_profile.max():
                continue

            y = float(np.interp(s, s_profile, y_profile))

            if s < pursuit1:
                self.track_positions[0].append((s, y))
            elif s < pursuit2:
                self.track_positions[1].append((s, y))
            elif s < start_200:
                self.track_positions[2].append((s, y))
            else:
                self.track_positions[3].append((s, y))

        # Update display
        self._update_display()

        lap_counts = [len(self.track_positions[i]) for i in range(4)]
        total_markers = sum(lap_counts)
        self.info_var.set(
            f"Loaded from session: {self.session.profile.source}\n"
            f"{total_markers} markers (10m intervals)"
        )
        self.status_callback(f"Loaded profile from session: {self.session.profile.source}")

    def _reset_marker_entries(self):
        """Reset entry fields to current marker values."""
        for lap, idx, y_var in self.marker_entries:
            if lap in self.track_positions and idx < len(self.track_positions[lap]):
                _, y = self.track_positions[lap][idx]
                y_var.set(f"{y:.2f}")
        self.info_var.set("Entries reset to current values")

    def _on_click(self, event):
        """Handle mouse click - select marker for dragging."""
        if event.inaxes != self.ax:
            return

        # Find nearest marker
        min_dist = float('inf')
        selected = None

        for i, marker in enumerate(self.markers):
            if marker is None:
                continue
            offsets = marker.get_offsets()
            if len(offsets) == 0:
                continue
            mx, my = offsets[0]
            dist = np.sqrt((event.xdata - mx)**2 + (event.ydata - my)**2)
            if dist < min_dist and dist < 5:  # Within 5 units
                min_dist = dist
                selected = i

        if selected is not None:
            self.dragging_marker = selected
            lap, idx, s = self.marker_data[selected]
            self.info_var.set(f"Dragging: L{lap}, s={s:.0f}m")

    def _on_drag(self, event):
        """Handle mouse drag - move selected marker."""
        if self.dragging_marker is None or event.inaxes != self.ax:
            return

        lap, idx, s = self.marker_data[self.dragging_marker]

        if lap not in self.track_positions or idx >= len(self.track_positions[lap]):
            return

        old_s, old_y = self.track_positions[lap][idx]

        # Get black line position at this s
        x_black, y_black, tx, ty, nx, ny = self.track_model.profile_to_xy(old_s, 0)

        # Project mouse position onto normal direction
        # new_y = distance from black line along normal
        dx = event.xdata - x_black
        dy = event.ydata - y_black
        new_y = dx * nx + dy * ny

        # Clamp to track bounds
        new_y = max(0, min(self.track_model.track_width, new_y))

        # Update position
        self.track_positions[lap][idx] = (old_s, new_y)

        # Update marker position visually
        new_x, new_y_vis, _, _, _, _ = self.track_model.profile_to_xy(old_s, new_y)
        self.markers[self.dragging_marker].set_offsets([[new_x, new_y_vis]])
        self.canvas.draw_idle()

        # Update entry in marker table
        for entry_lap, entry_idx, y_var in self.marker_entries:
            if entry_lap == lap and entry_idx == idx:
                y_var.set(f"{new_y:.2f}")
                break

        self.info_var.set(f"Dragging: s={old_s:.0f}m, y={new_y:.2f}m")

    def _on_release(self, event):
        """Handle mouse release."""
        if self.dragging_marker is not None:
            lap, idx, s = self.marker_data[self.dragging_marker]
            if lap in self.track_positions and idx < len(self.track_positions[lap]):
                s, y = self.track_positions[lap][idx]
                self.info_var.set(f"Updated: s={s:.0f}m, y={y:.2f}m")
            self.dragging_marker = None
            # Full redraw to update path lines
            self._update_display()

    def _on_session_changed(self):
        """Handle session data changes (observer callback).

        Updates the optimized line status label and refreshes profile graphs
        when new simulation data is available.
        """
        if self.session.last_optimized_y_m is not None:
            improvement = self.session.last_optimization_improvement_ms
            if improvement > 0:
                self.optimized_info_var.set(f"Available: -{improvement:.0f}ms (click Refresh)")
            elif improvement < 0:
                self.optimized_info_var.set(f"Available: +{-improvement:.0f}ms (click Refresh)")
            else:
                self.optimized_info_var.set("Available (click Refresh to view)")
        else:
            self.optimized_info_var.set("No optimization result")

        # Update profile graphs when new simulation data is available
        if hasattr(self, 'profile_canvas'):
            self._update_profile_graphs()

        # Update optimizer comparison table when optimization results change
        if hasattr(self, 'comparison_tree'):
            self._update_optimizer_comparison()

    def _apply_optimized_line(self):
        """Apply the optimized line to current track positions.

        Copies the optimized y_m values from session to track_positions,
        replacing the current line with the optimizer's recommended line.

        Uses standard blackline positions (10m intervals) for performance.
        """
        if self.session.last_optimized_y_m is None or self.session.last_optimized_s_m is None:
            messagebox.showinfo("No Optimized Line",
                               "No optimization result available.\n\n"
                               "Run the Energy Optimizer first to generate an optimized line.")
            return

        # Get optimized data, scaled to current track width
        opt_s = self.session.last_optimized_s_m
        opt_y = scale_y_to_track_width(self.session.last_optimized_y_m, self.track_model.track_width)

        # Standard blackline positions: 10m intervals + 695 + 895
        blackline_positions = [float(i) for i in range(0, 691, 10)]
        blackline_positions.append(695.0)
        blackline_positions.extend([float(i) for i in range(700, 891, 10)])
        blackline_positions.append(895.0)

        # Calculate lap boundaries from current track geometry
        _, pursuit1, pursuit2, start_200 = self._get_lap_boundaries()

        # Clear existing positions
        self.track_positions = {0: [], 1: [], 2: [], 3: []}

        # Interpolate optimized line to standard positions and assign to laps
        for s in blackline_positions:
            if s < opt_s.min() or s > opt_s.max():
                continue

            y = float(np.interp(s, opt_s, opt_y))

            if s < pursuit1:
                self.track_positions[0].append((s, y))
            elif s < pursuit2:
                self.track_positions[1].append((s, y))
            elif s < start_200:
                self.track_positions[2].append((s, y))
            else:
                self.track_positions[3].append((s, y))

        # Update display
        self._update_display()

        # Sync to session profile
        self._sync_to_session()

        improvement = self.session.last_optimization_improvement_ms
        total_markers = sum(len(self.track_positions[i]) for i in range(4))
        self.info_var.set(
            f"Applied optimized line (Δ{-improvement:+.0f}ms)\n"
            f"{total_markers} markers (10m intervals)"
        )
        self.status_callback("Applied optimized line to track positions")
