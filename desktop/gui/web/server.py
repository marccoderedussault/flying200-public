"""
Flying 200 V2 - Flask Web Server

Single-file API server that wraps all V2 core modules for the HTML frontend.
Manages a single Session object in memory (single-user desktop tool).

Launch: python -m flying200_package_v2 --web
"""

import os
import sys
import json
import uuid
import copy
import threading
import tempfile
import io
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────────────────────
_web_dir = Path(__file__).parent
_gui_dir = _web_dir.parent
_pkg_root = _gui_dir.parent

for p in [str(_pkg_root), str(_gui_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Flask ────────────────────────────────────────────────────────────────────
from flask import Flask, request, jsonify, send_from_directory, send_file

app = Flask(__name__, static_folder=None)

# ── Core imports ─────────────────────────────────────────────────────────────
import numpy as np
from core.session import Session, Profile, PowerCurve, PowerCurves
from core.physics import (
    simulate_profile, SimulationConfig, create_simulation_grid,
    theta_track_blackline, calculate_implied_cda,
    S_200_START, S_TOTAL, S_OFFSET,
)
from core.track import (
    AVAILABLE_TRACKS, DEFAULT_TRACK, get_segment_name,
    rho_from_altitude, rho_from_conditions, get_track_rho,
    get_track_summary, create_track_from_params, register_track,
)
from core.config import (
    get_all_defaults, get_environment_defaults, save_environment_defaults,
    get_aero_defaults, save_aero_defaults,
    get_simulation_defaults, save_simulation_defaults,
    get_default_track, save_default_track,
    get_default_power_curves, save_power_curves_to_config,
    reset_to_builtin_defaults, BUILTIN_DEFAULTS,
    get_default_y_profile, get_config_path,
)
from fit.parser import parse_fit_file, extract_power_curve
from fit.detector import detect_flying_efforts, create_manual_effort, find_power_peaks
from fit.converter import (
    extract_effort_profile, GearConfig,
    convert_time_to_distance, align_to_finish_line,
)

from serializers import (
    NumpyEncoder,
    serialize_simulation_result, serialize_fit_data,
    serialize_effort, serialize_effort_chart_data,
    serialize_distance_profile, serialize_track,
    serialize_session_state, serialize_optimization_result,
)

# ── Custom JSON encoder ─────────────────────────────────────────────────────
app.json_encoder = NumpyEncoder

# ── Server state ─────────────────────────────────────────────────────────────
session = Session()
fit_data_store = {}        # {file_id: FitFileData}
efforts_store = {}         # {file_id: [DetectedEffort, ...]}
distance_profiles = {}     # {file_id: DistanceProfile}
optimizer_jobs = {}        # {job_id: {status, progress, ...}}
_snapshots = {}            # {snapshot_id: deepcopy of all in-memory state}
_snapshots_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC FILE SERVING
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return send_from_directory(str(_web_dir), 'index.html')


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/session')
def get_session():
    """Get current session state summary."""
    return jsonify({
        "header": session.header_text,
        "status": session.status_text,
        "is_ready": session.is_ready,
        "has_profile": session.profile is not None,
        "has_power_curves": session.power_curves is not None,
        "track": session.track.name,
        "simulation_stale": session.simulation_stale,
    })


@app.route('/api/session/state')
def get_session_state():
    """Full session state dump for the State tab."""
    return jsonify(serialize_session_state(session))


@app.route('/api/session/_snapshot', methods=['POST'])
def session_snapshot():
    """Snapshot all in-memory state. Returns an opaque id for /api/session/_restore.

    Intended for tests that need to safely poke the running server without
    disturbing whatever the user has loaded. Not part of the user-facing API.
    """
    snap_id = uuid.uuid4().hex
    with _snapshots_lock:
        _snapshots[snap_id] = {
            "session": copy.deepcopy(session),
            "fit_data_store": copy.deepcopy(fit_data_store),
            "efforts_store": copy.deepcopy(efforts_store),
            "distance_profiles": copy.deepcopy(distance_profiles),
            "optimizer_jobs": copy.deepcopy(optimizer_jobs),
        }
    return jsonify({"snapshot_id": snap_id})


@app.route('/api/session/_restore', methods=['POST'])
def session_restore():
    """Restore a previously captured snapshot, replacing current in-memory state."""
    global session
    data = request.json or {}
    snap_id = data.get("snapshot_id")
    with _snapshots_lock:
        snap = _snapshots.pop(snap_id, None)
    if snap is None:
        return jsonify({"error": "Unknown snapshot_id"}), 404
    session = snap["session"]
    for store, restored in (
        (fit_data_store, snap["fit_data_store"]),
        (efforts_store, snap["efforts_store"]),
        (distance_profiles, snap["distance_profiles"]),
        (optimizer_jobs, snap["optimizer_jobs"]),
    ):
        store.clear()
        store.update(restored)
    return jsonify({"ok": True})


@app.route('/api/session/track', methods=['PUT'])
def set_track():
    """Set the active track."""
    data = request.json or {}
    track_key = data.get('track')
    if not track_key:
        return jsonify({"error": "Missing 'track' field"}), 400

    if track_key not in AVAILABLE_TRACKS:
        return jsonify({
            "error": f"Unknown track: {track_key}",
            "available": list(AVAILABLE_TRACKS.keys()),
        }), 400

    session.track = AVAILABLE_TRACKS[track_key]
    return jsonify({"track": session.track.name})


# ═══════════════════════════════════════════════════════════════════════════════
# TRACK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/tracks')
def list_tracks():
    """List all available tracks with geometry."""
    tracks = {}
    for key, track in AVAILABLE_TRACKS.items():
        tracks[key] = serialize_track(track)
    return jsonify(tracks)


@app.route('/api/track/geometry')
def get_track_geometry():
    """Get current track geometry."""
    return jsonify(serialize_track(session.track))


@app.route('/api/track/positions')
def get_track_positions():
    """Get y_m marker positions from config."""
    s_default, y_default = get_default_y_profile()
    if len(s_default) > 0:
        return jsonify({
            "s_m": s_default.tolist(),
            "y_m": y_default.tolist(),
        })
    return jsonify({"s_m": [], "y_m": []})


@app.route('/api/track/positions', methods=['PUT'])
def set_track_positions():
    """Update y_m marker positions."""
    data = request.json or {}
    s_m = data.get('s_m', [])
    y_m = data.get('y_m', [])
    if len(s_m) != len(y_m):
        return jsonify({"error": "s_m and y_m must have same length"}), 400

    # Update session profile if loaded
    if session.profile is not None:
        session.update_profile_y_m(np.array(s_m), np.array(y_m))

    return jsonify({"ok": True})


@app.after_request
def add_cors_headers(response):
    """Allow cross-origin requests (local-only single-user server)."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS'
    return response


@app.route('/api/tracks/create', methods=['POST', 'OPTIONS'])
def create_track():
    """Create a new track from track-builder parameters."""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.json or {}
    name = data.get('name')
    if not name:
        return jsonify({"error": "Missing 'name' field"}), 400

    required = ['LAP_LENGTH', 'L_BLACK', 'banking_turn_deg', 'banking_straight_deg']
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    # Derive key from name
    key = name.replace(' ', '_').replace('(', '').replace(')', '')

    track = create_track_from_params(
        name=name,
        lap_length=float(data['LAP_LENGTH']),
        straight_length_m=float(data['L_BLACK']),
        banking_turn_deg=float(data['banking_turn_deg']),
        banking_straight_deg=float(data['banking_straight_deg']),
        width_m=float(data.get('W', 7.0)),
        altitude_m=float(data.get('altitude_m', 0.0)),
    )

    register_track(key, track)

    return jsonify({
        "ok": True,
        "key": key,
        "track": serialize_track(track),
    })


@app.route('/api/tracks/save-config', methods=['POST', 'OPTIONS'])
def save_track_config():
    """Save a complete track config (geometry + trajectory) to a JSON file."""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.json or {}
    name = data.get('name')
    if not name:
        return jsonify({"error": "Missing 'name' field"}), 400

    # Build filename from name
    key = name.replace(' ', '_').replace('(', '').replace(')', '').replace("'", '')
    tracks_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'tracks')
    os.makedirs(tracks_dir, exist_ok=True)
    filepath = os.path.join(tracks_dir, f"{key}.json")

    import json as json_mod
    with open(filepath, 'w') as f:
        json_mod.dump(data, f, indent=2)

    return jsonify({"ok": True, "key": key, "path": filepath})


@app.route('/api/tracks/configs', methods=['GET'])
def list_track_configs():
    """List all saved track config files."""
    tracks_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'tracks')
    if not os.path.isdir(tracks_dir):
        return jsonify({})

    import json as json_mod
    configs = {}
    for fname in sorted(os.listdir(tracks_dir)):
        if fname.endswith('.json'):
            key = fname[:-5]
            try:
                with open(os.path.join(tracks_dir, fname)) as f:
                    configs[key] = json_mod.load(f)
            except Exception:
                pass
    return jsonify(configs)


@app.route('/api/track/rho', methods=['POST'])
def calculate_rho():
    """Calculate air density from conditions."""
    data = request.json or {}
    method = data.get('method', 'altitude')

    if method == 'altitude':
        altitude = data.get('altitude_m', session.track.altitude_m)
        temp = data.get('temperature_c', 15.0)
        rho = rho_from_altitude(altitude, temp)
    elif method == 'conditions':
        temp = data.get('temperature_c', 20.0)
        humidity = data.get('humidity_pct', 50.0)
        pressure = data.get('pressure_hpa', 1013.25)
        rho = rho_from_conditions(temp, humidity, pressure)
    else:
        return jsonify({"error": f"Unknown method: {method}"}), 400

    return jsonify({"rho": rho})


# ═══════════════════════════════════════════════════════════════════════════════
# FIT FILE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/fit/upload', methods=['POST'])
def upload_fit():
    """Upload and parse a FIT file."""
    if 'file' not in request.files:
        return jsonify({"error": "No file in request"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    # Save to temp file and parse
    with tempfile.NamedTemporaryFile(suffix='.fit', delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        fit_data = parse_fit_file(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    file_id = str(uuid.uuid4())[:8]
    fit_data_store[file_id] = fit_data

    result = serialize_fit_data(fit_data)
    result["file_id"] = file_id
    return jsonify(result)


@app.route('/api/fit/detect', methods=['POST'])
def detect_efforts():
    """Auto-detect Flying 200 efforts from an uploaded FIT file."""
    data = request.json or {}
    file_id = data.get('file_id')
    effort_type = data.get('effort_type', 200)

    if not file_id or file_id not in fit_data_store:
        return jsonify({"error": "Unknown file_id. Upload a FIT file first."}), 400

    fit_data = fit_data_store[file_id]
    detected = detect_flying_efforts(fit_data.records, effort_type=effort_type, verbose=False)
    efforts_store[file_id] = detected

    return jsonify({
        "file_id": file_id,
        "count": len(detected),
        "efforts": [serialize_effort(e, i) for i, e in enumerate(detected)],
    })


@app.route('/api/fit/manual-effort', methods=['POST'])
def manual_effort():
    """Create a manual effort from a specified final row."""
    data = request.json or {}
    file_id = data.get('file_id')
    final_row = data.get('final_row')
    effort_type = data.get('effort_type', 200)
    lookback_s = data.get('lookback_s', 90.0)

    if not file_id or file_id not in fit_data_store:
        return jsonify({"error": "Unknown file_id"}), 400
    if final_row is None:
        return jsonify({"error": "Missing final_row"}), 400

    fit_data = fit_data_store[file_id]
    effort = create_manual_effort(
        fit_data.records,
        final_row=int(final_row),
        effort_type=effort_type,
        lookback_s=lookback_s,
        verbose=False,
    )

    if effort is None:
        return jsonify({"error": "Could not create effort (window too short)"}), 400

    # Append to efforts store
    if file_id not in efforts_store:
        efforts_store[file_id] = []
    efforts_store[file_id].append(effort)
    idx = len(efforts_store[file_id]) - 1

    return jsonify(serialize_effort(effort, idx))


@app.route('/api/fit/peaks', methods=['POST'])
def find_peaks():
    """Find power peaks as fallback when auto-detect finds nothing."""
    data = request.json or {}
    file_id = data.get('file_id')
    min_power_W = data.get('min_power_W', 300)

    if not file_id or file_id not in fit_data_store:
        return jsonify({"error": "Unknown file_id. Upload a FIT file first."}), 400

    fit_data = fit_data_store[file_id]
    detected = find_power_peaks(fit_data.records, min_power_W=min_power_W, verbose=False)
    efforts_store[file_id] = detected

    return jsonify({
        "file_id": file_id,
        "count": len(detected),
        "method": "power_peaks",
        "efforts": [serialize_effort(e, i) for i, e in enumerate(detected)],
    })


@app.route('/api/fit/effort-chart', methods=['POST'])
def get_effort_chart_data():
    """Get chart data for a specific effort."""
    data = request.json or {}
    file_id = data.get('file_id')
    effort_index = data.get('effort_index', 0)

    if not file_id or file_id not in fit_data_store:
        return jsonify({"error": "Unknown file_id"}), 400
    if file_id not in efforts_store or effort_index >= len(efforts_store[file_id]):
        return jsonify({"error": "Effort not found"}), 400

    fit_data = fit_data_store[file_id]
    effort = efforts_store[file_id][effort_index]
    return jsonify(serialize_effort_chart_data(fit_data, effort))


@app.route('/api/fit/convert', methods=['POST'])
def convert_effort():
    """Convert a detected effort to a distance profile."""
    data = request.json or {}
    file_id = data.get('file_id')
    effort_index = data.get('effort_index', 0)
    chainring = data.get('chainring', 55)
    cog = data.get('cog', 14)
    wheel_circ_mm = data.get('wheel_circ_mm', 2096)

    if not file_id or file_id not in fit_data_store:
        return jsonify({"error": "Unknown file_id"}), 400
    if file_id not in efforts_store or effort_index >= len(efforts_store[file_id]):
        return jsonify({"error": "Effort not found"}), 400

    fit_data = fit_data_store[file_id]
    effort = efforts_store[file_id][effort_index]
    gear = GearConfig(chainring=chainring, cog=cog, wheel_circumference_mm=wheel_circ_mm)

    profile = extract_effort_profile(
        fit_data.records,
        effort.start_index,
        effort.end_index,
        gear,
        align_to_finish=True,
        finish_line_m=895.0,
        ds=0.25,
    )

    distance_profiles[file_id] = profile
    return jsonify(serialize_distance_profile(profile))


@app.route('/api/fit/export-session', methods=['POST'])
def export_fit_to_session():
    """Push the converted distance profile into the session."""
    data = request.json or {}
    file_id = data.get('file_id')

    if not file_id or file_id not in distance_profiles:
        return jsonify({"error": "No distance profile. Convert an effort first."}), 400

    dist_profile = distance_profiles[file_id]
    fit_data = fit_data_store.get(file_id)

    s_m = dist_profile.s_m

    # Get default y_m positions
    s_default, y_default = get_default_y_profile()
    if len(s_default) > 2:
        y_m = np.interp(s_m, s_default, y_default)
    else:
        y_m = np.zeros_like(s_m)

    # Get default CdA
    aero = get_aero_defaults()
    default_cda = aero.get("CdA_seated", 0.24)

    profile = Profile(
        s_m=s_m,
        y_m=y_m,
        CdA_m2=np.full_like(s_m, default_cda),
        P_W=dist_profile.power_W,
        source=f"FIT: {fit_data.filename}" if fit_data else "FIT Import",
    )

    session.set_profile(profile)

    return jsonify({
        "ok": True,
        "source": profile.source,
        "distance_m": float(dist_profile.total_distance_m),
        "duration_s": float(dist_profile.total_time_s),
        "points": len(s_m),
        "cda_default": default_cda,
        "header": session.header_text,
    })


@app.route('/api/fit/export-csv', methods=['POST'])
def export_fit_to_csv():
    """Download the distance profile as a CSV file."""
    data = request.json or {}
    file_id = data.get('file_id')

    if not file_id or file_id not in distance_profiles:
        return jsonify({"error": "No distance profile. Convert an effort first."}), 400

    dist_profile = distance_profiles[file_id]

    # Standard blackline positions
    blackline_positions = [float(i) for i in range(0, 691, 10)] + [695.0] + \
                          [float(i) for i in range(700, 891, 10)] + [895.0]
    s_m = np.array(blackline_positions)

    P_W = np.interp(s_m, dist_profile.s_m, dist_profile.power_W)

    # Fill missing early points
    s_min = dist_profile.s_m.min()
    if s_min > 0:
        first_valid = np.searchsorted(s_m, s_min)
        if 0 < first_valid < len(P_W):
            P_W[:first_valid] = P_W[first_valid]

    s_default, y_default = get_default_y_profile()
    y_m = np.interp(s_m, s_default, y_default) if len(s_default) > 2 else np.zeros_like(s_m)

    aero = get_aero_defaults()
    CdA = np.full_like(s_m, aero.get("CdA_seated", 0.24))

    # Build CSV in memory
    buf = io.StringIO()
    buf.write("s_m,y_m,CdA_m2,P_W\n")
    for i in range(len(s_m)):
        buf.write(f"{int(s_m[i])},{y_m[i]:.2f},{CdA[i]:.2f},{P_W[i]:.2f}\n")

    buf.seek(0)
    return send_file(
        io.BytesIO(buf.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='profile_f200.csv',
    )


@app.route('/api/fit/power-curve', methods=['POST'])
def extract_fit_power_curve():
    """Extract power curve from uploaded FIT data."""
    data = request.json or {}
    file_id = data.get('file_id')

    if not file_id or file_id not in fit_data_store:
        return jsonify({"error": "Unknown file_id"}), 400

    fit_data = fit_data_store[file_id]
    power_curve = extract_power_curve(fit_data.records)

    return jsonify({"power_curve": power_curve})


# ═══════════════════════════════════════════════════════════════════════════════
# PROFILE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/profile/load-csv', methods=['POST'])
def load_profile_csv():
    """Upload and load a profile CSV into the session."""
    if 'file' not in request.files:
        return jsonify({"error": "No file in request"}), 400

    file = request.files['file']
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False, mode='w') as tmp:
        content = file.read().decode('utf-8')
        tmp.write(content)
        tmp_path = tmp.name

    try:
        session.load_profile(tmp_path)
        # Override source name with original filename
        if file.filename:
            session.profile.source = file.filename
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    p = session.profile
    return jsonify({
        "ok": True,
        "source": p.source,
        "points": len(p.s_m),
        "s_range": [float(p.s_m.min()), float(p.s_m.max())],
        "power_range": [float(p.P_W.min()), float(p.P_W.max())],
        "header": session.header_text,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# POWER CURVE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/power-curves')
def get_power_curves():
    """Get current power curves (from session or config defaults)."""
    if session.power_curves:
        pc = session.power_curves
        return jsonify({
            "source": pc.source_description,
            "seated": pc.seated.to_dict(),
            "standing": pc.standing.to_dict(),
        })

    # Try config defaults
    config_pc = get_default_power_curves()
    if config_pc:
        return jsonify({
            "source": "config defaults",
            "seated": config_pc.get("seated", {}),
            "standing": config_pc.get("standing", {}),
        })

    # Builtin defaults
    return jsonify({
        "source": "builtin defaults",
        "seated": BUILTIN_DEFAULTS.get("power_curves", {}).get("seated", {}),
        "standing": BUILTIN_DEFAULTS.get("power_curves", {}).get("standing", {}),
    })


@app.route('/api/power-curves', methods=['PUT'])
def set_power_curves():
    """Set power curves from manual entry."""
    data = request.json or {}
    seated = data.get('seated', {})
    standing = data.get('standing', {})
    source = data.get('source', 'manual')

    if not seated and not standing:
        return jsonify({"error": "Provide at least one of 'seated' or 'standing'"}), 400

    # Convert string keys to int
    seated_int = {int(k): float(v) for k, v in seated.items() if v}
    standing_int = {int(k): float(v) for k, v in standing.items() if v}

    if seated_int or standing_int:
        session.set_power_curves(
            seated_int or standing_int,  # fallback to whichever has data
            standing_int or seated_int,
            source=source,
        )

    return jsonify({
        "ok": True,
        "header": session.header_text,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/profile/grid')
def get_profile_grid():
    """Get profile data at standard intervals for editing."""
    if session.profile is None:
        return jsonify({"error": "No profile loaded"}), 400

    positions = list(range(0, 691, 10)) + [695] + list(range(700, 896, 10))
    s_arr = np.array(positions, dtype=float)

    p = session.profile
    P_W = np.interp(s_arr, p.s_m, p.P_W)
    y_m = np.interp(s_arr, p.s_m, p.y_m)
    CdA = np.interp(s_arr, p.s_m, p.CdA_m2)

    rows = []
    for i in range(len(s_arr)):
        rows.append({
            "s_m": int(s_arr[i]),
            "P_W": round(float(P_W[i]), 1),
            "y_m": round(float(y_m[i]), 2),
            "CdA": round(float(CdA[i]), 3),
        })
    return jsonify({"rows": rows})


@app.route('/api/simulation/run-modified', methods=['POST'])
def run_modified_simulation():
    """Run simulation with user-modified profile grid."""
    data = request.json or {}
    rows = data.get('profile_rows')
    if not rows:
        return jsonify({"error": "No profile rows provided"}), 400

    s_arr = np.array([r['s_m'] for r in rows], dtype=float)
    P_arr = np.array([r['P_W'] for r in rows], dtype=float)
    y_arr = np.array([r['y_m'] for r in rows], dtype=float)
    CdA_arr = np.array([r['CdA'] for r in rows], dtype=float)

    env = get_environment_defaults()
    sim_defaults = get_simulation_defaults()

    config = SimulationConfig(
        mass_kg=data.get('mass_kg', env.get('rider_mass_kg', 92.0)),
        rho_kg_m3=data.get('rho_kg_m3', env.get('rho_kg_m3', 1.1627)),
        c_rr=data.get('c_rr', env.get('c_rr', 0.002)),
        v0_m_s=data.get('v0_m_s', sim_defaults.get('v0_m_s', 5.0)),
        ds_m=data.get('ds_m', sim_defaults.get('ds_m', 0.25)),
        drivetrain_efficiency=data.get('drivetrain_efficiency', env.get('drivetrain_eff', 0.98)),
        cda_bend_factor=data.get('cda_bend_factor', 1.0),
    )

    s_grid = create_simulation_grid(ds=config.ds_m)
    y_grid = np.interp(s_grid, s_arr, y_arr)
    CdA_grid = np.interp(s_grid, s_arr, CdA_arr)
    P_grid = np.interp(s_grid, s_arr, P_arr)

    result = simulate_profile(s_grid, y_grid, CdA_grid, P_grid, config, track_geometry=session.track)
    return jsonify(serialize_simulation_result(result))


@app.route('/api/simulation/run', methods=['POST'])
def run_simulation():
    """Run a simulation with the current session profile."""
    if session.profile is None:
        return jsonify({"error": "No profile loaded. Load via FIT Analysis or CSV."}), 400

    data = request.json or {}

    # Build config from request params (with session defaults as fallback)
    env = get_environment_defaults()
    sim_defaults = get_simulation_defaults()

    config = SimulationConfig(
        mass_kg=data.get('mass_kg', env.get('rider_mass_kg', 92.0)),
        rho_kg_m3=data.get('rho_kg_m3', env.get('rho_kg_m3', 1.1627)),
        c_rr=data.get('c_rr', env.get('c_rr', 0.002)),
        v0_m_s=data.get('v0_m_s', sim_defaults.get('v0_m_s', 5.0)),
        ds_m=data.get('ds_m', sim_defaults.get('ds_m', 0.25)),
        drivetrain_efficiency=data.get('drivetrain_efficiency', env.get('drivetrain_eff', 0.98)),
        cda_bend_factor=data.get('cda_bend_factor', 1.0),
    )

    s_grid = create_simulation_grid(ds=config.ds_m)
    y_grid, CdA_grid, P_grid = session.profile.interpolate_to_grid(s_grid)

    result = simulate_profile(s_grid, y_grid, CdA_grid, P_grid, config, track_geometry=session.track)

    # Store in session for optimizer baseline
    sim_params = {
        'M': config.mass_kg,
        'rho': config.rho_kg_m3,
        'C_RR': config.c_rr,
        'V0': config.v0_m_s,
        'DS': config.ds_m,
        'drivetrain_eff': config.drivetrain_efficiency,
        'cda_bend_factor': config.cda_bend_factor,
        'track_name': session.track.name,
    }

    # Build dict form for optimizer compatibility
    result_dict = {
        's': result.s_grid,
        'v': result.v,
        't': result.t,
        'dt': result.dt,
        'y': result.y,
        'CdA': result.CdA,
        'P_eff': result.P_eff,
        'W_aero': result.W_aero,
        'W_rr': result.W_rr,
        'dE_pot': result.dE_pot,
        'dE_kin': result.dE_kin,
        'T_total': result.T_total,
        'T_200': result.T_200,
        'v_200_entry': result.v_200_entry,
        'v_200_exit': result.v_200_exit,
        'T_sprint': result.T_sprint,
        'P_avg_sprint': result.P_avg_sprint,
        'theta': result.theta,
    }
    session.set_simulation_result(result_dict, sim_params)

    return jsonify(serialize_simulation_result(result))


# ═══════════════════════════════════════════════════════════════════════════════
# CALIBRATION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/calibration/compute', methods=['POST'])
def compute_calibration():
    """Compute implied CdA from actual measured times."""
    data = request.json or {}
    granularity = data.get('granularity', '50m')
    actual_times = data.get('actual_times', {})

    if not session.last_simulation_result:
        return jsonify({"error": "Run a simulation first"}), 400

    sim = session.last_simulation_result
    params = session.last_simulation_params or {}

    # Generate segment definitions
    segments = _generate_segments(granularity)

    results = []
    s_grid = sim['s']
    v_grid = sim['v']
    t_grid = sim['t']

    for seg in segments:
        s_start = seg['s_start']
        s_end = seg['s_end']

        # Find indices for this segment
        mask = (s_grid >= s_start) & (s_grid <= s_end)
        if not np.any(mask):
            continue

        indices = np.where(mask)[0]
        i_start = indices[0]
        i_end = indices[-1]

        # Model time for this segment
        model_time = t_grid[i_end] - t_grid[i_start]
        model_v_start = v_grid[i_start]
        model_v_end = v_grid[i_end]
        model_v_avg = np.mean(v_grid[indices])

        seg_result = {
            "name": seg['name'],
            "s_start": s_start,
            "s_end": s_end,
            "model_time_s": float(model_time),
            "model_v_avg_kph": float(model_v_avg * 3.6),
        }

        # If actual time provided, compute delta and implied CdA
        actual = actual_times.get(seg['name'])
        if actual is not None:
            actual_time = float(actual)
            delta = actual_time - model_time
            seg_result["actual_time_s"] = actual_time
            seg_result["delta_s"] = float(delta)
            seg_result["actual_v_avg_kph"] = float((s_end - s_start) / actual_time * 3.6)

            # Implied CdA
            power_avg = float(np.mean(sim['P_eff'][indices]))
            theta_avg = float(np.mean(sim['theta'][indices]))

            # Height change in segment
            y_seg = sim['y'][indices]
            dh = 0.0  # Simplified - flat track assumption for now

            implied = calculate_implied_cda(
                segment_distance=s_end - s_start,
                real_time=actual_time,
                power_avg=power_avg,
                mass=params.get('M', 92.0),
                rho=params.get('rho', 1.1627),
                c_rr=params.get('C_RR', 0.002),
                drivetrain_eff=params.get('drivetrain_eff', 0.98),
                theta_avg=theta_avg,
                dh=dh,
                v_start=float(v_grid[i_start]),
                v_end=float((s_end - s_start) / actual_time),  # avg speed as proxy
            )
            seg_result["implied_cda"] = float(implied) if implied is not None else None

        results.append(seg_result)

    # Total delta
    total_model = sum(r["model_time_s"] for r in results)
    total_actual = sum(r.get("actual_time_s", 0) for r in results if "actual_time_s" in r)
    total_delta = total_actual - total_model if total_actual > 0 else None

    return jsonify({
        "segments": results,
        "total_model_s": total_model,
        "total_actual_s": total_actual if total_actual > 0 else None,
        "total_delta_s": total_delta,
    })


def _generate_segments(granularity: str):
    """Generate segment definitions for calibration."""
    segments = []
    if granularity == "10m":
        for i in range(20):
            start = S_200_START + i * 10
            segments.append({"name": f"{i*10}-{(i+1)*10}m", "s_start": start, "s_end": start + 10})
    elif granularity == "50m":
        for i in range(4):
            start = S_200_START + i * 50
            segments.append({"name": f"{i*50}-{(i+1)*50}m", "s_start": start, "s_end": start + 50})
    elif granularity == "100m":
        for i in range(2):
            start = S_200_START + i * 100
            segments.append({"name": f"{i*100}-{(i+1)*100}m", "s_start": start, "s_end": start + 100})
    else:  # 200m
        segments.append({"name": "0-200m", "s_start": S_200_START, "s_end": S_200_START + 200})
    return segments


# ═══════════════════════════════════════════════════════════════════════════════
# OPTIMIZER ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/optimizer/start', methods=['POST'])
def start_optimizer():
    """Start optimization in a background thread."""
    if session.profile is None:
        return jsonify({"error": "No profile loaded"}), 400

    data = request.json or {}
    mode = data.get('mode', 'energy_budget')
    n_samples = data.get('n_samples', 500)

    job_id = str(uuid.uuid4())[:8]
    optimizer_jobs[job_id] = {
        "status": "running",
        "progress": 0,
        "total": n_samples,
        "best_time": None,
        "result": None,
        "error": None,
        "stop_flag": False,
    }

    thread = threading.Thread(
        target=_run_optimizer_thread,
        args=(job_id, data, mode, n_samples),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route('/api/optimizer/status/<job_id>')
def optimizer_status(job_id):
    """Poll optimization progress."""
    job = optimizer_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job_id"}), 404

    response = {
        "status": job["status"],
        "progress": job["progress"],
        "total": job["total"],
        "best_time": job["best_time"],
        "error": job["error"],
    }

    if job["status"] == "completed" and job["result"]:
        response["result"] = serialize_optimization_result(
            job["result"],
            baseline_sim=job.get("baseline_result"),
        )
        response["result"]["rho"] = job.get("rho", 1.1627)

    return jsonify(response)


@app.route('/api/optimizer/stop/<job_id>', methods=['POST'])
def stop_optimizer(job_id):
    """Stop a running optimization."""
    job = optimizer_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job_id"}), 404

    job["stop_flag"] = True
    return jsonify({"ok": True})


def _run_optimizer_thread(job_id, data, mode, n_samples):
    """Background thread for running optimization."""
    from optimizer.energy_budget import EnergyBudgetOptimizer
    from optimizer.power_redistribution import PowerRedistributionOptimizer

    job = optimizer_jobs[job_id]

    try:
        # Build simulation infrastructure
        env = get_environment_defaults()
        sim_defaults = get_simulation_defaults()
        aero = get_aero_defaults()

        sim_params = {
            'M': data.get('mass_kg', env.get('rider_mass_kg', 92.0)),
            'rho': data.get('rho_kg_m3', env.get('rho_kg_m3', 1.1627)),
            'C_RR': data.get('c_rr', env.get('c_rr', 0.002)),
            'V0': data.get('v0_m_s', sim_defaults.get('v0_m_s', 5.0)),
            'DS': data.get('ds_m', sim_defaults.get('ds_m', 0.25)),
            'drivetrain_eff': data.get('drivetrain_efficiency', env.get('drivetrain_eff', 0.98)),
            'S_TOTAL': 895.0,
            'cda_bend_factor': data.get('cda_bend_factor', 1.0),
        }

        ds = sim_params['DS']
        s_grid = np.arange(0.0, sim_params['S_TOTAL'] + ds, ds)

        # Interpolate profile to grid
        profile = session.profile
        y_grid = np.interp(s_grid, profile.s_m, profile.y_m)
        CdA_grid = np.interp(s_grid, profile.s_m, profile.CdA_m2)
        P_grid = np.interp(s_grid, profile.s_m, profile.P_W)

        # Theta grid
        theta_grid = np.array([theta_track_blackline(s + S_OFFSET) for s in s_grid])

        # CdA values
        cda_seated = data.get('cda_seated', aero.get('CdA_seated', 0.24))
        cda_standing = data.get('cda_standing', aero.get('CdA_standing', 0.38))
        CdA_seated_arr = np.full_like(s_grid, cda_seated)
        CdA_standing_arr = np.full_like(s_grid, cda_standing)

        # Power curves
        if session.power_curves:
            pc = session.power_curves
            power_curve_seated = pc.seated.to_dict()
            power_curve_standing = pc.standing.to_dict()
        else:
            config_pc = get_default_power_curves()
            if config_pc:
                power_curve_seated = {int(k): v for k, v in config_pc.get("seated", {}).items()}
                power_curve_standing = {int(k): v for k, v in config_pc.get("standing", {}).items()}
            else:
                power_curve_seated = BUILTIN_DEFAULTS["power_curves"]["seated"]
                power_curve_standing = BUILTIN_DEFAULTS["power_curves"]["standing"]

        # Create simulation wrapper (same pattern as optimizer_tab.py)
        config = SimulationConfig(
            mass_kg=sim_params['M'],
            rho_kg_m3=sim_params['rho'],
            c_rr=sim_params['C_RR'],
            v0_m_s=sim_params['V0'],
            ds_m=sim_params['DS'],
            drivetrain_efficiency=sim_params['drivetrain_eff'],
            cda_bend_factor=sim_params.get('cda_bend_factor', 1.0),
        )
        track_geometry = session.track

        def sim_func(y, CdA, P, params, s, theta, label=""):
            sim_config = SimulationConfig(
                mass_kg=params.get('M', config.mass_kg),
                rho_kg_m3=params.get('rho', config.rho_kg_m3),
                c_rr=params.get('C_RR', config.c_rr),
                v0_m_s=params.get('V0', config.v0_m_s),
                ds_m=params.get('DS', config.ds_m),
                drivetrain_efficiency=params.get('drivetrain_eff', config.drivetrain_efficiency),
            )
            result = simulate_profile(s, y, CdA, P, sim_config, track_geometry=track_geometry)
            return {
                's': result.s_grid, 'v': result.v, 't': result.t, 'dt': result.dt,
                'y': result.y, 'CdA': result.CdA, 'P_eff': result.P_eff,
                'W_aero': result.W_aero, 'W_rr': result.W_rr,
                'dE_pot': result.dE_pot, 'dE_kin': result.dE_kin,
                'T_total': result.T_total, 'T_200': result.T_200,
                'v_200_entry': result.v_200_entry, 'v_200_exit': result.v_200_exit,
                'T_sprint': result.T_sprint, 'P_avg_sprint': result.P_avg_sprint,
                'theta': result.theta,
            }

        # Run baseline
        baseline_result = None
        if session.last_simulation_result:
            baseline_result = session.last_simulation_result
        else:
            baseline_result = sim_func(y_grid, CdA_grid, P_grid, sim_params, s_grid, theta_grid, "baseline")

        def progress_cb(iteration, total, best_time):
            job["progress"] = iteration
            job["best_time"] = best_time

        def stop_check():
            return job["stop_flag"]

        if mode == "energy_budget":
            optimizer = EnergyBudgetOptimizer(
                simulate_func=sim_func,
                params=sim_params,
                s_grid=s_grid,
                theta_grid=theta_grid,
                y_grid=y_grid,
                CdA_standing=CdA_standing_arr,
                CdA_seated=CdA_seated_arr,
                P_baseline=P_grid,
                power_curve_seated=power_curve_seated,
                power_curve_standing=power_curve_standing,
                total_energy_budget_J=data.get('energy_budget_J', 25000),
                optimization_start_m=data.get('opt_start_m', 480.0),
                timed_zone_start_m=695.0,
                segment_length_m=data.get('segment_length_m', 50),
                min_power_fraction=data.get('min_power_fraction', 0.3),
                flatout_mode=data.get('flatout_mode', True),
            )

            energy_levels = data.get('energy_levels', 10)
            result = optimizer.optimize(
                n_samples=n_samples,
                energy_levels=energy_levels,
                progress_callback=progress_cb,
                stop_check=stop_check,
                baseline_result=baseline_result,
            )
        else:
            # Power redistribution
            def power_curve_func(elapsed_time_s):
                durations = sorted(power_curve_seated.keys())
                powers = [power_curve_seated[d] for d in durations]
                return float(np.interp(elapsed_time_s, durations, powers))

            optimizer = PowerRedistributionOptimizer(
                simulate_func=sim_func,
                params=sim_params,
                s_grid=s_grid,
                theta_grid=theta_grid,
                y_grid=y_grid,
                CdA_grid=CdA_grid,
                P_baseline=P_grid,
                optimization_start_m=data.get('opt_start_m', 430.0),
                finish_m=895.0,
                segment_mode=data.get('segment_mode', 'fixed'),
                segment_length_m=data.get('segment_length_m', 10),
                power_increment_W=data.get('power_increment_W', 10),
                max_adjustment_W=data.get('max_adjustment_W', 100),
                min_power_fraction=data.get('min_power_fraction', 0.5),
                power_curve_func=power_curve_func,
                track_geometry=track_geometry,
            )

            optimizer.baseline_result = baseline_result
            optimizer.baseline_time = baseline_result.get('T_200', float('inf'))

            result = optimizer.optimize_random(
                n_samples=n_samples,
                progress_callback=progress_cb,
                stop_check=stop_check,
            )

        # Attach baseline comparison to all result types so the UI can display it.
        baseline_T200 = baseline_result.get('T_200', 0)
        if result.success and baseline_T200:
            if not hasattr(result, 'improvement_ms') or result.improvement_ms is None:
                result.improvement_ms = (baseline_T200 - result.best_time_s) * 1000
            if not hasattr(result, 'baseline_time_s') or result.baseline_time_s is None:
                result.baseline_time_s = baseline_T200

        job["status"] = "completed"
        job["result"] = result
        job["baseline_result"] = baseline_result
        job["rho"] = sim_params.get('rho', 1.1627)

        # Store optimized line in session if successful
        if result.success and hasattr(result, 'simulation_result') and result.simulation_result:
            sim_r = result.simulation_result
            if 'y' in sim_r and 's' in sim_r:
                improvement = (baseline_T200 - result.best_time_s) * 1000
                session.set_optimized_line(
                    np.array(sim_r['s']),
                    np.array(sim_r['y']),
                    improvement,
                )

    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"] = f"{str(e)}\n{traceback.format_exc()}"


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/config')
def get_config():
    """Get all configuration values."""
    return jsonify({
        "environment": get_environment_defaults(),
        "aero": get_aero_defaults(),
        "simulation": get_simulation_defaults(),
        "default_track": get_default_track(),
        "power_curves": get_default_power_curves(),
        "config_path": str(get_config_path()),
        "builtin_defaults": BUILTIN_DEFAULTS,
    })


@app.route('/api/config/environment', methods=['PUT'])
def save_config_environment():
    """Save environment defaults."""
    data = request.json or {}
    save_environment_defaults(data)
    return jsonify({"ok": True})


@app.route('/api/config/aero', methods=['PUT'])
def save_config_aero():
    """Save aero defaults."""
    data = request.json or {}
    save_aero_defaults(data)
    return jsonify({"ok": True})


@app.route('/api/config/simulation', methods=['PUT'])
def save_config_simulation():
    """Save simulation defaults."""
    data = request.json or {}
    save_simulation_defaults(data)
    return jsonify({"ok": True})


@app.route('/api/config/track', methods=['PUT'])
def save_config_track():
    """Save default track."""
    data = request.json or {}
    track_name = data.get('track')
    if track_name:
        save_default_track(track_name)
    return jsonify({"ok": True})


@app.route('/api/config/reset', methods=['POST'])
def reset_config():
    """Reset all config to built-in defaults."""
    reset_to_builtin_defaults()
    return jsonify({"ok": True, "defaults": BUILTIN_DEFAULTS})


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

@app.errorhandler(Exception)
def handle_error(e):
    import traceback
    return jsonify({
        "error": str(e),
        "traceback": traceback.format_exc(),
    }), 500


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def run_server(port: int = 5200, open_browser: bool = True):
    """Start the Flask server."""
    if open_browser:
        import webbrowser
        import threading as _threading
        _threading.Timer(0.5, lambda: webbrowser.open(f'http://localhost:{port}')).start()

    print(f"\n  Flying 200 V2 — Web GUI")
    print(f"  http://localhost:{port}")
    print(f"  Press Ctrl+C to stop\n")

    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)


if __name__ == '__main__':
    run_server()
