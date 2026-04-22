"""
Flying 200 V2 - Professional Charts Module

Clean, segment-labeled visualizations for simulation results.
Addresses the "charts are ugly" pain point with:
- Named segment labels on x-axis
- Consistent color palette
- Data source in chart title
- Proper layout and spacing
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from typing import Optional, Dict, List, Tuple
import tkinter as tk

# =============================================================================
# Color Palette - Professional and Consistent
# =============================================================================

COLORS = {
    'base': '#2563EB',      # Blue - baseline results
    'modified': '#DC2626',  # Red - modified/optimized results
    'power': '#16A34A',     # Green - power data
    'speed': '#9333EA',     # Purple - velocity data
    'cda': '#EA580C',       # Orange - aerodynamic data
    'standing': '#EF4444',  # Red - standing position
    'seated': '#3B82F6',    # Blue - seated position
    'grid': '#E5E7EB',      # Light gray - grid lines
    'text': '#1F2937',      # Dark gray - text
    'background': '#FFFFFF', # White - background
}

# Standard figure sizes
FIG_SIZE_SMALL = (8, 4)
FIG_SIZE_MEDIUM = (10, 5)
FIG_SIZE_LARGE = (12, 6)
FIG_SIZE_WIDE = (14, 5)


# =============================================================================
# Segment Labeling
# =============================================================================

def add_segment_labels(
    ax: plt.Axes,
    s_grid: np.ndarray,
    get_segment_name_func,
    n_labels: int = 8,
    label_y_offset: float = -0.15,
):
    """
    Add segment name labels below the x-axis.

    Args:
        ax: Matplotlib axes
        s_grid: Distance grid
        get_segment_name_func: Function(s_m) -> segment_name
        n_labels: Number of labels to show
        label_y_offset: Y offset for labels (normalized axes coords)
    """
    # Select evenly spaced points
    s_min, s_max = s_grid.min(), s_grid.max()
    label_positions = np.linspace(s_min, s_max, n_labels)

    for s in label_positions:
        segment_name = get_segment_name_func(s)
        ax.annotate(
            segment_name,
            xy=(s, 0),
            xycoords=('data', 'axes fraction'),
            xytext=(0, label_y_offset * 100),
            textcoords='offset points',
            ha='center',
            va='top',
            fontsize=7,
            color=COLORS['text'],
            rotation=45,
        )


def add_segment_shading(
    ax: plt.Axes,
    s_grid: np.ndarray,
    track_geometry,
    alpha: float = 0.1,
):
    """
    Add alternating background shading for track segments.

    Args:
        ax: Matplotlib axes
        s_grid: Distance grid
        track_geometry: TrackGeometry with segment definitions
        alpha: Shading opacity
    """
    s_min, s_max = s_grid.min(), s_grid.max()

    for i, segment in enumerate(track_geometry.segments):
        if segment.end_m < s_min or segment.start_m > s_max:
            continue

        start = max(segment.start_m, s_min)
        end = min(segment.end_m, s_max)

        # Alternate between gray and white
        if i % 2 == 0:
            ax.axvspan(start, end, alpha=alpha, color='gray', zorder=0)


# =============================================================================
# Chart Functions
# =============================================================================

def create_velocity_chart(
    s_grid: np.ndarray,
    v_base: np.ndarray,
    v_mod: Optional[np.ndarray] = None,
    data_source: str = "",
    get_segment_func=None,
    figsize: Tuple[int, int] = FIG_SIZE_MEDIUM,
) -> Figure:
    """
    Create velocity vs distance chart.

    Args:
        s_grid: Distance array [m]
        v_base: Baseline velocity [m/s]
        v_mod: Modified velocity [m/s] (optional)
        data_source: String describing data source for title
        get_segment_func: Function to get segment names
        figsize: Figure size

    Returns:
        Matplotlib Figure
    """
    fig, ax = plt.subplots(figsize=figsize, facecolor=COLORS['background'])

    # Convert to km/h
    v_base_kph = v_base * 3.6
    ax.plot(s_grid, v_base_kph, color=COLORS['base'], linewidth=1.5, label='Baseline')

    if v_mod is not None:
        v_mod_kph = v_mod * 3.6
        ax.plot(s_grid, v_mod_kph, color=COLORS['modified'], linewidth=1.5, label='Modified')

    # Styling
    ax.set_xlabel('Distance (m)', fontsize=10, color=COLORS['text'])
    ax.set_ylabel('Velocity (km/h)', fontsize=10, color=COLORS['text'])
    ax.grid(True, alpha=0.3, color=COLORS['grid'])
    ax.legend(loc='lower right', framealpha=0.9)

    # Title with data source
    title = 'Velocity Profile'
    if data_source:
        title += f'\n{data_source}'
    ax.set_title(title, fontsize=11, color=COLORS['text'])

    # Segment labels
    if get_segment_func is not None:
        add_segment_labels(ax, s_grid, get_segment_func)

    plt.tight_layout()
    return fig


def create_power_chart(
    s_grid: np.ndarray,
    P_base: np.ndarray,
    P_mod: Optional[np.ndarray] = None,
    data_source: str = "",
    get_segment_func=None,
    figsize: Tuple[int, int] = FIG_SIZE_MEDIUM,
) -> Figure:
    """
    Create power vs distance chart.

    Args:
        s_grid: Distance array [m]
        P_base: Baseline power [W]
        P_mod: Modified power [W] (optional)
        data_source: String describing data source
        get_segment_func: Function to get segment names
        figsize: Figure size

    Returns:
        Matplotlib Figure
    """
    fig, ax = plt.subplots(figsize=figsize, facecolor=COLORS['background'])

    ax.plot(s_grid, P_base, color=COLORS['base'], linewidth=1.5, label='Baseline')

    if P_mod is not None:
        ax.plot(s_grid, P_mod, color=COLORS['modified'], linewidth=1.5, label='Modified')

    # Styling
    ax.set_xlabel('Distance (m)', fontsize=10, color=COLORS['text'])
    ax.set_ylabel('Power (W)', fontsize=10, color=COLORS['text'])
    ax.grid(True, alpha=0.3, color=COLORS['grid'])
    ax.legend(loc='upper right', framealpha=0.9)

    # Title with data source
    title = 'Power Profile'
    if data_source:
        title += f'\n{data_source}'
    ax.set_title(title, fontsize=11, color=COLORS['text'])

    # Segment labels
    if get_segment_func is not None:
        add_segment_labels(ax, s_grid, get_segment_func)

    plt.tight_layout()
    return fig


def create_combined_chart(
    s_grid: np.ndarray,
    result: Dict,
    data_source: str = "",
    get_segment_func=None,
    figsize: Tuple[int, int] = FIG_SIZE_WIDE,
) -> Figure:
    """
    Create combined chart with velocity, power, and CdA subplots.

    Args:
        s_grid: Distance array [m]
        result: Simulation result dict with 'v', 'P_eff', 'CdA' keys
        data_source: String describing data source
        get_segment_func: Function to get segment names
        figsize: Figure size

    Returns:
        Matplotlib Figure
    """
    fig, axes = plt.subplots(3, 1, figsize=figsize, sharex=True, facecolor=COLORS['background'])

    v = result.get('v', np.zeros_like(s_grid))
    P = result.get('P_eff', np.zeros_like(s_grid))
    CdA = result.get('CdA', np.zeros_like(s_grid))

    # Velocity subplot
    axes[0].plot(s_grid, v * 3.6, color=COLORS['speed'], linewidth=1.5)
    axes[0].set_ylabel('Velocity (km/h)', fontsize=9, color=COLORS['text'])
    axes[0].grid(True, alpha=0.3, color=COLORS['grid'])

    # Power subplot
    axes[1].plot(s_grid, P, color=COLORS['power'], linewidth=1.5)
    axes[1].set_ylabel('Power (W)', fontsize=9, color=COLORS['text'])
    axes[1].grid(True, alpha=0.3, color=COLORS['grid'])

    # CdA subplot
    axes[2].plot(s_grid, CdA, color=COLORS['cda'], linewidth=1.5)
    axes[2].set_ylabel('CdA (m²)', fontsize=9, color=COLORS['text'])
    axes[2].set_xlabel('Distance (m)', fontsize=9, color=COLORS['text'])
    axes[2].grid(True, alpha=0.3, color=COLORS['grid'])

    # Segment labels on bottom subplot
    if get_segment_func is not None:
        add_segment_labels(axes[2], s_grid, get_segment_func)

    # Title
    title = 'Simulation Results'
    if data_source:
        title += f' | {data_source}'
    fig.suptitle(title, fontsize=11, color=COLORS['text'])

    plt.tight_layout()
    return fig


def create_comparison_chart(
    s_grid: np.ndarray,
    base_result: Dict,
    mod_result: Dict,
    data_source: str = "",
    get_segment_func=None,
    figsize: Tuple[int, int] = FIG_SIZE_WIDE,
) -> Figure:
    """
    Create comparison chart between baseline and modified results.

    Args:
        s_grid: Distance array [m]
        base_result: Baseline simulation result
        mod_result: Modified simulation result
        data_source: String describing data source
        get_segment_func: Function to get segment names
        figsize: Figure size

    Returns:
        Matplotlib Figure
    """
    fig, axes = plt.subplots(2, 1, figsize=figsize, sharex=True, facecolor=COLORS['background'])

    v_base = base_result.get('v', np.zeros_like(s_grid))
    v_mod = mod_result.get('v', np.zeros_like(s_grid))

    P_base = base_result.get('P_eff', np.zeros_like(s_grid))
    P_mod = mod_result.get('P_eff', np.zeros_like(s_grid))

    # Velocity comparison
    axes[0].plot(s_grid, v_base * 3.6, color=COLORS['base'], linewidth=1.5, label='Baseline')
    axes[0].plot(s_grid, v_mod * 3.6, color=COLORS['modified'], linewidth=1.5, label='Modified')
    axes[0].set_ylabel('Velocity (km/h)', fontsize=9, color=COLORS['text'])
    axes[0].grid(True, alpha=0.3, color=COLORS['grid'])
    axes[0].legend(loc='lower right', framealpha=0.9, fontsize=8)

    # Power comparison
    axes[1].plot(s_grid, P_base, color=COLORS['base'], linewidth=1.5, label='Baseline')
    axes[1].plot(s_grid, P_mod, color=COLORS['modified'], linewidth=1.5, label='Modified')
    axes[1].set_ylabel('Power (W)', fontsize=9, color=COLORS['text'])
    axes[1].set_xlabel('Distance (m)', fontsize=9, color=COLORS['text'])
    axes[1].grid(True, alpha=0.3, color=COLORS['grid'])
    axes[1].legend(loc='upper right', framealpha=0.9, fontsize=8)

    # Time comparison in title
    t_base = base_result.get('T_200', 0)
    t_mod = mod_result.get('T_200', 0)
    delta = (t_mod - t_base) * 1000  # ms

    title = f'Baseline vs Modified | 200m: {t_base:.3f}s → {t_mod:.3f}s ({delta:+.1f}ms)'
    if data_source:
        title += f'\n{data_source}'
    fig.suptitle(title, fontsize=11, color=COLORS['text'])

    # Segment labels
    if get_segment_func is not None:
        add_segment_labels(axes[1], s_grid, get_segment_func)

    plt.tight_layout()
    return fig


def create_optimization_chart(
    s_grid: np.ndarray,
    segments: List[Dict],
    positions: List[str],
    P_grid: np.ndarray,
    data_source: str = "",
    figsize: Tuple[int, int] = FIG_SIZE_MEDIUM,
) -> Figure:
    """
    Create optimization results chart showing power allocation and positions.

    Args:
        s_grid: Distance array [m]
        segments: List of segment dicts with 'start_m', 'end_m', 'energy_J'
        positions: List of 'standing' or 'seated' per segment
        P_grid: Power grid array [W]
        data_source: String describing data source
        figsize: Figure size

    Returns:
        Matplotlib Figure
    """
    fig, ax = plt.subplots(figsize=figsize, facecolor=COLORS['background'])

    # Plot power profile
    ax.plot(s_grid, P_grid, color=COLORS['power'], linewidth=1.5)

    # Shade segments by position
    for seg, pos in zip(segments, positions):
        color = COLORS['standing'] if pos == 'standing' else COLORS['seated']
        ax.axvspan(seg['start_m'], seg['end_m'], alpha=0.15, color=color)

    # Styling
    ax.set_xlabel('Distance (m)', fontsize=10, color=COLORS['text'])
    ax.set_ylabel('Power (W)', fontsize=10, color=COLORS['text'])
    ax.grid(True, alpha=0.3, color=COLORS['grid'])

    # Legend for positions
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=COLORS['standing'], alpha=0.3, label='Standing'),
        Patch(facecolor=COLORS['seated'], alpha=0.3, label='Seated'),
    ]
    ax.legend(handles=legend_elements, loc='upper right', framealpha=0.9)

    # Title
    title = 'Optimized Power Allocation'
    if data_source:
        title += f'\n{data_source}'
    ax.set_title(title, fontsize=11, color=COLORS['text'])

    plt.tight_layout()
    return fig


# =============================================================================
# Track Visualization
# =============================================================================

def create_track_view(
    track_geometry,
    highlight_distance: Optional[float] = None,
    show_200m_zone: bool = True,
    figsize: Tuple[int, int] = FIG_SIZE_MEDIUM,
) -> Figure:
    """
    Create a top-down view of the velodrome track.

    Shows:
    - Track outline (black line)
    - Segment boundaries
    - 200m zone highlighted
    - Key distance markers (finish, 200m start, pursuit line)

    Args:
        track_geometry: TrackGeometry object with track parameters
        highlight_distance: Optional distance to highlight (e.g., current position)
        show_200m_zone: Whether to shade the 200m timed zone
        figsize: Figure size

    Returns:
        Matplotlib Figure
    """
    fig, ax = plt.subplots(figsize=figsize, facecolor=COLORS['background'])

    # Extract track parameters
    straight_len = track_geometry.straight_length_m
    radius = track_geometry.turn_radius_m
    lap_len = track_geometry.length_m

    # Calculate track coordinates
    # Track layout: HomeStraight -> Turn1/Turn2 (right bend) -> BackStraight -> Turn3/Turn4 (left bend)
    # Origin at center of track

    # Build track path
    num_points = 200
    x_track = []
    y_track = []

    # Home straight (bottom, left to right)
    for i in range(num_points // 4):
        t = i / (num_points // 4)
        x_track.append(-straight_len / 2 + t * straight_len)
        y_track.append(-radius)

    # Right bend (Turn 1 & 2)
    for i in range(num_points // 4):
        angle = -np.pi / 2 + i / (num_points // 4) * np.pi
        x_track.append(straight_len / 2 + radius * np.cos(angle))
        y_track.append(radius * np.sin(angle))

    # Back straight (top, right to left)
    for i in range(num_points // 4):
        t = i / (num_points // 4)
        x_track.append(straight_len / 2 - t * straight_len)
        y_track.append(radius)

    # Left bend (Turn 3 & 4)
    for i in range(num_points // 4):
        angle = np.pi / 2 + i / (num_points // 4) * np.pi
        x_track.append(-straight_len / 2 + radius * np.cos(angle))
        y_track.append(radius * np.sin(angle))

    # Close the track
    x_track.append(x_track[0])
    y_track.append(y_track[0])

    # Draw track outline
    ax.plot(x_track, y_track, color='#1F2937', linewidth=3, label='Black Line')

    # Draw track surface (inner)
    track_surface = plt.Polygon(list(zip(x_track, y_track)),
                                 fill=True, facecolor='#E5E7EB', edgecolor='none', alpha=0.3)
    ax.add_patch(track_surface)

    # Mark key positions
    # Finish line at start of home straight
    ax.plot([-straight_len / 2, -straight_len / 2], [-radius - 5, -radius + 5],
            color='red', linewidth=3, label='Finish Line')

    # 200m start marker (695m from pursuit line, ~195m from finish going backwards)
    # In standard Flying 200: s=0 at pursuit line (mid back straight)
    # 200m zone = 695m to 895m from pursuit line
    if show_200m_zone:
        # Shade 200m zone - last 200m before finish
        # This is approximately the home straight + entry turn
        ax.axvspan(-straight_len / 2, straight_len / 2 + radius * 0.3,
                   ymin=0, ymax=0.45, alpha=0.2, color='red', label='200m Zone')

    # Pursuit line at mid back straight
    ax.plot([0, 0], [radius - 5, radius + 5],
            color='blue', linewidth=2, linestyle='--', label='Pursuit Line')

    # Add segment labels
    ax.text(0, -radius - 12, 'Home Straight', ha='center', fontsize=9, color=COLORS['text'])
    ax.text(0, radius + 12, 'Back Straight', ha='center', fontsize=9, color=COLORS['text'])
    ax.text(straight_len / 2 + radius + 8, 0, 'Turn 1/2', ha='left', fontsize=9, color=COLORS['text'])
    ax.text(-straight_len / 2 - radius - 8, 0, 'Turn 3/4', ha='right', fontsize=9, color=COLORS['text'])

    # Add track info text box
    info_text = (
        f"{track_geometry.name}\n"
        f"Lap: {lap_len:.0f}m\n"
        f"Straights: {straight_len:.1f}m\n"
        f"Turn Radius: {radius:.1f}m\n"
        f"Banking: {track_geometry.banking_straight_deg:.0f}°/{track_geometry.banking_turn_deg:.0f}°"
    )
    props = dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='gray')
    ax.text(0.02, 0.98, info_text, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', bbox=props, color=COLORS['text'])

    # Styling
    ax.set_aspect('equal')
    ax.set_xlim(-straight_len / 2 - radius - 30, straight_len / 2 + radius + 30)
    ax.set_ylim(-radius - 30, radius + 30)
    ax.axis('off')

    title = f"Track Layout: {track_geometry.name}"
    ax.set_title(title, fontsize=12, color=COLORS['text'], pad=10)

    # Legend
    ax.legend(loc='lower right', fontsize=8, framealpha=0.9)

    plt.tight_layout()
    return fig


def create_track_comparison(
    track1,
    track2,
    figsize: Tuple[int, int] = FIG_SIZE_WIDE,
) -> Figure:
    """
    Create side-by-side comparison of two tracks.

    Args:
        track1: First TrackGeometry
        track2: Second TrackGeometry
        figsize: Figure size

    Returns:
        Matplotlib Figure
    """
    fig, axes = plt.subplots(1, 2, figsize=figsize, facecolor=COLORS['background'])

    for ax, track in zip(axes, [track1, track2]):
        straight_len = track.straight_length_m
        radius = track.turn_radius_m

        # Build track path
        num_points = 200
        x_track = []
        y_track = []

        # Home straight
        for i in range(num_points // 4):
            t = i / (num_points // 4)
            x_track.append(-straight_len / 2 + t * straight_len)
            y_track.append(-radius)

        # Right bend
        for i in range(num_points // 4):
            angle = -np.pi / 2 + i / (num_points // 4) * np.pi
            x_track.append(straight_len / 2 + radius * np.cos(angle))
            y_track.append(radius * np.sin(angle))

        # Back straight
        for i in range(num_points // 4):
            t = i / (num_points // 4)
            x_track.append(straight_len / 2 - t * straight_len)
            y_track.append(radius)

        # Left bend
        for i in range(num_points // 4):
            angle = np.pi / 2 + i / (num_points // 4) * np.pi
            x_track.append(-straight_len / 2 + radius * np.cos(angle))
            y_track.append(radius * np.sin(angle))

        x_track.append(x_track[0])
        y_track.append(y_track[0])

        # Draw track
        ax.plot(x_track, y_track, color='#1F2937', linewidth=2)
        track_surface = plt.Polygon(list(zip(x_track, y_track)),
                                     fill=True, facecolor='#E5E7EB', edgecolor='none', alpha=0.3)
        ax.add_patch(track_surface)

        # Track info
        info_text = (
            f"Straights: {straight_len:.1f}m\n"
            f"Turn Radius: {radius:.1f}m\n"
            f"Banking: {track.banking_straight_deg:.0f}°/{track.banking_turn_deg:.0f}°"
        )
        props = dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='gray')
        ax.text(0.02, 0.98, info_text, transform=ax.transAxes, fontsize=9,
                verticalalignment='top', bbox=props)

        ax.set_aspect('equal')
        ax.set_xlim(-straight_len / 2 - radius - 20, straight_len / 2 + radius + 20)
        ax.set_ylim(-radius - 20, radius + 20)
        ax.axis('off')
        ax.set_title(track.name, fontsize=11, color=COLORS['text'])

    fig.suptitle('Track Comparison', fontsize=12, color=COLORS['text'])
    plt.tight_layout()
    return fig


# =============================================================================
# Tkinter Integration
# =============================================================================

class ChartCanvas:
    """
    Wrapper for embedding Matplotlib charts in Tkinter.
    """

    def __init__(self, parent: tk.Widget, figsize: Tuple[int, int] = FIG_SIZE_MEDIUM):
        """
        Initialize chart canvas.

        Args:
            parent: Tkinter parent widget
            figsize: Default figure size
        """
        self.parent = parent
        self.figsize = figsize
        self.canvas = None
        self.current_fig = None

    def show_figure(self, fig: Figure):
        """
        Display a matplotlib figure in the canvas.

        Args:
            fig: Matplotlib Figure to display
        """
        # Clear previous
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()

        if self.current_fig is not None:
            plt.close(self.current_fig)

        # Create new canvas
        self.current_fig = fig
        self.canvas = FigureCanvasTkAgg(fig, master=self.parent)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def clear(self):
        """Clear the canvas."""
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
            self.canvas = None

        if self.current_fig is not None:
            plt.close(self.current_fig)
            self.current_fig = None

    def save(self, filepath: str, dpi: int = 150):
        """
        Save current figure to file.

        Args:
            filepath: Output file path
            dpi: Resolution in dots per inch
        """
        if self.current_fig is not None:
            self.current_fig.savefig(filepath, dpi=dpi, bbox_inches='tight')
