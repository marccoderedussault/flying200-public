"""
Portfolio flow test for Flying 200 web GUI.

Exercises the full user flow end-to-end against the running Flask server
at http://localhost:8080 and reports anomalies / stale behavior. No
external deps — only stdlib.

Flow:
  A. Baseline session + state
  B. Upload FIT -> detect peaks -> pick effort -> convert to distance
  C. Export distance profile to session (profile loaded)
  D. Run Simulation 1 (defaults) + Simulation 2 (altered mass + rho)
  E. Run Optimizer: Energy Budget  (method 1)
  F. Run Optimizer: Power Redistribution (method 2)
  G. Mutate power curve (weaker peaks) -> re-run Energy Budget optimizer
     -> confirm result differs (constraints recognized)
  H. Poll /session/state between steps; dump final state

Each step prints PASS/FAIL with evidence. Any mismatched invariants are
flagged. Raw responses are saved under c:/tmp/portfolio_test/ for post-hoc
inspection.
"""
from __future__ import annotations
import json
import mimetypes
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib import request as ur
from urllib.error import HTTPError, URLError

BASE = os.environ.get("FLYING200_API", "http://localhost:5200/api")
OUT = Path(os.environ.get("FLYING200_TEST_OUT", Path(tempfile.gettempdir()) / "portfolio_test"))
OUT.mkdir(parents=True, exist_ok=True)

# Test fixture — committed alongside this test.
FIXTURE_FIT = (
    Path(__file__).parent / "fixtures" / "flying200_sample.fit"
)

# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers (stdlib only)
# ─────────────────────────────────────────────────────────────────────────────

def _req(method: str, path: str, body: Optional[dict] = None, *,
         raw: bool = False, timeout: int = 60) -> Any:
    url = BASE + path
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = ur.Request(url, data=data, headers=headers, method=method)
    try:
        with ur.urlopen(req, timeout=timeout) as r:
            payload = r.read()
    except HTTPError as e:
        payload = e.read()
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {payload[:400].decode(errors='replace')}")
    except URLError as e:
        raise RuntimeError(f"{method} {path} -> URL error: {e}")
    if raw:
        return payload
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload.decode(errors="replace")


def GET(path: str, **kw):
    return _req("GET", path, **kw)


def POST(path: str, body: Optional[dict] = None, **kw):
    return _req("POST", path, body, **kw)


def PUT(path: str, body: Optional[dict] = None, **kw):
    return _req("PUT", path, body, **kw)


def upload_fit(file_path: str) -> dict:
    """Multipart upload — implemented by hand so we don't need requests."""
    boundary = "----boundary" + uuid.uuid4().hex
    filename = os.path.basename(file_path)
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        data = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = ur.Request(
        BASE + "/fit/upload",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with ur.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

issues: list[str] = []
passed: list[str] = []


def step(num: str, title: str):
    bar = "=" * 72
    print(f"\n{bar}\n  [{num}] {title}\n{bar}")


def ok(msg: str):
    passed.append(msg)
    print(f"  PASS  {msg}")


def fail(msg: str):
    issues.append(msg)
    print(f"  FAIL  {msg}")


def warn(msg: str):
    issues.append("WARN: " + msg)
    print(f"  WARN  {msg}")


def dump(name: str, data: Any):
    path = OUT / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"        -> saved {path}")


# ─────────────────────────────────────────────────────────────────────────────
# Flow steps
# ─────────────────────────────────────────────────────────────────────────────

def pick_fit() -> str:
    if FIXTURE_FIT.exists():
        return str(FIXTURE_FIT)
    fail(f"Fixture not found: {FIXTURE_FIT}")
    sys.exit(1)


def poll_optimizer(job_id: str, label: str, timeout: int = 180) -> dict:
    start = time.time()
    last_prog = -1
    while True:
        s = GET(f"/optimizer/status/{job_id}")
        prog = s.get("progress", 0)
        total = s.get("total", 0)
        if prog != last_prog and prog != 0:
            print(f"        [{label}] {prog}/{total}  best={s.get('best_time')}")
            last_prog = prog
        if s.get("status") == "completed":
            ok(f"[{label}] optimizer completed in {time.time()-start:.1f}s")
            return s
        if s.get("status") == "error" or s.get("error"):
            fail(f"[{label}] optimizer error: {s.get('error')}")
            return s
        if time.time() - start > timeout:
            fail(f"[{label}] optimizer timed out after {timeout}s")
            return s
        time.sleep(1.5)


def assert_keys(d: dict, keys: list[str], label: str):
    missing = [k for k in keys if d.get(k) in (None, "", [], {})]
    if missing:
        warn(f"{label}: missing/empty keys {missing}")
    else:
        ok(f"{label}: has {keys}")


