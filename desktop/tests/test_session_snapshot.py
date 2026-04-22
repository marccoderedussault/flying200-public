"""Unit tests for the /api/session/_snapshot and /api/session/_restore endpoints.

These guard the test-isolation contract: the portfolio-flow E2E (and any other
test that pokes a running desktop server) must be able to capture the in-memory
state, run, and restore so the live session is unchanged.
"""
import sys
from pathlib import Path

import pytest

DESKTOP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DESKTOP))
sys.path.insert(0, str(DESKTOP / "gui" / "web"))

import server  # type: ignore


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def _set_track(client, key):
    return client.put("/api/session/track", json={"track": key})


def _get_track(client):
    return client.get("/api/session").get_json()["track"]


def test_snapshot_returns_opaque_id(client):
    r = client.post("/api/session/_snapshot", json={})
    assert r.status_code == 200
    data = r.get_json()
    assert "snapshot_id" in data
    assert isinstance(data["snapshot_id"], str)
    assert len(data["snapshot_id"]) >= 16


def test_restore_unknown_id_returns_404(client):
    r = client.post("/api/session/_restore", json={"snapshot_id": "no-such-snapshot"})
    assert r.status_code == 404


def test_restore_round_trips_track_selection(client):
    _set_track(client, "Bromont")
    pre = _get_track(client)
    snap_id = client.post("/api/session/_snapshot", json={}).get_json()["snapshot_id"]

    _set_track(client, "Milton")
    assert _get_track(client) != pre, "test setup precondition: track must change"

    restore = client.post("/api/session/_restore", json={"snapshot_id": snap_id})
    assert restore.status_code == 200
    assert restore.get_json() == {"ok": True}
    assert _get_track(client) == pre


def test_restore_round_trips_fit_data_store(client):
    snap_id = client.post("/api/session/_snapshot", json={}).get_json()["snapshot_id"]
    pre_keys = set(server.fit_data_store.keys())

    server.fit_data_store["test-key-xyz"] = {"sentinel": True}
    assert "test-key-xyz" in server.fit_data_store

    client.post("/api/session/_restore", json={"snapshot_id": snap_id})
    assert set(server.fit_data_store.keys()) == pre_keys
    assert "test-key-xyz" not in server.fit_data_store


def test_snapshot_id_is_consumed_on_restore(client):
    """A snapshot id is single-use: restoring twice with the same id must 404 the second time."""
    snap_id = client.post("/api/session/_snapshot", json={}).get_json()["snapshot_id"]
    first = client.post("/api/session/_restore", json={"snapshot_id": snap_id})
    second = client.post("/api/session/_restore", json={"snapshot_id": snap_id})
    assert first.status_code == 200
    assert second.status_code == 404
