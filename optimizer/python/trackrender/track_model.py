# veloapp/track/track_model.py
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional
import logging

class TrackModel:
    """
    Handles track geometry calculations and segment definitions.
    Maintains the exact same mathematical approach as the original implementation.
    """
    
    def __init__(self, config=None):
        """
        Initialize the track model with configuration parameters.
        
        Parameters:
        -----------
        config : object, optional
            Configuration object containing track parameters
        """
        self.logger = logging.getLogger(__name__)
        self.config = config
        
        # Track geometry data
        self.x_inner = None
        self.y_inner = None
        self.nx = None
        self.ny = None
        self.segment_indices = None
        self.start_idx = None
        self.finish_idx = None
        self.black_line_length = None
        self.x_black = None
        self.y_black = None
        self.start_pos = None
        self.start_normal = None
        
        # Segment data
        self.segments = []
        
        if config:
            self.update_geometry()
    
    def update_geometry(self) -> Tuple:
        """
        Update the track geometry based on current configuration.
        Uses the identical mathematics from create_velodrome_track.
        
        Returns:
        --------
        tuple
            Track parameters tuple for compatibility with original code
        """
        if not self.config:
            self.logger.error("Cannot update geometry: no configuration provided")
            return None
        
        # Extract parameters directly from config
        L_BLACK = self.config["L_BLACK"]
        a_BLACK = self.config["a_BLACK"]
        b_BLACK = self.config["b_BLACK"]
        W = self.config["W"]
        BLACK_LINE_POSITION = self.config["BLACK_LINE_POSITION"]
        SPRINT_DISTANCE = self.config["SPRINT_DISTANCE"]
        
        # Calculate black line length with parameters
        h_black = ((a_BLACK-b_BLACK)/(a_BLACK+b_BLACK))**2
        ellipse_perimeter_black = np.pi * (a_BLACK + b_BLACK) * (1 + 3*h_black/(10 + np.sqrt(4 - 3*h_black)))
        black_line_length = 2 * L_BLACK + ellipse_perimeter_black

        self.logger.info(f"Black measurement line length: {black_line_length:.2f} m")
        
        # Adjust if needed to make exactly 250
        scale_factor = 250.0 / black_line_length
        
        if abs(scale_factor - 1.0) > 0.001:
            self.logger.info(f"Adjusting track parameters by factor {scale_factor:.4f}")
            L_BLACK_adjusted = L_BLACK * scale_factor
            a_BLACK_adjusted = a_BLACK * scale_factor
            b_BLACK_adjusted = b_BLACK * scale_factor
            self.logger.info(f"New parameters: L_BLACK={L_BLACK_adjusted:.2f}m, a_BLACK={a_BLACK_adjusted:.2f}m, b_BLACK={b_BLACK_adjusted:.2f}m")
        else:
            L_BLACK_adjusted = L_BLACK
            a_BLACK_adjusted = a_BLACK
            b_BLACK_adjusted = b_BLACK
            self.logger.info("No adjustment needed, black line already very close to 250m")
        
        # Calculate INNER EDGE parameters (BLACK_LINE_POSITION INWARD from black line)
        # For the inner edge, the ellipse gets smaller
        a_inner = a_BLACK_adjusted - BLACK_LINE_POSITION
        b_inner = b_BLACK_adjusted - BLACK_LINE_POSITION
        L_inner = L_BLACK_adjusted  # Straight length stays the same
        
        # Number of points in each segment
        n_straight = 200
        n_curve = 300
        
        # Create BLACK LINE coordinates
        # SEGMENT 1: Bottom straight
        s1_x_black = np.linspace(0, L_BLACK_adjusted, n_straight)
        s1_y_black = np.full(n_straight, -b_BLACK_adjusted)
        
        # SEGMENT 2: Right curve
        theta = np.linspace(-np.pi/2, np.pi/2, n_curve)
        s2_x_black = L_BLACK_adjusted + a_BLACK_adjusted * np.cos(theta)
        s2_y_black = b_BLACK_adjusted * np.sin(theta)
        
        # SEGMENT 3: Top straight
        s3_x_black = np.linspace(L_BLACK_adjusted, 0, n_straight)
        s3_y_black = np.full(n_straight, b_BLACK_adjusted)
        
        # SEGMENT 4: Left curve (centered at origin, symmetric with right curve centered at L_BLACK)
        # Note: Top straight ends at (0, b_BLACK), left curve starts there going counter-clockwise
        theta = np.linspace(np.pi/2, 3*np.pi/2, n_curve)
        s4_x_black = a_BLACK_adjusted * np.cos(theta)  # At theta=pi/2: x=0, at theta=pi: x=-a, at theta=3pi/2: x=0
        s4_y_black = b_BLACK_adjusted * np.sin(theta)  # At theta=pi/2: y=b, at theta=pi: y=0, at theta=3pi/2: y=-b
        
        # Combine segments for BLACK LINE
        x_black = np.concatenate([s1_x_black, s2_x_black, s3_x_black, s4_x_black])
        y_black = np.concatenate([s1_y_black, s2_y_black, s3_y_black, s4_y_black])

        # Center the track about x=0 for visual symmetry
        # The track center is at x = L_BLACK/2, so shift everything left by that amount
        track_center_x = L_BLACK_adjusted / 2
        x_black = x_black - track_center_x
        
        # Save segment indices for reference
        segment_indices = [0, n_straight, n_straight + n_curve, n_straight + n_curve + n_straight]
        
        # Calculate normal vectors for BLACK LINE (pointing outward from center of track)
        nx = np.zeros_like(x_black)
        ny = np.zeros_like(y_black)
        
        # SEGMENT 1: Bottom straight - normal is (0,-1)
        nx[:n_straight] = 0.0
        ny[:n_straight] = -1.0
        
        # SEGMENT 2: Right curve - normal points away from center (L/2, 0) after centering
        idx = slice(n_straight, n_straight + n_curve)
        # Calculate vector from center to point, then normalize
        # Right curve center was at (L_BLACK, 0), now shifted to (L_BLACK - L_BLACK/2, 0) = (L_BLACK/2, 0)
        right_curve_center_x = L_BLACK_adjusted - track_center_x
        center_to_point_x = s2_x_black - track_center_x - right_curve_center_x
        center_to_point_y = s2_y_black - 0
        norms = np.sqrt(center_to_point_x**2 + center_to_point_y**2)
        nx[idx] = center_to_point_x / norms
        ny[idx] = center_to_point_y / norms
        
        # SEGMENT 3: Top straight - normal is (0,1)
        idx = slice(n_straight + n_curve, n_straight + n_curve + n_straight)
        nx[idx] = 0.0
        ny[idx] = 1.0
        
        # SEGMENT 4: Left curve - normal points away from center (-L/2, 0) after centering
        idx = slice(n_straight + n_curve + n_straight, len(x_black))
        # Calculate vector from center to point, then normalize
        # Left curve center was at (0, 0), now shifted to (0 - L_BLACK/2, 0) = (-L_BLACK/2, 0)
        left_curve_center_x = 0 - track_center_x
        center_to_point_x = s4_x_black - track_center_x - left_curve_center_x
        center_to_point_y = s4_y_black - 0
        norms = np.sqrt(center_to_point_x**2 + center_to_point_y**2)
        nx[idx] = center_to_point_x / norms
        ny[idx] = center_to_point_y / norms
        
        # Calculate INNER EDGE coordinates by going INWARD from black line
        x_inner = x_black - nx * BLACK_LINE_POSITION
        y_inner = y_black - ny * BLACK_LINE_POSITION
        
        # Verify inner edge geometry
        self.logger.debug(f"Inner edge: a={a_inner:.2f}m, b={b_inner:.2f}m")
        
        # Recalculate black line length after adjustments
        h_black_adjusted = ((a_BLACK_adjusted-b_BLACK_adjusted)/(a_BLACK_adjusted+b_BLACK_adjusted))**2
        ellipse_perimeter_adjusted = np.pi * (a_BLACK_adjusted + b_BLACK_adjusted) * (1 + 3*h_black_adjusted/(10 + np.sqrt(4 - 3*h_black_adjusted)))
        
        # Each half-elliptical curve length along black line
        half_curve_length = ellipse_perimeter_adjusted / 2
        
        # Calculate positions based on exact measurements - PARAMETERIZED APPROACH
        self.logger.debug(f"Each half-curve length along black line: {half_curve_length:.2f}m")
        self.logger.debug(f"Total straights length: {2*L_BLACK_adjusted:.2f}m")
        self.logger.debug(f"Total black line length: {2*L_BLACK_adjusted + ellipse_perimeter_adjusted:.2f}m")
        
        # Calculate the distance from start to S2-S3 junction (end of right curve)
        # For a sprint, start position is on the x-axis of the right curve
        distance_to_curve_end = half_curve_length / 2  # Half of the right curve
        self.logger.debug(f"Distance from start to end of right curve: {distance_to_curve_end:.2f}m")
        
        # Distance from start to end of top straight
        distance_to_top_straight_end = distance_to_curve_end + L_BLACK_adjusted
        self.logger.debug(f"Distance from start to end of top straight: {distance_to_top_straight_end:.2f}m")
        
        # Distance from start to end of left curve
        distance_to_left_curve_end = distance_to_top_straight_end + half_curve_length
        self.logger.debug(f"Distance from start to end of left curve: {distance_to_left_curve_end:.2f}m")
        
        # Distance from start of bottom straight to finish line
        distance_along_bottom_straight = SPRINT_DISTANCE - distance_to_left_curve_end
        self.logger.debug(f"Distance along bottom straight to finish: {distance_along_bottom_straight:.2f}m")
        
        # Proportion along bottom straight for finish line
        finish_proportion = distance_along_bottom_straight / L_BLACK_adjusted
        self.logger.debug(f"Finish line position: {finish_proportion*100:.2f}% along bottom straight")
        
        # Find start position exactly on the x-axis of the right curve
        segment_2_start = n_straight
        segment_2_end = segment_2_start + n_curve
        
        # Find where y crosses zero on the right curve
        y_segment2 = y_black[segment_2_start:segment_2_end]
        idx_before_zero = np.where(y_segment2[:-1] * y_segment2[1:] <= 0)[0]
        
        if len(idx_before_zero) >= 1:
            idx_at_zero = segment_2_start + idx_before_zero[0]
            idx_after_zero = idx_at_zero + 1
            
            # Interpolate to get the exact position where y = 0
            y1, y2 = y_black[idx_at_zero], y_black[idx_after_zero]
            x1, x2 = x_black[idx_at_zero], x_black[idx_after_zero]
            nx1, nx2 = nx[idx_at_zero], nx[idx_after_zero]
            ny1, ny2 = ny[idx_at_zero], ny[idx_after_zero]
            
            # Interpolation parameter
            if y2 != y1:  # Avoid division by zero
                t = abs(0 - y1) / abs(y2 - y1)
            else:
                t = 0
            
            # Exact start position with y = 0
            exact_start_x = x1 * (1-t) + x2 * t
            exact_start_y = 0  # We know this is exactly 0
            
            # Exact normal vector (normalize after interpolation)
            exact_start_nx = nx1 * (1-t) + nx2 * t
            exact_start_ny = ny1 * (1-t) + ny2 * t
            norm = np.sqrt(exact_start_nx**2 + exact_start_ny**2)
            exact_start_nx /= norm
            exact_start_ny /= norm
            
            self.logger.debug(f"Exact start position: ({exact_start_x:.4f}, {exact_start_y:.4f})")
            start_pos = (exact_start_x, exact_start_y)
            start_normal = (exact_start_nx, exact_start_ny)
            start_idx = idx_at_zero  # For reference only
        else:
            # Fallback in case zero crossing not found
            self.logger.warning("Zero crossing not found on right curve, using approximation")
            crossing_idx_relative = np.argmin(np.abs(y_segment2))
            start_idx = crossing_idx_relative + segment_2_start
            start_pos = (x_black[start_idx], y_black[start_idx])
            start_normal = (nx[start_idx], ny[start_idx])
        
        # Set the finish line at the calculated proportion along bottom straight
        finish_idx = int(finish_proportion * n_straight)

        # Calculate 200m start position - exactly 200m before finish line on the track
        # The track has 1000 points for 250m, so 200m = 800 points
        # Going backwards from finish_idx by 800 points (wrapping around)
        total_points = len(x_black)
        points_per_200m = int((SPRINT_DISTANCE / 250.0) * total_points)  # 800 points for 200m
        start_200m_idx = (finish_idx - points_per_200m) % total_points

        # Override start_pos and start_normal with the 200m start position
        start_pos = (x_black[start_200m_idx], y_black[start_200m_idx])
        start_normal = (nx[start_200m_idx], ny[start_200m_idx])
        start_idx = start_200m_idx

        self.logger.debug(f"200m Start position: ({start_pos[0]:.4f}, {start_pos[1]:.4f})")
        self.logger.debug(f"Finish position: ({x_black[finish_idx]:.4f}, {y_black[finish_idx]:.4f})")
        self.logger.debug(f"Sprint distance: {SPRINT_DISTANCE:.2f}m")

        # Store all calculated values
        self.x_inner = x_inner
        self.y_inner = y_inner
        self.nx = nx
        self.ny = ny
        self.segment_indices = segment_indices
        self.start_idx = start_idx
        self.finish_idx = finish_idx
        self.black_line_length = 250.0  # By design
        self.x_black = x_black
        self.y_black = y_black
        self.start_pos = start_pos
        self.start_normal = start_normal
        
        # Create segments data
        self._create_track_segments()
        
        # Return the track parameters tuple for compatibility with original code
        track_params = (
            x_inner, y_inner, nx, ny, segment_indices, 
            start_idx, finish_idx, 250.0, x_black, y_black, 
            start_pos, start_normal
        )
        
        return track_params
    
    def _create_track_segments(self) -> None:
        """Create named track segments data with proper boundaries."""
        if not self.segment_indices:
            return
        
        segment_names = ['Bottom Straight', 'Right Curve', 'Top Straight', 'Left Curve']
        
        # Calculate segment lengths
        L_BLACK = self.config["L_BLACK"]
        a_BLACK = self.config["a_BLACK"]
        b_BLACK = self.config["b_BLACK"]
        
        # Calculate ellipse perimeter (half for each curve)
        h_black = ((a_BLACK-b_BLACK)/(a_BLACK+b_BLACK))**2
        ellipse_perimeter = np.pi * (a_BLACK + b_BLACK) * (1 + 3*h_black/(10 + np.sqrt(4 - 3*h_black)))
        half_curve_length = ellipse_perimeter / 2
        
        # Lengths of each segment
        segment_lengths = [L_BLACK, half_curve_length, L_BLACK, half_curve_length]
        
        # Calculate start/end distances from beginning of track
        distance = 0
        segment_boundaries = [0]
        
        for length in segment_lengths:
            distance += length
            segment_boundaries.append(distance)
        
        # Create segments
        self.segments = []
        for i, name in enumerate(segment_names):
            self.segments.append({
                'name': name,
                'start_idx': self.segment_indices[i],
                'end_idx': self.segment_indices[i+1] if i < len(self.segment_indices)-1 else len(self.x_black),
                'start_distance': segment_boundaries[i],
                'end_distance': segment_boundaries[i+1],
                'length': segment_lengths[i]
            })
    
    def get_track_data(self) -> pd.DataFrame:
        """
        Get all track data as a DataFrame.
        
        Returns:
        --------
        pd.DataFrame
            DataFrame with track geometry data
        """
        if not self.x_black is not None:
            return pd.DataFrame()
        
        # Create segment labels
        segments = []
        labels = []
        positions = []
        track_positions = []
        
        for i, segment in enumerate(self.segments):
            start_idx = segment['start_idx']
            end_idx = segment['end_idx']
            count = end_idx - start_idx
            
            segments.extend([segment['name']] * count)
            labels.extend(['start'] + [''] * (count-2) + ['end'] if count > 1 else [segment['name']])
            
            # Calculate position within segment (0-1)
            seg_positions = np.linspace(0, 1, count)
            positions.extend(seg_positions)
            
            # Calculate position on track (0-1, one lap)
            track_start = segment['start_distance'] / self.black_line_length
            track_end = segment['end_distance'] / self.black_line_length
            track_positions.extend(np.linspace(track_start, track_end, count))
        
        # Distance along track
        distances = np.linspace(0, self.black_line_length, len(self.x_black))
        
        # Create the DataFrame
        track_df = pd.DataFrame({
            'distance': distances,
            'x': self.x_black,
            'y': self.y_black,
            'nx': self.nx,
            'ny': self.ny,
            'segment': segments,
            'position': positions,
            'track_position': track_positions,
            'label': labels
        })
        
        # Calculate lap value (integer laps + fraction)
        track_df['lap'] = track_df['distance'] / self.black_line_length
        
        return track_df
    
    def calculate_position_from_distance(self, distance_m: float) -> Tuple[float, float, float, float, str]:
        """
        Calculate position on track from distance along the black line.

        Parameters:
        -----------
        distance_m : float
            Distance in meters along the black line

        Returns:
        --------
        tuple
            (x, y, nx, ny, segment_name)
        """
        # Normalize distance to a single lap
        lap_distance = distance_m % self.black_line_length

        # Direct interpolation using track arrays - more reliable than segment lookup
        # The track has 1000 points covering 250m (black_line_length)
        total_points = len(self.x_black)

        # Calculate fractional index
        idx_f = (lap_distance / self.black_line_length) * (total_points - 1)
        idx1 = int(np.floor(idx_f))
        idx2 = int(np.ceil(idx_f))

        # Clamp indices
        idx1 = min(max(idx1, 0), total_points - 1)
        idx2 = min(max(idx2, 0), total_points - 1)

        # Determine segment name based on index
        segment_name = ""
        for segment in self.segments:
            if segment['start_idx'] <= idx1 < segment['end_idx']:
                segment_name = segment['name']
                break

        # Interpolate position
        if idx1 == idx2:
            x = self.x_black[idx1]
            y = self.y_black[idx1]
            nx_val = self.nx[idx1]
            ny_val = self.ny[idx1]
        else:
            weight = idx_f - idx1
            x = self.x_black[idx1] * (1 - weight) + self.x_black[idx2] * weight
            y = self.y_black[idx1] * (1 - weight) + self.y_black[idx2] * weight
            nx_val = self.nx[idx1] * (1 - weight) + self.nx[idx2] * weight
            ny_val = self.ny[idx1] * (1 - weight) + self.ny[idx2] * weight

            # Normalize normal vector
            norm = np.sqrt(nx_val**2 + ny_val**2)
            if norm > 0:
                nx_val /= norm
                ny_val /= norm

        return (x, y, nx_val, ny_val, segment_name)

    def _calculate_position_from_distance_old(self, distance_m: float) -> Tuple[float, float, float, float, str]:
        """Old segment-based calculation - kept for reference."""
        # Normalize distance to a single lap
        lap_distance = distance_m % self.black_line_length

        # Find appropriate segment
        segment_idx = 0
        segment_name = ""
        for i, segment in enumerate(self.segments):
            if segment['start_distance'] <= lap_distance < segment['end_distance']:
                segment_idx = i
                segment_name = segment['name']
                break

        # Calculate position within segment
        segment = self.segments[segment_idx]
        segment_start_dist = segment['start_distance']
        segment_length = segment['length']
        
        # Relative position within segment (0-1)
        rel_pos = (lap_distance - segment_start_dist) / segment_length
        
        # Map to index in the arrays
        start_idx = segment['start_idx']
        end_idx = segment['end_idx']
        
        # Interpolate position
        max_idx = len(self.x_black) - 1  # Maximum valid index

        if start_idx == end_idx:  # Edge case: segment has only one point
            idx = min(start_idx, max_idx)
            x = self.x_black[idx]
            y = self.y_black[idx]
            nx_val = self.nx[idx]
            ny_val = self.ny[idx]
        else:
            # Linear interpolation
            # Clamp end_idx to valid range for interpolation
            effective_end_idx = min(end_idx, max_idx)
            idx_f = start_idx + rel_pos * (effective_end_idx - start_idx)
            idx1 = int(np.floor(idx_f))
            idx2 = int(np.ceil(idx_f))

            # Clamp indices to valid range
            idx1 = min(max(idx1, 0), max_idx)
            idx2 = min(max(idx2, 0), max_idx)

            if idx1 == idx2:  # Edge case
                x = self.x_black[idx1]
                y = self.y_black[idx1]
                nx_val = self.nx[idx1]
                ny_val = self.ny[idx1]
            else:
                # Interpolation weight
                weight = idx_f - idx1

                # Interpolate coordinates and normal vectors
                x = self.x_black[idx1] * (1 - weight) + self.x_black[idx2] * weight
                y = self.y_black[idx1] * (1 - weight) + self.y_black[idx2] * weight
                nx_val = self.nx[idx1] * (1 - weight) + self.nx[idx2] * weight
                ny_val = self.ny[idx1] * (1 - weight) + self.ny[idx2] * weight

                # Normalize normal vector
                norm = np.sqrt(nx_val**2 + ny_val**2)
                if norm > 0:
                    nx_val /= norm
                    ny_val /= norm

        return (x, y, nx_val, ny_val, segment_name)
    
    def calculate_distance_from_position(self, x: float, y: float) -> float:
        """
        Calculate approximate distance along track from a position.
        
        Parameters:
        -----------
        x : float
            X coordinate
        y : float
            Y coordinate
            
        Returns:
        --------
        float
            Approximate distance along black line
        """
        # Calculate distances to all points on black line
        distances = np.sqrt((self.x_black - x)**2 + (self.y_black - y)**2)
        
        # Find closest point
        idx = np.argmin(distances)
        
        # Calculate distance along track to that point
        segment_idx = 0
        for i, segment in enumerate(self.segments):
            if segment['start_idx'] <= idx < segment['end_idx']:
                segment_idx = i
                break
        
        # Calculate distance within segment
        segment = self.segments[segment_idx]
        segment_start_dist = segment['start_distance']
        segment_length = segment['length']
        
        # Relative position within segment (0-1)
        rel_pos = (idx - segment['start_idx']) / (segment['end_idx'] - segment['start_idx'])
        
        # Distance along track
        distance = segment_start_dist + rel_pos * segment_length
        
        return distance
    
    def get_segment_at_distance(self, distance_m: float) -> Optional[Dict]:
        """
        Get the segment information at a specific distance.
        
        Parameters:
        -----------
        distance_m : float
            Distance in meters along the black line
            
        Returns:
        --------
        dict or None
            Segment information
        """
        # Normalize distance to a single lap
        lap_distance = distance_m % self.black_line_length
        
        # Find appropriate segment
        for segment in self.segments:
            if segment['start_distance'] <= lap_distance < segment['end_distance']:
                return segment.copy()
        
        return None


    def debug_segments(self):
        """Debug method to print segment information."""
       # if not self.segments:
       #     print("DEBUG: No segments found!")
       #     return
        
       # print("DEBUG: Track segments:")
       # for i, segment in enumerate(self.segments):
       #     print(f"  {i}: {segment['name']} - {segment['start_distance']:.1f}m to {segment['end_distance']:.1f}m (length: {segment['length']:.1f}m)")
        
        # Test pursuit line calculation
        try:
            pursuit_lines = self.get_pursuit_lines()
            if pursuit_lines and pursuit_lines[0] and pursuit_lines[1]:
                top_data, bottom_data = pursuit_lines
               # print(f"DEBUG: Top Pursuit Line: {top_data[0]:.1f}m at ({top_data[1][0]:.1f}, {top_data[1][1]:.1f})")
               # print(f"DEBUG: Bottom Pursuit Line: {bottom_data[0]:.1f}m at ({bottom_data[1][0]:.1f}, {bottom_data[1][1]:.1f})")
            else:
                print("DEBUG: Failed to calculate pursuit lines")
        except Exception as e:
            print(f"DEBUG: Error calculating pursuit lines: {e}")

    def get_pursuit_lines(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """
        Get the exact positions of the Top and Bottom Pursuit Lines.
        These are positioned exactly at the middle of the top and bottom straights.

        Returns:
        --------
        tuple
            ((top_pursuit_distance, top_pursuit_position), (bottom_pursuit_distance, bottom_pursuit_position))
            where position is (x, y) coordinates
        """
        try:
            # Use physical track geometry directly
            # The track is 250m with straights of L_BLACK length
            L_BLACK = self.config["L_BLACK"]  # 43m

            # Bottom pursuit line is at middle of bottom straight
            # Bottom straight runs from 0 to L_BLACK (43m)
            bottom_pursuit_distance = L_BLACK / 2  # 21.5m

            # Top pursuit line is at middle of top straight
            # Track layout: Bottom(0-43) -> Right Curve(43-125) -> Top(125-168) -> Left Curve(168-250)
            # Actually, use segment indices to find exact middle of top straight
            # Top straight is segment 2: indices 500-700 (middle = 600)
            # Which corresponds to distance: (600/1000) * 250 = 150m

            # More precisely: Top straight starts after bottom + right curve
            # Right curve is approximately (250 - 2*L_BLACK) / 2 = (250-86)/2 = 82m
            # So top straight starts at 43 + 82 = 125m and ends at 125 + 43 = 168m
            # Middle of top straight = (125 + 168) / 2 = 146.5m

            # Use array indices directly for accuracy:
            # Bottom straight: indices 0-199 (middle = 100)
            # Top straight: indices 500-699 (middle = 600)
            total_points = len(self.x_black)

            # Middle of bottom straight
            bottom_mid_idx = 100  # Middle of indices 0-199
            bottom_pursuit_distance = (bottom_mid_idx / (total_points - 1)) * self.black_line_length

            # Middle of top straight
            top_mid_idx = 600  # Middle of indices 500-699
            top_pursuit_distance = (top_mid_idx / (total_points - 1)) * self.black_line_length

            # Get the exact positions using the new direct interpolation
            top_pursuit_pos = self.calculate_position_from_distance(top_pursuit_distance)
            bottom_pursuit_pos = self.calculate_position_from_distance(bottom_pursuit_distance)

            # Extract just x, y coordinates
            top_pursuit_xy = (top_pursuit_pos[0], top_pursuit_pos[1])
            bottom_pursuit_xy = (bottom_pursuit_pos[0], bottom_pursuit_pos[1])

            return (top_pursuit_distance, top_pursuit_xy), (bottom_pursuit_distance, bottom_pursuit_xy)

        except Exception as e:
            self.logger.error(f"Error calculating pursuit lines: {e}")
            return None, None 
    
   
    def get_bottom_pursuit_line_distance(self) -> float:
        """
        Get the exact distance of the Bottom Pursuit Line for lap counting.
        
        Returns:
        --------
        float
            Distance in meters along the track where the Bottom Pursuit Line is located
        """
        pursuit_lines = self.get_pursuit_lines()
        if pursuit_lines[1] is None:
            return 20.0  # Fallback to current approximate value
        
        return pursuit_lines[1][0]  # Return bottom pursuit distance

    def get_top_pursuit_line_distance(self) -> float:
        """
        Get the exact distance of the Top Pursuit Line.
        
        Returns:
        --------
        float
            Distance in meters along the track where the Top Pursuit Line is located
        """
        pursuit_lines = self.get_pursuit_lines()
        if pursuit_lines[0] is None:
            return 125.0  # Fallback approximate value
        
        return pursuit_lines[0][0]  # Return top pursuit distance