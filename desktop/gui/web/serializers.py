"""
Flying 200 V2 - JSON Serialization Helpers

Handles conversion of numpy arrays, dataclasses, and simulation results
into JSON-safe dictionaries for the web API.
"""

import json
import numpy as np
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Dict, Optional


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types, datetimes, and dataclasses."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)
        return super().default(obj)


def _finite_or_none(x: Any) -> Any:
    """
    Replace non-finite floats (inf/-inf/NaN) with None so Flask jsonify emits
    valid JSON. Python json writes Infinity/NaN as bare tokens (non-standard)
    which browsers reject in JSON.parse. Walks nested lists/dicts.
    """
    if isinstance(x, float):
        return x if np.isfinite(x) else None
    if isinstance(x, (np.floating,)):
        f = float(x)
        return f if np.isfinite(f) else None
    if isinstance(x, dict):
        return {k: _finite_or_none(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite_or_none(v) for v in x]
    return x


def downsample(arr: np.ndarray, target_points: int = 200) -> list:
    """Downsample a numpy array to ~target_points for chart rendering."""
    if len(arr) <= target_points:
        return arr.tolist()
    step = max(1, len(arr) // target_points)
    # Always include last point
    indices = list(range(0, len(arr), step))
    if indices[-1] != len(arr) - 1:
        indices.append(len(arr) - 1)
    return arr[indices].tolist()


def serialize_simulation_result(result) -> Dict:
    """
    Convert a SimulationResult into a JSON-safe dict.

    Splits into 'summary' (scalar metrics) and 'series' (downsampled arrays)
    so the frontend can render readout cards instantly without parsing arrays.
    """
    return _finite_or_none({
        "summary": {
            "T_200": result.T_200,
            "T_total": result.T_total,
            "v_200_entry_kph": result.v_200_entry_kph,
            "v_200_exit_kph": result.v_200_exit_kph,
            "splits_200": list(result.splits_200) if result.splits_200 else [],
            "T_sprint": result.T_sprint,
            "s_sprint_start": result.s_sprint_start,
            "P_avg_sprint": result.P_avg_sprint,
            "line_cost_200": result.line_cost_200,
            "line_cost_total": result.line_cost_total,
        },
        "series": {
            "s_m": downsample(result.s_grid),
            "v_kph": downsample(result.v * 3.6),
            "t_s": downsample(result.t),
            "P_W": downsample(result.P_eff),
            "CdA": downsample(result.CdA),
            "y_m": downsample(result.y),
            "theta_deg": downsample(np.degrees(result.theta)),
            "W_aero_J": downsample(result.W_aero),
            "W_rr_J": downsample(result.W_rr),
            "dE_pot_J": downsample(result.dE_pot),
            "dE_kin_J": downsample(result.dE_kin),
        },
    })


def serialize_fit_data(fit_data) -> Dict:
    """Serialize FitFileData summary (without full record arrays)."""
    return {
        "filename": fit_data.filename,
        "total_duration_s": fit_data.total_duration_s,
        "max_power_W": fit_data.max_power_W,
        "avg_power_W": fit_data.avg_power_W,
        "max_cadence_rpm": fit_data.max_cadence_rpm,
        "avg_cadence_rpm": fit_data.avg_cadence_rpm,
        "record_count": len(fit_data.records),
        "lap_count": len(fit_data.lap_markers),
    }


def serialize_effort(effort, index: int) -> Dict:
    """Serialize a DetectedEffort for the effort list."""
    return {
        "index": index,
        "start_index": effort.start_index,
        "end_index": effort.end_index,
        "duration_s": effort.duration_s,
        "sprint_duration_s": effort.sprint_duration_s,
        "ramp_duration_s": effort.ramp_duration_s,
        "max_power_W": effort.max_power_W,
        "avg_power_W": effort.avg_power_W,
        "sprint_avg_power_W": effort.sprint_avg_power_W,
        "confidence": effort.confidence,
        "effort_type": effort.effort_type,
        "is_high_confidence": effort.is_high_confidence,
    }


def serialize_effort_chart_data(fit_data, effort) -> Dict:
    """Serialize effort data for chart rendering (time-based)."""
    records = fit_data.records[effort.start_index:effort.end_index + 1]

    t0 = records[0].elapsed_s
    times = [r.elapsed_s - t0 for r in records]
    powers = [r.power_W for r in records]
    speeds = [r.speed_kph for r in records]
    cadences = [r.cadence_rpm for r in records]

    return {
        "times": times,
        "powers": powers,
        "speeds": speeds,
        "cadences": cadences,
        "sprint_start_offset": effort.sprint_start_s - effort.start_time_s,
    }


def serialize_distance_profile(profile) -> Dict:
    """Serialize a DistanceProfile for chart rendering and export."""
    return {
        "s_m": downsample(profile.s_m),
        "elapsed_s": downsample(profile.elapsed_s),
        "power_W": downsample(profile.power_W),
        "speed_kph": downsample(profile.speed_mps * 3.6),
        "cadence_rpm": downsample(profile.cadence_rpm),
        "total_distance_m": profile.total_distance_m,
        "total_time_s": profile.total_time_s,
    }


def serialize_track(track) -> Dict:
    """Serialize a TrackGeometry object."""
    result = {
        "name": track.name,
        "length_m": track.length_m,
        "straight_length_m": track.straight_length_m,
        "turn_radius_m": track.turn_radius_m,
        "banking_straight_deg": track.banking_straight_deg,
        "banking_turn_deg": track.banking_turn_deg,
        "width_m": track.width_m,
        "altitude_m": track.altitude_m,
        "arc_length_m": track.arc_length_m,
    }
    # Add segments if available
    if hasattr(track, 'segments') and track.segments:
        result["segments"] = [
            {
                "name": s.name,
                "display_name": s.display_name,
                "start_m": s.start_m,
                "end_m": s.end_m,
                "is_turn": s.is_turn,
            }
            for s in track.segments
        ]
    return result


def serialize_session_state(session) -> Dict:
    """Serialize full session state for the State tab."""
    state = {
        "header": session.header_text,
        "short_header": session.short_header,
        "status": session.status_text,
        "is_ready": session.is_ready,
        "simulation_stale": session.simulation_stale,
        "track": session.track.name,
        "created_at": session.created_at.isoformat(),
    }

    # Profile info
    if session.profile:
        p = session.profile
        state["profile"] = {
            "source": p.source,
            "loaded_at": p.loaded_at.isoformat(),
            "point_count": len(p.s_m),
            "s_range": [float(p.s_m.min()), float(p.s_m.max())],
            "power_range": [float(p.P_W.min()), float(p.P_W.max())],
            "cda_range": [float(p.CdA_m2.min()), float(p.CdA_m2.max())],
            "y_range": [float(p.y_m.min()), float(p.y_m.max())],
        }
    else:
        state["profile"] = None

    # Power curves info
    if session.power_curves:
        pc = session.power_curves
        state["power_curves"] = {
            "source": pc.source_description,
            "seated_count": len(pc.seated.durations_s),
            "standing_count": len(pc.standing.durations_s),
            "seated": pc.seated.to_dict(),
            "standing": pc.standing.to_dict(),
        }
    else:
        state["power_curves"] = None

    # Last simulation
    if session.last_simulation_result:
        state["last_simulation"] = {
            "T_200": session.last_simulation_result.get("T_200"),
            "T_total": session.last_simulation_result.get("T_total"),
        }
        state["last_simulation_params"] = session.last_simulation_params
    else:
        state["last_simulation"] = None
        state["last_simulation_params"] = None

    # Optimization
    if session.last_optimized_y_m is not None:
        state["optimization"] = {
            "improvement_ms": session.last_optimization_improvement_ms,
            "point_count": len(session.last_optimized_y_m),
        }
    else:
        state["optimization"] = None

    return state


def _series_from_sim_dict(sim: Dict) -> Dict:
    """Downsample a raw simulation dict (from sim_func) into chart-ready arrays."""
    if not sim or 's' not in sim:
        return {}
    import numpy as _np
    s = _np.asarray(sim.get('s', []))
    v = _np.asarray(sim.get('v', []))
    t = _np.asarray(sim.get('t', []))
    P = _np.asarray(sim.get('P_eff', sim.get('P', [])))
    CdA = _np.asarray(sim.get('CdA', []))
    y = _np.asarray(sim.get('y', []))
    W_aero = _np.asarray(sim.get('W_aero', []))
    W_rr = _np.asarray(sim.get('W_rr', []))
    dE_pot = _np.asarray(sim.get('dE_pot', []))
    dE_kin = _np.asarray(sim.get('dE_kin', []))
    return {
        "s_m": downsample(s),
        "v_kph": downsample(v * 3.6) if v.size else [],
        "t_s": downsample(t),
        "P_W": downsample(P),
        "CdA": downsample(CdA),
        "y_m": downsample(y),
        "W_aero_J": downsample(W_aero) if W_aero.size else [],
        "W_rr_J": downsample(W_rr) if W_rr.size else [],
        "dE_pot_J": downsample(dE_pot) if dE_pot.size else [],
        "dE_kin_J": downsample(dE_kin) if dE_kin.size else [],
    }


def serialize_optimization_result(result, baseline_sim: Optional[Dict] = None) -> Dict:
    """Serialize an OptimizationResult or RedistributionResult."""
    data = {
        "success": result.success,
        "best_time_s": result.best_time_s,
        "iterations": result.iterations,
        "valid_samples": result.valid_samples,
        "rejected_samples": result.rejected_samples,
        "segment_summary": result.segment_summary,
    }

    # Series for charts: baseline vs optimized run
    if baseline_sim:
        data["baseline_series"] = _series_from_sim_dict(baseline_sim)
    if hasattr(result, 'simulation_result') and result.simulation_result:
        data["optimized_series"] = _series_from_sim_dict(result.simulation_result)

    # OptimizationResult-specific fields
    if hasattr(result, 'energy_allocation_J'):
        data["energy_allocation_J"] = result.energy_allocation_J
        data["energy_fractions"] = result.energy_fractions
        data["positions"] = result.positions
        data["transition_m"] = result.transition_m

    # Baseline comparison (attached by server route for all result types)
    if hasattr(result, 'improvement_ms') and result.improvement_ms is not None:
        data["improvement_ms"] = result.improvement_ms
    if hasattr(result, 'baseline_time_s') and result.baseline_time_s is not None:
        data["baseline_time_s"] = result.baseline_time_s

    # RedistributionResult-specific fields
    if hasattr(result, 'adjustments_W'):
        data["adjustments_W"] = result.adjustments_W

    # Strip Infinity/NaN so the response is parseable JSON (see _finite_or_none)
    return _finite_or_none(data)
