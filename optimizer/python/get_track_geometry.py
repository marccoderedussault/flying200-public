#!/usr/bin/env python3
"""
Python bridge script for track geometry.
Returns track coordinates for canvas rendering.
Supports multiple track configurations: Bromont, Milton, Konya.
"""
import sys
import json
import os
import numpy as np

# Add current directory to path for local trackrender module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trackrender.track_model import TrackModel


# Track configurations based on v2 track model definitions
# For circular turns: a_BLACK = b_BLACK = turn_radius
TRACK_CONFIGS = {
    "Bromont": {
        "name": "Bromont 250m",
        "description": "Bromont Velodrome, Quebec, Canada (Atlanta 1996 Olympic track). 59m straights, 21.0m turn radius, 42° banking.",
        "L_BLACK": 59.0,              # Straight length (longest of all tracks)
        "a_BLACK": 21.0,              # Turn radius (tightest turns)
        "b_BLACK": 21.0,              # Circular turns
        "W": 7.5,                     # Track width
        "BLACK_LINE_POSITION": 0.85,
        "RED_LINE_POSITION": 2.45,
        "BLUE_LINE_POSITION": 3.45,
        "COTE_AZUR_WIDTH": 0.85,
        "SPRINT_DISTANCE": 200.0,
        "banking_turn_deg": 42.0,
        "banking_straight_deg": 12.0,
    },
    "Milton": {
        "name": "Milton 250m (Mattamy)",
        "description": "Mattamy National Cycling Centre, Milton, Ontario, Canada. 41m straights, 26.7m turn radius, 42° banking.",
        "L_BLACK": 41.0,              # Shorter straights
        "a_BLACK": 26.7,              # Wider turns
        "b_BLACK": 26.7,              # Circular turns
        "W": 7.0,                     # Standard UCI width
        "BLACK_LINE_POSITION": 0.85,
        "RED_LINE_POSITION": 2.45,
        "BLUE_LINE_POSITION": 3.45,
        "COTE_AZUR_WIDTH": 0.85,
        "SPRINT_DISTANCE": 200.0,
        "banking_turn_deg": 42.0,
        "banking_straight_deg": 13.0,
    },
    "Konya": {
        "name": "Konya 250m",
        "description": "Konya Velodrome, Turkey (2021). 38m straights, 27.7m turn radius, 45.5° banking. Fastest track geometry.",
        "L_BLACK": 38.0,              # Shortest straights
        "a_BLACK": 27.7,              # Widest turns
        "b_BLACK": 27.7,              # Circular turns
        "W": 8.0,                     # Wider than UCI minimum
        "BLACK_LINE_POSITION": 0.85,
        "RED_LINE_POSITION": 2.45,
        "BLUE_LINE_POSITION": 3.45,
        "COTE_AZUR_WIDTH": 0.85,
        "SPRINT_DISTANCE": 200.0,
        "banking_turn_deg": 45.5,
        "banking_straight_deg": 12.69,
    },
    # Default config (original) - kept for backwards compatibility
    "Default": {
        "name": "Default 250m",
        "description": "Default track configuration.",
        "L_BLACK": 43.0,
        "a_BLACK": 25.0,
        "b_BLACK": 21.0,
        "W": 7.5,
        "BLACK_LINE_POSITION": 0.85,
        "RED_LINE_POSITION": 2.45,
        "BLUE_LINE_POSITION": 3.45,
        "COTE_AZUR_WIDTH": 0.85,
        "SPRINT_DISTANCE": 200.0,
        "banking_turn_deg": 42.0,
        "banking_straight_deg": 12.0,
    },
}


def get_available_tracks():
    """Return list of available track names with descriptions."""
    return {
        "tracks": [
            {
                "id": key,
                "name": config["name"],
                "description": config["description"],
            }
            for key, config in TRACK_CONFIGS.items()
            if key != "Default"  # Hide default from list
        ]
    }


def get_track_geometry(track_name="Bromont"):
    """Get track geometry data for canvas rendering."""
    try:
        # Get track configuration
        if track_name not in TRACK_CONFIGS:
            track_name = "Bromont"  # Default to Bromont

        config = TRACK_CONFIGS[track_name].copy()

        track_model = TrackModel(config)

        # Get pursuit line positions
        pursuit_lines = track_model.get_pursuit_lines()
        top_pursuit = None
        bottom_pursuit = None
        if pursuit_lines and pursuit_lines[0] and pursuit_lines[1]:
            top_pursuit = {
                "distance_m": pursuit_lines[0][0],
                "x": pursuit_lines[0][1][0],
                "y": pursuit_lines[0][1][1]
            }
            bottom_pursuit = {
                "distance_m": pursuit_lines[1][0],
                "x": pursuit_lines[1][1][0],
                "y": pursuit_lines[1][1][1]
            }

        # Extract geometry arrays (convert to lists for JSON)
        return {
            "success": True,
            "track_name": track_name,
            "track": {
                "name": config.get("name", track_name),
                "description": config.get("description", ""),
                "black_line": {
                    "x": track_model.x_black.tolist(),
                    "y": track_model.y_black.tolist(),
                },
                "inner_edge": {
                    "x": track_model.x_inner.tolist(),
                    "y": track_model.y_inner.tolist(),
                },
                "normals": {
                    "nx": track_model.nx.tolist(),
                    "ny": track_model.ny.tolist(),
                },
                "start": {
                    "x": track_model.start_pos[0],
                    "y": track_model.start_pos[1],
                    "nx": track_model.start_normal[0],
                    "ny": track_model.start_normal[1],
                },
                "finish": {
                    "x": track_model.x_black[track_model.finish_idx],
                    "y": track_model.y_black[track_model.finish_idx],
                    "idx": track_model.finish_idx,
                },
                "pursuit_lines": {
                    "top": top_pursuit,
                    "bottom": bottom_pursuit,
                },
                "config": config,
                "segments": [
                    {
                        "name": s["name"],
                        "start_distance": s["start_distance"],
                        "end_distance": s["end_distance"],
                        "length": s["length"],
                    }
                    for s in track_model.segments
                ],
            }
        }

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def main():
    input_data = json.load(sys.stdin)
    action = input_data.get("action", "get_geometry")

    if action == "get_geometry":
        track_name = input_data.get("track_name", "Bromont")
        result = get_track_geometry(track_name)
    elif action == "list_tracks":
        result = get_available_tracks()
    else:
        result = {"error": f"Unknown action: {action}"}

    print(json.dumps(result))


if __name__ == "__main__":
    main()
