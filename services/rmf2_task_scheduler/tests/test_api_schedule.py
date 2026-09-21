"""FastAPI smoke test against a tmp_path-backed ScheduleStream.

Env vars are set before the first import of ``rmf2_task_scheduler.app`` so that
the module-level ``config = settings()`` in app.py picks up a throwaway
schedule stream path instead of the project's own data/ directory.
"""

from __future__ import annotations

import sys
from uuid import uuid4

from fastapi.testclient import TestClient


def test_health_info_and_dry_run_edit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RMF2_TS__HOST", "0.0.0.0")
    monkeypatch.setenv("RMF2_TS__PORT", "8000")
    monkeypatch.setenv("RMF2_TS__SCHEDULE_STREAM_PATH", str(tmp_path / "stream"))
    monkeypatch.setenv("RMF2_TS__DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    # config.py's CliSettingsSource parses the real sys.argv; swap it out so
    # pytest's own flags (-v, etc.) aren't mistaken for app CLI args.
    monkeypatch.setattr(sys, "argv", ["rmf2_task_scheduler"])

    from rmf2_task_scheduler.app import app

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        resp = client.get("/info")
        assert resp.status_code == 200
        assert resp.json()["api_version"] == "v1"

        action = {
            "type": "TASK_ADD",
            "task": {
                "id": str(uuid4()),
                "type": "demo",
                "start_time": "2030-01-01T00:00:00",
            },
        }
        resp = client.post("/v1/schedule/edit", params={"dry_run": "true"}, json=action)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"message": "Dry run successfully."}
