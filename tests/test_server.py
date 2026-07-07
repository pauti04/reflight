"""Sprint 2: REST endpoints over the store."""

from fastapi.testclient import TestClient

import main as example
from fake_model import FakeAnthropic
from tools import make_tools

from reflight import Recorder
from reflight.server import create_app

TASK = "What is 12 divided by 0? Use the calculator."


def _client(tmp_path) -> TestClient:
    db = tmp_path / "test.db"
    run_dir = tmp_path / "runs" / "api-demo"
    session = Recorder(run_dir, FakeAnthropic(), make_tools(run_dir / "notes"), db_path=db)
    example.run_agent(session, TASK)
    return TestClient(create_app(db))


def test_runs_endpoint(tmp_path):
    client = _client(tmp_path)
    runs = client.get("/api/runs").json()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "api-demo"
    assert runs[0]["tool_errors"] == 1

    run = client.get("/api/runs/api-demo").json()
    assert run["model"] == "claude-sonnet-5"
    assert client.get("/api/runs/nope").status_code == 404


def test_promote_endpoint(tmp_path):
    db = tmp_path / "test.db"
    run_dir = tmp_path / "runs" / "api-demo"
    session = Recorder(run_dir, FakeAnthropic(), make_tools(run_dir / "notes"), db_path=db)
    example.run_agent(session, TASK)

    client = TestClient(create_app(db, tests_dir=tmp_path / "agent_tests"))
    response = client.post("/api/runs/api-demo/promote")
    assert response.status_code == 200
    body = response.json()
    assert body["path"].endswith("api-demo.yaml")
    assert "assertions" in body["yaml"]
    assert (tmp_path / "agent_tests" / "api-demo.yaml").exists()

    assert client.post("/api/runs/nope/promote").status_code == 404


def test_events_endpoint(tmp_path):
    client = _client(tmp_path)
    events = client.get("/api/runs/api-demo/events").json()
    assert [e["event"]["type"] for e in events][:3] == ["run_start", "llm_call", "tool_call"]
    tool_call = events[2]["event"]
    assert tool_call["is_error"] is True
    llm_costs = [e["cost_usd"] for e in events if e["event"]["type"] == "llm_call"]
    assert all(c > 0 for c in llm_costs)
