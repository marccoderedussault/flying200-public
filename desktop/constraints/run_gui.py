"""
Launch the Power-Cadence Constraints GUI.

Usage:
    python run_gui.py

Or from the package:
    python -m constraints.gui
"""

import sys
import os

# Ensure proper imports
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from constraints.gui import main

if __name__ == "__main__":
    main()
