"""
Entry point for running the constraints module as a script.

Usage:
    python -m constraints collect calendar.json --fit-dir ./fits
    python -m constraints analyze ./data
    python -m constraints interpolate ./data --chainring 55 --cog 14
"""

from .cli import main

if __name__ == '__main__':
    main()
