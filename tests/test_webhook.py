from fastapi.testclient import TestClient

import app


client = TestClient(app.app)
HEADERS = {"X-Webhook-Secret": "test-webhook-secret"}


def official_payload(event_id: str, event: str = "bookings.created") -> dict:
    return {
        "event": event,
        "event_id": event_id,
        "webhook_id": "test-webhook",
        "triggered_at": "2026-09-01T12:00:00Z",
        "data": {"type": "bookings", "id": "booking-1", "number": "BB-test"},
    }


def test_duplicate_event_id_is_processed_only_once(monkeypatch):
    calls = []

    def fake_process(event: str, booking_id: str, retry_windows=None) -> dict:
        calls.append((event, booking_id))
        return {"ok": True, "event": event, "booking_id": booking_id, "redistribution": {}}

    monkeypatch.setattr(app, "process_booking_event", fake_process)
    payload = official_payload("event-once")

    first = client.post("/", headers=HEADERS, json=payload)
    duplicate = client.post("/", headers=HEADERS, json=payload)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert calls == [("bookings.created", "booking-1")]


def test_retryable_event_is_reprocessed_until_it_succeeds(monkeypatch):
    calls = []

    def fake_process(event: str, booking_id: str, retry_windows=None) -> dict:
        calls.append((event, booking_id))
        if len(calls) == 1:
            return {"ok": False, "reason": "FETCH_BOOKING_FAILED", "retryable": True}
        return {"ok": True, "event": event, "booking_id": booking_id, "redistribution": {}}

    monkeypatch.setattr(app, "process_booking_event", fake_process)
    payload = official_payload("event-retry")

    first = client.post("/", headers=HEADERS, json=payload)
    retry = client.post("/", headers=HEADERS, json=payload)
    duplicate = client.post("/", headers=HEADERS, json=payload)

    assert first.status_code == 503
    assert retry.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert len(calls) == 2
