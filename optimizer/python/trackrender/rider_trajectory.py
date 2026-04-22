# veloapp/track/rider_trajectory.py
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional
import logging

class RiderTrajectory:
    """
    Manages rider position and trajectory calculations.
    Preserves the exact same calculations for rider position and true racing line distance.
    """
    
    def __init__(self, track_model, config=None):
        """
        Initialize the rider trajectory manager.
        
        Parameters:
        -----------
        track_model : TrackModel
            The track model to use for calculations
        config : object, optional
            Configuration object with parameters
        """
        self.logger = logging.getLogger(__name__)
        self.track_model = track_model
        self.config = config
        
        # Trajectory data
        self.rider_data = None
    
    def set_track_model(self, track_model) -> None:
        """Set a new track model for calculations."""
        self.track_model = track_model
    
    def set_config(self, config) -> None:
        """Set a new configuration object."""
        self.config = config
    
    def create_flying_200m_data(self) -> pd.DataFrame:
        """
        Create sample data for a flying 200m effort including height on the track.
        Uses the identical logic from create_flying_200m_data_with_height.
        
        Returns:
        --------
        pd.DataFrame
            DataFrame with simulated rider data
        """
        if not self.config:
            self.logger.error("Cannot create data: configuration not set")
            return None
        
        # Extract parameters
        total_duration = self.config["TOTAL_DURATION"]
        sample_rate = self.config["SAMPLE_RATE"]
        initial_speed = self.config["INITIAL_SPEED"]
        max_speed = self.config["MAX_SPEED"]
        initial_height = self.config["INITIAL_HEIGHT"]
        max_height = self.config["MAX_HEIGHT"]
        buildup_duration = self.config["BUILDUP_DURATION"]
        acceleration_duration = self.config["ACCELERATION_DURATION"]
        dive_duration = self.config["DIVE_DURATION"]
        initial_cadence = self.config["INITIAL_CADENCE"]
        max_cadence = self.config["MAX_CADENCE"]
        max_power = self.config["MAX_POWER"]
        
        # Create time points
        time_points = np.arange(0, total_duration + sample_rate, sample_rate)
        # Ensure time points have float precision
        time_points = time_points.astype(float)
        n_samples = len(time_points)
        
        # Initialize data arrays
        speed_kph = np.zeros(n_samples)
        cadence_rpm = np.zeros(n_samples)
        power_watts = np.zeros(n_samples)
        distance_m = np.zeros(n_samples)
        
        # Height represents position on the track banking
        # 0 = bottom (blue line), 1 = top (rail)
        height_pct = np.zeros(n_samples)
        
        # Define the build-up and sprint phases
        # Phase 1: Initial positioning - Low on track (pursuit line)
        phase1_end = 5
        phase1_idx = time_points <= phase1_end
        speed_kph[phase1_idx] = initial_speed + np.random.normal(0, 0.5, sum(phase1_idx))
        cadence_rpm[phase1_idx] = initial_cadence + np.random.normal(0, 2, sum(phase1_idx))
        height_pct[phase1_idx] = initial_height + np.random.normal(0, 0.02, sum(phase1_idx))
        
        # Phase 2: Build-up phase - gradually increasing speed and height
        phase2_end = phase1_end + buildup_duration
        phase2_idx = (time_points > phase1_end) & (time_points <= phase2_end)
        t_phase2 = time_points[phase2_idx] - phase1_end
        
        # Gradually build speed
        speed_buildup = initial_speed + (max_speed - 10 - initial_speed) * (t_phase2 / buildup_duration)
        speed_kph[phase2_idx] = speed_buildup
        
        # Gradual height increase with some tactical variations
        base_height = initial_height + (max_height - initial_height) * (t_phase2 / buildup_duration)
        tactical_adj = 0.05 * np.sin(t_phase2 * 0.25)  # Small adjustments
        height_pct[phase2_idx] = base_height + tactical_adj
        
        # Cadence increases with speed
        cadence_factor = (speed_buildup - initial_speed) / (max_speed - initial_speed)
        cadence_rpm[phase2_idx] = initial_cadence + (max_cadence - 20 - initial_cadence) * cadence_factor
        
        # Phase 3: Acceleration at top of track - maintaining height but increasing speed
        phase3_end = phase2_end + acceleration_duration
        phase3_idx = (time_points > phase2_end) & (time_points <= phase3_end)
        t_phase3 = time_points[phase3_idx] - phase2_end
        
        # Final acceleration
        speed_kph[phase3_idx] = (max_speed - 10) + 10 * (t_phase3 / acceleration_duration)
        cadence_rpm[phase3_idx] = (max_cadence - 20) + 20 * (t_phase3 / acceleration_duration)
        
        # Maintain height then begin to descend
        height_adj = max_height - 0.2 * (t_phase3 / acceleration_duration)**2  # Start descent 
        height_pct[phase3_idx] = height_adj + 0.03 * np.sin(t_phase3)  # Small variations
        
        # Phase 4: Diving down for the 200m sprint
        phase4_idx = time_points > phase3_end
        t_phase4 = time_points[phase4_idx] - phase3_end
        
        # Dive from high to low while maintaining/increasing speed
        height_pct[phase4_idx] = (max_height - 0.2) * np.exp(-0.5 * t_phase4) + 0.1  # Exponential dive to ~10%
        
        # Sprint speed
        speed_kph[phase4_idx] = max_speed * (1 - 0.05 * np.exp(-0.3 * t_phase4))
        cadence_rpm[phase4_idx] = max_cadence * (1 - 0.1 * np.exp(-0.3 * t_phase4))
        
        # Add some noise to make it realistic
        speed_kph += np.random.normal(0, 0.3, n_samples)
        cadence_rpm += np.random.normal(0, 1.0, n_samples)
        height_pct = np.clip(height_pct + np.random.normal(0, 0.02, n_samples), 0, 1)
        
        # Calculate power based on speed and a simple model (P = k * v³)
        # Determine k based on max power at max speed
        k = max_power / (max_speed**3)
        power_watts = k * (speed_kph**3)
        power_watts = np.minimum(power_watts, max_power)  # Cap at max power
        power_watts += np.random.normal(0, 30, n_samples)  # Add noise
        
        for i in range(1, n_samples):
            # Convert km/h to m/s and multiply by time step with full precision
            time_step = float(time_points[i]) - float(time_points[i-1])
            # Use higher precision calculation
            distance_m[i] = distance_m[i-1] + (speed_kph[i-1] / 3.6) * time_step
        
        # Create a DataFrame
        data = pd.DataFrame({
            'time_s': time_points,
            'speed_kph': speed_kph,
            'cadence_rpm': cadence_rpm,
            'power_watts': power_watts,
            'height_pct': height_pct,
            'distance_m': distance_m
        })
        
        # Calculate true distance along racing line
        true_distances = self.calculate_true_racing_line_distance(data)
        data['true_distance_m'] = true_distances
        
        # Calculate position on track based on true distance and height
        self.calculate_positions(data)
        
        # Store the data
        self.rider_data = data
        
        return data
    
    def calculate_true_racing_line_distance(self, rider_data: pd.DataFrame) -> np.ndarray:
        """
        Calculate the true distance along the racing line, accounting for height changes and banking angle.
        Uses identical logic from calculate_true_racing_line_distance.
        
        Parameters:
        -----------
        rider_data : pd.DataFrame
            DataFrame containing rider data with time, speed, and height
            
        Returns:
        --------
        np.array
            Array of distances along the racing line
        """
        if not self.track_model or not self.config:
            self.logger.error("Cannot calculate distance: track model or configuration not set")
            return np.zeros(len(rider_data))
        
        # Get track data
        x_black = self.track_model.x_black
        y_black = self.track_model.y_black
        nx = self.track_model.nx
        ny = self.track_model.ny
        segment_indices = self.track_model.segment_indices
        
        # Track width and banking angles
        track_width = self.config["W"]
        straight_banking = np.radians(self.config["STRAIGHT_BANKING"])
        curve_banking = np.radians(self.config["CURVE_BANKING"])
        
        # Simplified banking angle model
        banking_angles = np.zeros(len(x_black))
        
        # Straight sections (bottom and top)
        banking_angles[segment_indices[0]:segment_indices[1]] = straight_banking
        banking_angles[segment_indices[2]:segment_indices[3]] = straight_banking
        
        # Curve sections (right and left)
        banking_angles[segment_indices[1]:segment_indices[2]] = curve_banking
        banking_angles[segment_indices[3]:] = curve_banking
        
        # Calculate distance along racing line
        true_distances = np.zeros(len(rider_data))
        
        for i in range(1, len(rider_data)):
            # Get time step
            time_step = rider_data['time_s'].iloc[i] - rider_data['time_s'].iloc[i-1]
            
            # Convert speed to m/s
            speed_ms = rider_data['speed_kph'].iloc[i-1] / 3.6
            
            # Get heights for current and previous positions
            h1 = rider_data['height_pct'].iloc[i-1]
            h2 = rider_data['height_pct'].iloc[i]
            
            # Calculate angular position around track
            ang_pos1 = (true_distances[i-1] % 250.0) / 250.0
            idx1 = int(ang_pos1 * len(x_black))
            
            # Get banking angle at this position
            banking_angle = banking_angles[idx1]
            
            # Calculate effective distance considering height change
            # On a banked track, moving up the banking increases distance
            height_change = h2 - h1
            effective_distance = speed_ms * time_step
            
            # If moving up/down the banking, adjust distance based on banking angle
            if abs(height_change) > 0.001:
                # Convert height change to meters
                height_change_m = height_change * track_width
                
                # Adjustment based on banking angle and Pythagorean theorem
                adjustment = np.sqrt(effective_distance**2 + (height_change_m / np.cos(banking_angle))**2)
                effective_distance = adjustment
            
            true_distances[i] = true_distances[i-1] + effective_distance
        
        return true_distances
    
    def calculate_positions(self, rider_data: pd.DataFrame) -> None:
        """
        Calculate rider positions on the track based on distance and height.
        
        Parameters:
        -----------
        rider_data : pd.DataFrame
            DataFrame with rider data including true_distance_m and height_pct
        """
        if not self.track_model or not self.config:
            self.logger.error("Cannot calculate positions: track model or configuration not set")
            return
        
        # Track parameters
        track_width = self.config["W"]
        black_line_position = self.config["BLACK_LINE_POSITION"]
        
        # Initialize position arrays
        rider_x = []
        rider_y = []
        
        # For each time point, calculate the position on the track
        for i, (_, row) in enumerate(rider_data.iterrows()):
            # Angular position (0-1 representing position around track)
            angular_pos = (row['true_distance_m'] % 250.0) / 250.0
            
            # Get track position data at this angular position
            x, y, nx_val, ny_val, segment = self.track_model.calculate_position_from_distance(
                row['true_distance_m']
            )
            
            # Calculate position based on height
            height = row['height_pct']
            
            # The inner edge is at height=0, black line at height=BLACK_LINE_POSITION/track_width
            # and the outer edge at height=1
            relative_position = black_line_position/track_width + height * (1 - black_line_position/track_width)
            
            # Calculate position
            x_pos = x + nx_val * (relative_position * track_width - black_line_position)
            y_pos = y + ny_val * (relative_position * track_width - black_line_position)
            
            rider_x.append(x_pos)
            rider_y.append(y_pos)
        
        # Add position data to the DataFrame
        rider_data['x_position'] = rider_x
        rider_data['y_position'] = rider_y
        
    def calculate_speed_from_cadence(self, cadence_rpm, wheel_diameter=None, 
                                chainring=None, cog=None, tire_width=None):
        """
        Calculate speed from cadence using gear ratio and wheel size.
        
        Parameters:
        -----------
        cadence_rpm : float
            Cadence in revolutions per minute
        wheel_diameter : float, optional
            Wheel diameter in mm (e.g., 622 for 700c)
        chainring : int, optional
            Number of teeth on chainring
        cog : int, optional
            Number of teeth on cog
        tire_width : float, optional
            Tire width in mm
        
        Returns:
        --------
        float
            Speed in km/h
        """
        # Use passed parameters or get from config with defaults
        wheel_diameter = wheel_diameter if wheel_diameter is not None else self.config.get("WHEEL_DIAMETER", 622.0)
        chainring = chainring if chainring is not None else self.config.get("CHAINRING", 57)
        cog = cog if cog is not None else self.config.get("COG", 13)
        tire_width = tire_width if tire_width is not None else self.config.get("TIRE_WIDTH", 19.0)
        
        # Calculate total wheel diameter including tire
        total_diameter = wheel_diameter + (tire_width * 2)
        
        # Calculate gear ratio
        gear_ratio = chainring / cog
        
        # Calculate wheel circumference in meters
        wheel_circumference = total_diameter * 3.14159 / 1000
        
        # Calculate speed
        # Speed (km/h) = Cadence (RPM) × Circumference (m) × Gear Ratio × 60 / 1000
        # Simplified: × 0.06
        speed_kph = cadence_rpm * wheel_circumference * gear_ratio * 0.06
        
        return speed_kph


    def load_rider_data(self, filename: str) -> Optional[pd.DataFrame]:
        """
        Load rider data from a CSV file.
        
        Parameters:
        -----------
        filename : str
            Path to the CSV file
            
        Returns:
        --------
        pd.DataFrame or None
            Loaded rider data
        """
        try:
            data = pd.read_csv(filename)
            
            # Check if we need to calculate positions
            if 'true_distance_m' in data.columns and 'height_pct' in data.columns:
                if 'x_position' not in data.columns or 'y_position' not in data.columns:
                    self.calculate_positions(data)
            
            self.rider_data = data
            return data
        except Exception as e:
            self.logger.error(f"Error loading rider data: {e}")
            return None
    
    def save_rider_data(self, filename: str) -> bool:
        """
        Save rider data to a CSV file.
        
        Parameters:
        -----------
        filename : str
            Path to the CSV file
            
        Returns:
        --------
        bool
            Success status
        """
        if self.rider_data is None:
            self.logger.error("No rider data to save")
            return False
        
        try:
            self.rider_data.to_csv(filename, index=False)
            self.logger.info(f"Rider data saved to {filename}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving rider data: {e}")
            return False