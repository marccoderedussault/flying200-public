# CLAUDE.md — Orientation for AI agents

This file orients an AI coding agent (Claude Code, Copilot, etc.) helping a reviewer
explore the project. Read this first; it tells you what's here and where to look.

## What this is

A standalone Python desktop tool that simulates and optimizes a **Flying 200 m**
track-cycling time trial. Inputs a power file (FIT or CSV), detects the rider's
effort, calibrates an aero/physics model against the actual race, then proposes a
faster pacing/position strategy. Ships with a Tkinter GUI, a Flask web GUI, and a
pure-CLI mode.

This is a public portfolio extract from a larger working repo. It is intentionally
self-contained — no external services, no auth, no database.

## Quickstart

```bash
pip install -r requirements.txt
python -m pytest tests/                           # 39 passing unit tests, 1 skipped
python -m desktop --web                           # browser opens at http://localhost:5200
```

Run the end-to-end portfolio flow against the running server:
```bash
python tests/test_portfolio_flow.py               # uses /api/session/_snapshot to leave state untouched
```

## Layout

| Dir | Purpose | Worth opening |
|---|---|---|
| `core/` | Physics engine, simulation grid, session state, config | `physics.py`, `session.py` |
| `fit/` | FIT file parser, effort detector, time→distance converter | `detector.py`, `converter.py` |
| `optimizer/` | Two optimizers: energy-budget redistribution and power-redistribution | `power_redistribution.py` |
| `gui/web/` | Flask server + single-file HTML/JS frontend | `server.py`, `serializers.py` |
| `gui/` | Tkinter desktop GUI (older surface, still works) | `main.py` |
| `tests/` | Unit + physics + UI-static-audit + E2E flow | see below |
| `tracks/` | Track geometry definitions (JSON) | — |
| `constraints/` | Power/cadence constraint analysis (separate sub-tool) | — |

## Where the interesting design lives

When a reviewer asks *"show me something clever"* or *"where did you make a thoughtful trade-off"*,
point them at one of these:

- **Two-tier effort detection** — `fit/detector.py:53` `detect_flying_efforts` (strict; rejects
  standing-start sprints by ramp + speed validation) with `fit/detector.py:615` `find_power_peaks`
  as a permissive fallback. Real-world FIT files have noisy data; one detector per noise regime.
- **Snapshot/restore for test isolation** — `gui/web/server.py:117` `/api/session/_snapshot` and
  `_restore`. The desktop server is single-user / in-memory, so an E2E test would normally
  trample whatever the user had loaded. The test wraps its run in a deepcopy snapshot so the
  live session is byte-identical afterward. Five tests in `tests/test_session_snapshot.py`.
- **JSON-finiteness scrubbing** — `gui/web/serializers.py` `_finite_or_none()`. Flask's JSON
  writer (and stdlib `json` with `allow_nan=True`) emits bare `Infinity` / `NaN` tokens, which
  are not valid JSON. Browsers `JSON.parse` throws and the optimizer poll path swallowed it
  silently. The serializer now walks every payload and replaces non-finite floats with `null`.
  Locked down by `tests/test_json_finiteness.py`.
- **Effective power ceiling** — `optimizer/power_redistribution.py` `effective_ceiling_W`.
  The user-supplied power curve sometimes underestimates what the rider actually produced
  (the baseline trace from a real ride can exceed the curve at peak). The optimizer's
  per-segment ceiling is `max(curve(1s), 1.05 × baseline_peak)` so it can't reject the
  rider's own measured output as "impossible."
- **Zero-sum power adjustments** — same file, `generate_zero_sum_adjustments`. Power
  redistribution must preserve total energy. The discretization residual is folded back
  into a single random segment that can absorb it within the per-segment cap; if no
  segment can, the whole sample is rejected. Tested in `test_power_redistribution_fixes.py`.
- **UI static audit** — `tests/test_ui_static_audit.py` walks `index.html` and proves every
  `getElementById` reference has a matching DOM id and every id'd button is referenced
  somewhere. Catches dead handlers and dead markup at test time, not at user-click time.

## Gotchas

- **Server is single-user, in-memory, dev-only.** `flask --debug=False threaded=True`.
  Fine for one rider on one laptop. Not multi-tenant.
- **`flying200_config.json` is auto-created on first import** of `core.config` from
  `BUILTIN_DEFAULTS` (see `core/config.py:108`). If the file is corrupted JSON, `load_config`
  returns `None` and downstream code uses a safe constant-y_m=2.5m fallback so simulations
  never silently produce y_m=0 (which historically broke aero/banking calculations).
- **Track terminology**: `y_m` is the rider's lateral position from the inside black line.
  `y_m=0` is the black line, `y_m≈4` is the rail. "Riding the rail" = high `y_m`.
- **Test fixture FIT** (`tests/fixtures/flying200_sample.fit`) is real ride data with the
  identifying activity ID and event name stripped from the filename. The track is a 250 m
  oval with 12° straights and 42° bends; geometry constants are in `core/physics.py`.

## Running checks

| Command | What it covers |
|---|---|
| `pytest tests/test_physics_validation.py` | Forward-Euler simulator regression (vs golden values) |
| `pytest tests/test_power_redistribution_fixes.py` | Optimizer ceiling + zero-sum invariants |
| `pytest tests/test_json_finiteness.py` | Serializer Infinity/NaN scrubbing |
| `pytest tests/test_ui_static_audit.py` | HTML id ↔ JS reference consistency |
| `pytest tests/test_session_snapshot.py` | Server snapshot/restore round-trip |
| `python tests/test_portfolio_flow.py` | E2E (needs running server on :5200) |
