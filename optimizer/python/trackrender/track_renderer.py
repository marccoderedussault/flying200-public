# veloapp/track/track_renderer.py
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import LineCollection
from typing import Dict, Any, List, Tuple, Optional, Union
import logging

class TrackRenderer:
    """
    Renders the velodrome track with all markings and rider trajectories.
    Uses the exact same drawing approach as the original implementation.
    """
    
    def __init__(self, track_model, config=None):
        """
        Initialize the track renderer.
        
        Parameters:
        -----------
        track_model : TrackModel
            The track model to render
        config : object, optional
            Configuration object with rendering parameters
        """
        self.logger = logging.getLogger(__name__)
        self.track_model = track_model
        self.config = config
        
        # Track colors
        self.colors = {
            'infield': 'lightblue',
            'cote_azur': 'lightblue',
            'track_surface': 'bisque',
            'inner_edge': 'blue',
            'black_line': 'black',
            'red_line': 'red',
            'blue_line': 'blue',
            'outer_edge': 'black',
            'start_line': 'blue',
            'finish_line': 'red',
            'grid': '#CCCCCC'
        }
        
        # Visualization elements
        self.track_elements = []
        self.rider_elements = []
        
        # Internal state
        self._figure = None
        self._ax = None
    
    def set_track_model(self, track_model) -> None:
        """Set a new track model to render."""
        self.track_model = track_model
    
    def set_config(self, config) -> None:
        """Set a new configuration object."""
        self.config = config
    


    def draw_track(self, ax: plt.Axes) -> None:
        """
        Draw the velodrome track with all markings - NO LEGEND.
        """
        if not self.track_model or not self.config:
            self.logger.error("Cannot draw track: track model or configuration not set")
            return
        
        # Store reference to the axes
        self._ax = ax
        
        # Extract track data
        x_inner = self.track_model.x_inner
        y_inner = self.track_model.y_inner
        nx = self.track_model.nx
        ny = self.track_model.ny
        x_black = self.track_model.x_black
        y_black = self.track_model.y_black
        start_pos = self.track_model.start_pos
        start_normal = self.track_model.start_normal
        start_idx = self.track_model.start_idx
        finish_idx = self.track_model.finish_idx
        
        # Extract parameters
        black_line_position = self.config["BLACK_LINE_POSITION"]
        red_line_position = self.config["RED_LINE_POSITION"]
        blue_line_position = self.config["BLUE_LINE_POSITION"]
        cote_azur_width = self.config["COTE_AZUR_WIDTH"]
        track_width = self.config["W"]  # This is the rideable width from black line to outer edge
        sprint_distance = self.config["SPRINT_DISTANCE"]

        # Clear the axis
        ax.clear()

        # Calculate outer edge - track_width (7.5m) from black line outward
        # This matches the y_m convention: y=0 is black line, y=7.5 is outer edge
        x_outer = x_black + nx * track_width
        y_outer = y_black + ny * track_width
        
        # Create polygon for track surface (between black line and outer edge)
        track_x = np.concatenate([x_black, np.flip(x_outer)])
        track_y = np.concatenate([y_black, np.flip(y_outer)])
        
        track_area = Polygon(np.column_stack([track_x, track_y]), closed=True,
                            fill=True, color=self.colors['track_surface'], alpha=0.7)
        ax.add_patch(track_area)
        
        # Create polygon for Côte d'Azur (between inner edge and black line)
        cote_polygon_x = np.concatenate([x_inner, np.flip(x_black)])
        cote_polygon_y = np.concatenate([y_inner, np.flip(y_black)])
        
        cote_area = Polygon(np.column_stack([cote_polygon_x, cote_polygon_y]), closed=True,
                            fill=True, color=self.colors['cote_azur'], alpha=0.7)
        ax.add_patch(cote_area)
        
        # Fill infield
        infield = Polygon(np.column_stack([x_inner, y_inner]), closed=True, 
                        fill=True, color=self.colors['infield'], alpha=0.3)
        ax.add_patch(infield)
        
        # Draw inner edge as a thin blue line (dashed) - NO LABEL
        inner_edge = ax.plot(x_inner, y_inner, 'b--', linewidth=1, alpha=0.7)[0]
        
        # Draw black line - NO LABEL
        black_line = ax.plot(x_black, y_black, 'k-', linewidth=2)[0]

        # Draw the other track lines going OUTWARD from black line - NO LABELS
        # Positions are now directly from black line (y=0), matching y_m convention
        line_positions = [
            (red_line_position, self.colors['red_line']),      # ~2.45m from black line
            (blue_line_position, self.colors['blue_line']),    # ~3.45m from black line
            (track_width, self.colors['outer_edge'])           # 7.5m from black line
        ]

        # Draw all track lines going outward from black line
        other_lines = []
        for pos, color in line_positions:
            # Calculate points at this distance from black line
            line_x = x_black + nx * pos
            line_y = y_black + ny * pos

            # Draw the line - NO LABEL
            line = ax.plot(line_x, line_y, color=color, linewidth=2)[0]
            other_lines.append(line)

        # Draw finish line - from inner edge (côte d'azur) to outer edge
        # Inner edge is at -black_line_position from black line
        # Outer edge is at track_width from black line
        total_line_width = black_line_position + track_width  # 0.85 + 7.5 = 8.35m
        finish_line_x = np.array([x_black[finish_idx] - nx[finish_idx] * black_line_position +
                                  t * nx[finish_idx] * total_line_width for t in np.linspace(0, 1, 20)])
        finish_line_y = np.array([y_black[finish_idx] - ny[finish_idx] * black_line_position +
                                  t * ny[finish_idx] * total_line_width for t in np.linspace(0, 1, 20)])

        # Draw start line from inner edge to outer edge
        start_inner_x = start_pos[0] - start_normal[0] * black_line_position
        start_inner_y = start_pos[1] - start_normal[1] * black_line_position

        start_outer_x = start_pos[0] + start_normal[0] * track_width
        start_outer_y = start_pos[1] + start_normal[1] * track_width

        start_line_x = np.linspace(start_inner_x, start_outer_x, 20)
        start_line_y = np.linspace(start_inner_y, start_outer_y, 20)
        
        # Draw the lines - NO LABELS
        finish_line = ax.plot(finish_line_x, finish_line_y, 'k-', linewidth=3)[0]
        start_line = ax.plot(start_line_x, start_line_y, 'k--', linewidth=3)[0]
        
        # Mark start/finish points on the black line - NO LABELS
        finish_point = ax.plot(x_black[finish_idx], y_black[finish_idx], 'ro', markersize=8)[0]
        start_point = ax.plot(start_pos[0], start_pos[1], 'bo', markersize=8)[0]
        
        # Set plot properties
        ax.set_aspect('equal')
        ax.grid(True, linestyle='--', alpha=0.5, color=self.colors['grid'])
        ax.set_title(f'Velodrome Track (250m Black Line, {sprint_distance}m Sprint)', fontsize=14)
        ax.set_xlabel('X (m)', fontsize=12)
        ax.set_ylabel('Y (m)', fontsize=12)

        # Set the axis limits
        ax.set_xlim([min(x_outer) - 5, max(x_outer) + 5])
        ax.set_ylim([min(y_outer) - 5, max(y_outer) + 5])

        # Add section labels outside the track (beyond outer wall)
        # Track geometry: Bottom Straight (0-59m), Right Curve (59-125m),
        #                 Top Straight (125-184m), Left Curve (184-250m)
        L = self.config["L_BLACK"]
        a = self.config["a_BLACK"]

        # Label positions outside the outer edge
        label_offset = track_width + 2  # Distance from black line to label (outside outer wall)

        # Home Straight (bottom) - center of bottom straight
        ax.text(L/2, -a - label_offset, 'Home Straight',
                ha='center', va='top', fontsize=9, color='#444444', style='italic')

        # Back Straight (top) - center of top straight
        ax.text(L/2, a + label_offset, 'Back Straight',
                ha='center', va='bottom', fontsize=9, color='#444444', style='italic')

        # C1 - Right bend bottom part (bottom half of right curve)
        ax.text(L + a + label_offset, -a/2, 'C1',
                ha='left', va='center', fontsize=9, color='#444444', fontweight='bold')

        # C2 - Right bend top part (top half of right curve)
        ax.text(L + a + label_offset, a/2, 'C2',
                ha='left', va='center', fontsize=9, color='#444444', fontweight='bold')

        # C3 - Left bend top part (top half of left curve)
        ax.text(-a - label_offset, a/2, 'C3',
                ha='right', va='center', fontsize=9, color='#444444', fontweight='bold')

        # C4 - Left bend bottom part (bottom half of left curve)
        ax.text(-a - label_offset, -a/2, 'C4',
                ha='right', va='center', fontsize=9, color='#444444', fontweight='bold')

        # NO LEGEND - removed completely
        self.draw_pursuit_lines(ax)
        # Store track elements
        self.track_elements = [
            track_area, cote_area, infield, inner_edge, black_line,
            *other_lines, finish_line, start_line, finish_point, start_point
        ]


    def draw_rider_trajectory(self, rider_data, ax: plt.Axes = None) -> None:
        """
        Draw rider trajectory on the track with color representing speed.
        Preserves the exact same visualization approach as visualize_flying_200m_with_height.
        
        Parameters:
        -----------
        rider_data : pd.DataFrame
            DataFrame with rider trajectory data
        ax : plt.Axes, optional
            Matplotlib axes to draw on, defaults to the current axes
        """
        if ax is None:
            ax = self._ax
        
        if ax is None:
            self.logger.error("Cannot draw trajectory: no axes available")
            return
        
        if rider_data is None or len(rider_data) == 0:
            self.logger.error("Cannot draw trajectory: no rider data")
            return
        
        # Clear any previous rider elements
        for elem in self.rider_elements:
            try:
                elem.remove()
            except:
                pass
        self.rider_elements = []
        
        # Save the xlim and ylim before adding the trajectory
        x_lim = ax.get_xlim()
        y_lim = ax.get_ylim()
        
        # Extract rider position data
        rider_x = rider_data['x_position'].values
        rider_y = rider_data['y_position'].values
        speeds = rider_data['speed_kph'].values
        
        # Plot trajectory on velodrome with color representing speed
        norm = plt.Normalize(speeds.min(), speeds.max())
        cmap = plt.cm.plasma
        
        points = np.array([rider_x, rider_y]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        
        lc = LineCollection(segments, cmap=cmap, norm=norm, linewidth=3)
        lc.set_array(speeds[:-1])
        line = ax.add_collection(lc)
        
        # Restore the xlim and ylim to maintain the view
        ax.set_xlim(x_lim)
        ax.set_ylim(y_lim)
        
        # Mark key points
        # Start of the effort
        start_effort = ax.plot(rider_x[0], rider_y[0], 'go', markersize=10, label='Start Effort')[0]
        
        # Find the sprint start point (200m from finish)
        true_distances = rider_data['true_distance_m'].values
        finish_distance = true_distances[-1]
        sprint_distance = self.config["SPRINT_DISTANCE"]
        sprint_start_distance = finish_distance - sprint_distance
        sprint_start_idx = np.argmin(np.abs(true_distances - sprint_start_distance))
        
        # Mark the sprint start
        sprint_start = ax.plot(rider_x[sprint_start_idx], rider_y[sprint_start_idx], 'bo', 
                            markersize=10, label='Start 200m')[0]
        
        # Mark finish
        finish = ax.plot(rider_x[-1], rider_y[-1], 'ro', markersize=10, label='Finish')[0]
        
        # Find the exact 200m start point by interpolation
        exact_finish_distance = true_distances[-1]
        exact_start_distance = exact_finish_distance - sprint_distance
        exact_start_time = self._interpolate_time(true_distances, exact_start_distance, rider_data)
        exact_finish_time = float(rider_data['time_s'].iloc[-1])

        # Calculate precise sprint time
        sprint_time = exact_finish_time - exact_start_time
        
        # Calculate TRUE average speed from distance and time
        avg_speed = (sprint_distance / sprint_time) * 3.6  # Convert m/s to km/h

        # Add annotation with stats
        avg_speed = rider_data['speed_kph'][sprint_start_idx:].mean()
        max_speed = rider_data['speed_kph'][sprint_start_idx:].max()
        avg_cadence = rider_data['cadence_rpm'][sprint_start_idx:].mean()
        avg_power = rider_data['power_watts'][sprint_start_idx:].mean()
        
        info_text = (
            f'200m Time: {sprint_time:.3f}s\n'
            f'Avg Speed: {avg_speed:.1f} km/h\n'
            f'Max Speed: {max_speed:.1f} km/h\n'
            f'Avg Cadence: {avg_cadence:.0f} rpm\n'
            f'Avg Power: {avg_power:.0f} W'
        )
            
        # Add text box with rider stats
        props = dict(boxstyle='round', facecolor='white', alpha=0.7)
        text_box = ax.text(0.05, 0.95, info_text, transform=ax.transAxes, fontsize=10,
                verticalalignment='top', bbox=props)
        
        # Store rider elements
        self.rider_elements = [lc, start_effort, sprint_start, finish, text_box]
        
        return sprint_time
    
    def _interpolate_time(self, distance, target_distance, data):
        """
        Interpolate to find the precise time at a specific distance.
        
        Parameters:
        -----------
        distance : np.array
            Array of distances
        target_distance : float
            Target distance to find time for
        data : pd.DataFrame
            DataFrame with rider data
            
        Returns:
        --------
        float
            Interpolated time
        """
        # Find the points before and after the target distance
        idx = np.where(data['true_distance_m'] >= target_distance)[0]
        if len(idx) == 0:  # Target is beyond last point
            return float(data['time_s'].iloc[-1])
        
        idx_after = idx[0]
        if idx_after == 0:  # Target is before first point
            return float(data['time_s'].iloc[0])
        
        idx_before = idx_after - 1
        
        # Get distances and times for the points before and after
        d1 = data['true_distance_m'].iloc[idx_before]
        d2 = data['true_distance_m'].iloc[idx_after]
        t1 = data['time_s'].iloc[idx_before]
        t2 = data['time_s'].iloc[idx_after]
        
        # Linearly interpolate
        if d2 == d1:  # Avoid division by zero
            return float(t1)
        
        t = t1 + (t2 - t1) * (target_distance - d1) / (d2 - d1)
        return float(t)
    
    def clear(self, ax: plt.Axes = None) -> None:
        """
        Clear all track and rider elements.
        
        Parameters:
        -----------
        ax : plt.Axes, optional
            Matplotlib axes to clear
        """
        if ax is None:
            ax = self._ax
        
        if ax is None:
            return
        
        # Clear the axis
        ax.clear()
        
        # Reset elements
        self.track_elements = []
        self.rider_elements = []

    def draw_pursuit_lines(self, ax: plt.Axes) -> None:
        """
        Draw the Top and Bottom Pursuit Lines on the track.
        These are used for precise lap counting.
        
        Parameters:
        -----------
        ax : plt.Axes
            Matplotlib axes to draw on
        """
        try:
            if not self.track_model:
                self.logger.error("Cannot draw pursuit lines: no track model")
                return
            
            if not hasattr(self.track_model, 'get_pursuit_lines'):
                self.logger.error("Track model does not have get_pursuit_lines method")
                return
            
            # Get pursuit line data
            pursuit_lines = self.track_model.get_pursuit_lines()
            if not pursuit_lines or not pursuit_lines[0] or not pursuit_lines[1]:
                self.logger.error("Failed to get pursuit line data")
                return
            
            top_pursuit_data, bottom_pursuit_data = pursuit_lines
            top_distance, top_pos = top_pursuit_data
            bottom_distance, bottom_pos = bottom_pursuit_data
            
            self.logger.info(f"Drawing pursuit lines - Top: {top_distance:.1f}m, Bottom: {bottom_distance:.1f}m")
            
            # Get track geometry at pursuit line positions
            top_full_pos = self.track_model.calculate_position_from_distance(top_distance)
            bottom_full_pos = self.track_model.calculate_position_from_distance(bottom_distance)
            
            # Extract normal vectors for drawing lines across track
            top_nx, top_ny = top_full_pos[2], top_full_pos[3]
            bottom_nx, bottom_ny = bottom_full_pos[2], bottom_full_pos[3]
            
            # Calculate line endpoints (from inner edge to outer edge)
            # Inner edge is at -black_line_position from black line (côte d'azur)
            # Outer edge is at +track_width from black line
            black_line_position = self.config["BLACK_LINE_POSITION"]
            track_width = self.config["W"]

            # Top Pursuit Line - from côte d'azur to outer edge
            top_inner_x = top_pos[0] - top_nx * black_line_position
            top_inner_y = top_pos[1] - top_ny * black_line_position
            top_outer_x = top_pos[0] + top_nx * track_width
            top_outer_y = top_pos[1] + top_ny * track_width

            # Bottom Pursuit Line - from côte d'azur to outer edge
            bottom_inner_x = bottom_pos[0] - bottom_nx * black_line_position
            bottom_inner_y = bottom_pos[1] - bottom_ny * black_line_position
            bottom_outer_x = bottom_pos[0] + bottom_nx * track_width
            bottom_outer_y = bottom_pos[1] + bottom_ny * track_width
            
            # Draw the pursuit lines
            top_pursuit_line = ax.plot([top_inner_x, top_outer_x], [top_inner_y, top_outer_y],
                                    'r-', linewidth=4, alpha=0.9, label='Top Pursuit')[0]
            bottom_pursuit_line = ax.plot([bottom_inner_x, bottom_outer_x], [bottom_inner_y, bottom_outer_y],
                                        'r-', linewidth=4, alpha=0.9, label='Bottom Pursuit')[0]

            # Store pursuit line elements
            self.track_elements.extend([top_pursuit_line, bottom_pursuit_line])
            
            self.logger.info("Successfully drew pursuit lines")
            
        except Exception as e:
            self.logger.error(f"Error drawing pursuit lines: {e}")
            import traceback
            self.logger.error(traceback.format_exc())