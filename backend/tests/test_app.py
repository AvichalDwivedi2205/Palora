from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PALORA_DATA_DIR", str(tmp_path / "palora-data"))
    monkeypatch.setenv("PALORA_REPO_ROOT", str(Path(__file__).resolve().parents[2]))
    monkeypatch.setenv("PALORA_TOKEN", "test-token")
    app = create_app()
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer test-token"})
    return client


def test_snapshot_boots_with_queue(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    response = client.get("/v1/sessions/sess_demo/snapshot")
    assert response.status_code == 200
    payload = response.json()
    assert payload["queue"]
    assert payload["graph"]["nodes"]
    assert payload["stats"]["open_loops"] >= 1


def test_chat_turn_streams_draft(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    response = client.post(
        "/v1/chat/turn",
        json={
          "session_id": "sess_demo",
          "message": "Draft follow-up to Recruiter X in my tone and ask me before sending.",
          "attachments": [],
          "mode": "default",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "Tightened opener" in payload["assistant_message"]
    assert payload["artifact"]["type"] == "email_draft"
    assert payload["citations"]


def test_action_approval_executes(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    actions = client.get("/v1/actions/pending", params={"session_id": "sess_demo"}).json()
    action = next(item for item in actions if item["status"] == "pending-approval")
    response = client.post(
        f"/v1/actions/{action['id']}/approve",
        json={"prepared_hash": action["prepared_hash"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "executed"
    assert payload["result"]["status"] == "created"
