import time

from fastapi.testclient import TestClient

from annodesk.app import create_app
from annodesk.events import EventLog


def test_log_filters_cursor_gap_and_raw_file(tmp_path):
    events = EventLog(tmp_path, files=True)
    with TestClient(create_app(events=events)) as client:
        events.emit("INFO", "model ready", project_id="a")
        events.emit("WARNING", "device warning", project_id="b")
        events.emit("SUCCESS", "completed")
        page = client.get("/api/v1/logs?level=20&comparison=eq&project_id=a").json()
        assert [r["message"] for r in page["items"]] == ["model ready"]
        assert events.read(page["next_cursor"])["items"] == []
        assert events.read("old-session:1")["gap"]
        assert "event_type" in page["items"][0] and "filename" not in page["items"][0]
        response = client.get("/api/v1/logs/download")
        assert response.status_code == 200
        assert "device warning" in response.text and "events.py" not in response.text
        assert client.get("/api/v1/logs?comparison=bad").status_code == 422


def test_error_aggregation_and_ring_bound(tmp_path):
    events = EventLog(tmp_path, files=True)
    for _ in range(4):
        events.emit("ERROR", "failed", event_type="inference", error_code="model")
    assert len(events.read()["items"]) == 1
    for item in events.repeats.values():
        item["at"] = time.monotonic() - 11
    summary = events.read()["items"][-1]
    assert summary["repeat_count"] == 3
    assert events.path.read_text().count("failed") == 4
    # Suppress file/console flood while exercising the bounded UI buffer.
    with events.lock:
        for i in range(2005):
            events._append("INFO", str(i), {})
    assert len(events.events) == 2000
    assert events.read(events.session_id + ":1")["gap"]
    events.close()
