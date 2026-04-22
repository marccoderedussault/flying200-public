"""
Flying 200 V2 - Main Entry Point

Run with:
  Desktop GUI:  python -m flying200_package_v2
  Web GUI:      python -m flying200_package_v2 --web
  Web (port):   python -m flying200_package_v2 --web --port 8080
"""

import sys
import os
import argparse

# Add package root to path for direct execution
_package_dir = os.path.dirname(os.path.abspath(__file__))
if _package_dir not in sys.path:
    sys.path.insert(0, _package_dir)

# Add gui directory to path
_gui_dir = os.path.join(_package_dir, 'gui')
if _gui_dir not in sys.path:
    sys.path.insert(0, _gui_dir)

# Add gui/web directory to path (for serializers import)
_web_dir = os.path.join(_gui_dir, 'web')
if _web_dir not in sys.path:
    sys.path.insert(0, _web_dir)


def main():
    parser = argparse.ArgumentParser(description='Flying 200 V2 - Track Cycling Simulation')
    parser.add_argument('--web', action='store_true', help='Launch web GUI instead of desktop')
    parser.add_argument('--port', type=int, default=5200, help='Web server port (default: 5200)')
    parser.add_argument('--no-browser', action='store_true', help='Do not auto-open browser')
    args = parser.parse_args()

    if args.web:
        from gui.web.server import run_server
        run_server(port=args.port, open_browser=not args.no_browser)
    else:
        from gui.main import main as desktop_main
        desktop_main()


if __name__ == "__main__":
    main()