def run():
    print("Flying 200 — Portfolio Flow Test")
    print(f"Server: {BASE}")
    print(f"Output: {OUT}")

    # ── A. baseline ─────────────────────────────────────────────────────────
    step("A", "Baseline session + state")
    sess0 = GET("/session")
    state0 = GET("/session/state")
    dump("A_state_baseline", state0)
    ok(f"server reachable, track={state0.get('track')}")

    # ── B. Upload FIT + detect + convert ────────────────────────────────────
    step("B", "Upload FIT -> find peaks -> convert to distance")
    fit_path = pick_fit()
    print(f"  Using FIT: {fit_path}")
    up = upload_fit(fit_path)
    dump("B_upload", up)
    file_id = up.get("file_id")
    if not file_id:
        fail(f"upload returned no file_id: {up}")
        return
    ok(f"upload file_id={file_id}, records={up.get('record_count')}")

    peaks = POST("/fit/peaks", {"file_id": file_id})
    dump("B_peaks", peaks)
    efforts = peaks.get("efforts") or []
    if not efforts:
        fail("peak finder returned 0 efforts")
        return
    ok(f"peak finder: {len(efforts)} efforts")

    # Pick best effort (first = highest power usually)
    conv = POST("/fit/convert", {
        "file_id": file_id,
        "effort_index": 0,
        "chainring": 55,
        "cog": 14,
    })
    max_P = max(conv.get("power_W") or [0]) if conv.get("power_W") else None
    dump("B_convert", {
        "total_distance_m": conv.get("total_distance_m"),
        "total_time_s": conv.get("total_time_s"),
        "power_samples": len(conv.get("power_W") or []),
        "max_P_local": max_P,
    })
    if not conv.get("s_m"):
        fail("convert returned no s_m array")
        return
    # (max_power_W field is not required: UI reads its "max power" readout
    # from /fit/upload, not /fit/convert.)
    ok(f"converted: {conv.get('total_distance_m'):.1f}m in {conv.get('total_time_s'):.2f}s, "
       f"max_P(local)={max_P:.0f}W" if max_P else "converted (no power)")

    # ── C. Export to session ────────────────────────────────────────────────
    step("C", "Export distance profile to session")
    exp = POST("/fit/export-session", {"file_id": file_id})
    dump("C_export", exp)
    if not exp.get("source"):
        fail(f"export-session: no source returned: {exp}")
    else:
        ok(f"profile loaded: {exp.get('source')} ({exp.get('points')} pts)")

    state1 = GET("/session/state")
    dump("C_state_after_export", state1)
    if not state1.get("profile"):
        fail("state.profile still null after export-session")
    else:
        p = state1["profile"]
        ok(f"state.profile.source={p.get('source')}, pts={p.get('point_count')}, "
           f"s_range={p.get('s_range')}")

    # ── D. Simulation 1 + Simulation 2 ──────────────────────────────────────
    step("D", "Simulation 1 (defaults) + Simulation 2 (mass+rho altered)")
    sim1 = POST("/simulation/run", {})
    s1 = (sim1.get("summary") or {})
    dump("D_sim1", s1)
    T1 = s1.get("T_200")
    if T1 is None:
        fail(f"sim1: no summary.T_200 (keys={list(sim1.keys())})")
    else:
        ok(f"sim1: T_200={T1:.3f}s, T_sprint={s1.get('T_sprint'):.3f}s, P_avg_sprint={s1.get('P_avg_sprint'):.0f}W")

    sim2_params = {"mass_kg": 85.0, "rho_kg_m3": 1.20, "c_rr": 0.0025}
    sim2 = POST("/simulation/run", sim2_params)
    s2 = (sim2.get("summary") or {})
    dump("D_sim2", s2)
    T2 = s2.get("T_200")
    if T2 is None:
        fail("sim2: no summary.T_200")
    elif T1 is not None:
        delta = T2 - T1
        ok(f"sim2: T_200={T2:.3f}s (delta={delta:+.3f}s vs sim1)")
        if abs(delta) < 1e-4:
            fail("sim2 altered mass+rho+crr but T_200 identical - params ignored?")

    # ── E. Optimizer — Energy Budget ────────────────────────────────────────
    step("E", "Optimizer: Energy Budget (method 1)")
    opt_payload = {
        "mode": "energy_budget",
        "energy_budget_J": 45000,
        "n_samples": 50,
        "segment_length_m": 15,
    }
    job = POST("/optimizer/start", opt_payload)
    if not job.get("job_id"):
        fail(f"optimizer/start did not return job_id: {job}")
        return
    res_eb = poll_optimizer(job["job_id"], "EnergyBudget", timeout=240)
    dump("E_optimizer_eb", res_eb)
    eb_best = None
    if res_eb.get("status") == "completed":
        r = res_eb.get("result") or {}
        assert_keys(r, ["best_time_s", "baseline_time_s", "improvement_ms"], "EB result")
        eb_best = r.get("best_time_s")
        if eb_best is not None:
            ok(f"EB: best={eb_best:.3f}s, baseline={r.get('baseline_time_s'):.3f}s, "
               f"improvement={r.get('improvement_ms'):+.1f}ms")

    # ── F. Optimizer — Power Redistribution ─────────────────────────────────
    step("F", "Optimizer: Power Redistribution (method 2)")
    opt_payload2 = dict(opt_payload, mode="power_redistribution")
    job2 = POST("/optimizer/start", opt_payload2)
    if not job2.get("job_id"):
        fail(f"optimizer/start (PR) did not return job_id: {job2}")
    else:
        res_pr = poll_optimizer(job2["job_id"], "PowerRedist", timeout=240)
        dump("F_optimizer_pr", res_pr)
        if res_pr.get("status") == "completed":
            r = res_pr.get("result") or {}
            assert_keys(r, ["best_time_s", "baseline_time_s", "improvement_ms"], "PR result")
            pr_best = r.get("best_time_s")
            if pr_best is not None:
                ok(f"PR: best={pr_best:.3f}s, baseline={r.get('baseline_time_s'):.3f}s, "
                   f"improvement={r.get('improvement_ms'):+.1f}ms")

    # ── G. Mutate power curve, re-run EB, expect different result ───────────
    step("G", "Change power curve -> re-run optimizer -> confirm constraints recognized")
    pc_before = GET("/power-curves")
    dump("G_pc_before", pc_before)

    # Halve every peak value in seated + standing (aggressive constraint)
    def halve(curve):
        return {str(d): float(p) * 0.5 for d, p in curve.items()}
    new_pc = {
        "seated":  halve(pc_before["seated"]["power_W_by_duration_s"]
                         if "power_W_by_duration_s" in pc_before["seated"]
                         else pc_before["seated"]),
        "standing": halve(pc_before["standing"]["power_W_by_duration_s"]
                          if "power_W_by_duration_s" in pc_before["standing"]
                          else pc_before["standing"]),
    }
    try:
        PUT("/power-curves", new_pc)
        ok("power curves mutated (50% of peaks)")
    except Exception as e:
        fail(f"power-curve PUT failed: {e}")

    pc_after = GET("/power-curves")
    dump("G_pc_after", pc_after)

    job3 = POST("/optimizer/start", opt_payload)
    if job3.get("job_id"):
        res_eb2 = poll_optimizer(job3["job_id"], "EB-weakened", timeout=240)
        dump("G_optimizer_eb_weakened", res_eb2)
        if res_eb2.get("status") == "completed" and res_eb.get("status") == "completed":
            t1 = (res_eb.get("result") or {}).get("best_time_s")
            t2 = (res_eb2.get("result") or {}).get("best_time_s")
            if t1 is None or t2 is None:
                warn(f"cannot compare best_time_s (t1={t1}, t2={t2})")
            else:
                if abs(t2 - t1) < 1e-3:
                    fail(f"weakened power curve gave same best_time_s ({t1:.3f} vs {t2:.3f}) - "
                         "constraint NOT recognized")
                else:
                    ok(f"weakened curve: best_time_s {t1:.3f} -> {t2:.3f} (delta={t2-t1:+.3f}s) - "
                       "constraint recognized")

    # Restore power curve so subsequent runs aren't polluted
    try:
        seated_orig = pc_before["seated"].get("power_W_by_duration_s", pc_before["seated"])
        standing_orig = pc_before["standing"].get("power_W_by_duration_s", pc_before["standing"])
        PUT("/power-curves", {"seated": seated_orig, "standing": standing_orig})
        ok("power curves restored to pre-test values")
    except Exception as e:
        warn(f"could not restore power curves: {e}")

    # ── H. Final state snapshot ─────────────────────────────────────────────
    step("H", "Final session state")
    state_final = GET("/session/state")
    dump("H_state_final", state_final)
    if state_final.get("optimization"):
        ok(f"optimization recorded: improvement={state_final['optimization'].get('improvement_ms'):.1f}ms")
    else:
        warn("state.optimization is null after 3 optimizer runs")
    if state_final.get("last_simulation"):
        ok(f"last_simulation: T_200={state_final['last_simulation'].get('T_200')}")
    else:
        warn("state.last_simulation is null after sim runs")

    # ── Summary ─────────────────────────────────────────────────────────────
    bar = "=" * 72
    print(f"\n{bar}\n  SUMMARY\n{bar}")
    print(f"  Passed: {len(passed)}")
    print(f"  Issues: {len(issues)}")
    if issues:
        print("\n  Issue list:")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")
    else:
        print("  No issues found.")


if __name__ == "__main__":
    snapshot_id = None
    try:
        snap = POST("/session/_snapshot", {})
        snapshot_id = snap.get("snapshot_id") if isinstance(snap, dict) else None
        if not snapshot_id:
            print(f"  WARN: failed to snapshot session — continuing without rollback ({snap!r})")
        else:
            print(f"  Snapshot: {snapshot_id} (state will be restored on exit)")
        run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n  UNHANDLED EXCEPTION: {e}")
        sys.exit(2)
    finally:
        if snapshot_id:
            try:
                r = POST("/session/_restore", {"snapshot_id": snapshot_id})
                if isinstance(r, dict) and r.get("ok"):
                    print(f"  Snapshot {snapshot_id} restored — live session unchanged.")
                else:
                    print(f"  WARN: restore returned {r!r}")
            except Exception as e:
                print(f"  WARN: restore failed: {e}")
