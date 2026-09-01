import threading
import time
from concurrent.futures import ThreadPoolExecutor

import app


START = "2026-09-05T18:00:00+00:00"
END = "2026-09-05T20:00:00+00:00"


def booking_payload(
    booking_id: str,
    *,
    status: str = "confirmed",
    weight: int = 1,
    description: str = "",
    start_date: str = START,
    end_date: str = END,
) -> dict:
    return {
        "data": {
            "type": "bookings",
            "id": booking_id,
            "attributes": {
                "number": f"BB-{booking_id}",
                "start_date": start_date,
                "end_date": end_date,
                "weight": weight,
                "status": status,
                "canceled_at": "2026-09-01T10:00:00Z" if status == "canceled" else None,
                "description": description,
                "note": "",
                "customer_note": "",
            },
            "relationships": {
                "resource": {"data": {"type": "resources", "id": "181227"}},
                "service": {"data": {"type": "services", "id": "83445"}},
            },
        }
    }


def add_allocation(booking_id: str, tables: list[str], need: int = 1):
    app.upsert_allocation(
        app.Allocation(
            booking_id=booking_id,
            booking_number=f"BB-{booking_id}",
            resource_id="181227",
            service_id="83445",
            start_date=START,
            end_date=END,
            need=need,
            tables=tables,
            status="assigned",
        )
    )


def test_capacity_failure_removes_canceled_blocker_and_retries(monkeypatch):
    for number, table in enumerate(app.TABLES, start=1):
        add_allocation(f"old-{number}", [table])

    def fake_fetch(booking_id: str) -> dict:
        if booking_id == "new":
            return booking_payload("new")
        if booking_id == "old-1":
            return booking_payload("old-1", status="canceled")
        return booking_payload(booking_id)

    monkeypatch.setattr(app, "fetch_booking", fake_fetch)
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    result = app.ensure_allocation_for_booking("new", event="bookings.created")

    assert result["ok"] is True
    assert result["tables"] == ["Tisch 1"]
    assert result["mode"] == "adjacent"
    assert result["reconciliation"]["attempted"] is True
    assert result["reconciliation"]["checked"] == 8
    assert result["reconciliation"]["removed_count"] == 1
    assert result["reconciliation"]["removed"][0]["reason"] == "BOOKING_CANCELED"
    assert app.get_allocation("old-1") is None
    assert app.get_allocation("new").tables == ["Tisch 1"]


def test_deleted_booking_is_removed_but_api_errors_fail_closed(monkeypatch):
    add_allocation("deleted", ["Tisch 1"])
    add_allocation("unknown", ["Tisch 2"])

    def fake_fetch(booking_id: str) -> dict:
        if booking_id == "deleted":
            return {"errors": [{"status": "404", "title": "Not Found"}]}
        return {"errors": [{"status": "503", "title": "Unavailable"}]}

    monkeypatch.setattr(app, "fetch_booking", fake_fetch)

    result = app.cleanup_stale_overlapping_allocations(
        app.parse_iso(START),
        app.parse_iso(END),
        resource_id="181227",
    )

    assert result["removed_count"] == 1
    assert result["api_error_count"] == 1
    assert app.get_allocation("deleted") is None
    assert app.get_allocation("unknown") is not None


def test_booking_does_not_block_its_own_reallocation(monkeypatch):
    add_allocation("moving", ["Tisch 1"], need=1)
    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: booking_payload("moving", weight=2))
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    result = app.ensure_allocation_for_booking("moving", event="manual.reconcile")

    assert result["ok"] is True
    assert result["tables"] == ["Tisch 1", "Tisch 2"]
    assert app.get_allocation("moving").need == 2


def test_real_update_is_not_skipped_when_own_marker_exists(monkeypatch):
    add_allocation("moving", ["Tisch 1"], need=1)
    payload = booking_payload("moving", weight=2, description="TISCHE: Tisch 1 — Teamnotiz")
    payload["data"]["attributes"]["note"] = "Auto-Allocation: Tisch 1"

    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: payload)
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    result = app.process_booking_event("bookings.updated", "moving")
    allocation = app.get_allocation("moving")

    assert result["ok"] is True
    assert allocation.need == 2
    assert allocation.tables == ["Tisch 1", "Tisch 2"]
    assert result["patch"]["response"]["data"]["id"] == "moving"


def test_deleted_booking_redistributes_oldest_open_allocation(monkeypatch):
    for number, table in enumerate(app.TABLES, start=1):
        add_allocation(f"old-{number}", [table])
    app.upsert_allocation(
        app.Allocation(
            booking_id="waiting",
            booking_number="BB-waiting",
            resource_id="181227",
            service_id="83445",
            start_date=START,
            end_date=END,
            need=1,
            tables=[],
            status="unassigned",
        )
    )

    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: booking_payload("waiting"))
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    result = app.process_booking_event("bookings.deleted", "old-1")

    assert app.get_allocation("old-1") is None
    assert app.get_allocation("waiting").tables == ["Tisch 1"]
    assert result["redistribution"]["assigned_count"] == 1


def test_canceled_update_releases_table_and_redistributes(monkeypatch):
    for number, table in enumerate(app.TABLES, start=1):
        add_allocation(f"old-{number}", [table])
    app.upsert_allocation(
        app.Allocation(
            booking_id="waiting",
            booking_number="BB-waiting",
            resource_id="181227",
            service_id="83445",
            start_date=START,
            end_date=END,
            need=1,
            tables=[],
            status="unassigned",
        )
    )

    def fake_fetch(booking_id: str) -> dict:
        if booking_id == "old-1":
            return booking_payload("old-1", status="canceled")
        return booking_payload(booking_id)

    monkeypatch.setattr(app, "fetch_booking", fake_fetch)
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    result = app.process_booking_event("bookings.updated", "old-1")

    assert app.get_allocation("old-1") is None
    assert app.get_allocation("waiting").tables == ["Tisch 1"]
    assert result["redistribution"]["assigned_count"] == 1


def test_time_change_releases_old_window_and_redistributes(monkeypatch):
    for number, table in enumerate(app.TABLES, start=1):
        add_allocation(f"old-{number}", [table])
    app.upsert_allocation(
        app.Allocation(
            booking_id="waiting",
            booking_number="BB-waiting",
            resource_id="181227",
            service_id="83445",
            start_date=START,
            end_date=END,
            need=1,
            tables=[],
            status="unassigned",
        )
    )

    def fake_fetch(booking_id: str) -> dict:
        if booking_id == "old-1":
            return booking_payload(
                "old-1",
                start_date="2026-09-06T18:00:00+00:00",
                end_date="2026-09-06T20:00:00+00:00",
            )
        return booking_payload(booking_id)

    monkeypatch.setattr(app, "fetch_booking", fake_fetch)
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    result = app.process_booking_event("bookings.updated", "old-1")

    assert app.get_allocation("old-1").start_date == "2026-09-06T18:00:00+00:00"
    assert app.get_allocation("waiting").tables == ["Tisch 1"]
    assert result["redistribution"]["assigned_count"] == 1


def test_redistribution_assigns_oldest_waiting_booking_first(monkeypatch):
    for number, table in enumerate(app.TABLES, start=1):
        add_allocation(f"old-{number}", [table])
    for booking_id in ("waiting-oldest", "waiting-newer"):
        app.upsert_allocation(
            app.Allocation(
                booking_id=booking_id,
                booking_number=f"BB-{booking_id}",
                resource_id="181227",
                service_id="83445",
                start_date=START,
                end_date=END,
                need=1,
                tables=[],
                status="unassigned",
            )
        )
    with app.db() as connection:
        connection.execute(
            "UPDATE allocations SET created_at='2026-09-01T10:00:00+00:00' WHERE booking_id='waiting-oldest'"
        )
        connection.execute(
            "UPDATE allocations SET created_at='2026-09-01T11:00:00+00:00' WHERE booking_id='waiting-newer'"
        )
        connection.commit()

    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: booking_payload(booking_id))
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    result = app.process_booking_event("bookings.deleted", "old-1")

    assert app.get_allocation("waiting-oldest").tables == ["Tisch 1"]
    assert app.get_allocation("waiting-newer").status == "unassigned"
    assert result["redistribution"]["assigned_count"] == 1


def test_patch_failure_is_retryable_and_not_marked_as_synced(monkeypatch):
    add_allocation("existing", ["Tisch 1"])
    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: booking_payload("existing"))
    monkeypatch.setattr(
        app,
        "patch_booking",
        lambda booking_id, attrs: {"errors": [{"status": "503", "title": "Unavailable"}]},
    )

    result = app.ensure_allocation_for_booking("existing", event="bookings.updated")
    allocation = app.get_allocation("existing")

    assert result["ok"] is False
    assert result["reason"] == "ANNY_PATCH_FAILED"
    assert result["retryable"] is True
    assert allocation.last_patch_hash == ""
    assert allocation.patched_at == ""


def test_new_assignment_is_rolled_back_when_anny_patch_fails(monkeypatch):
    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: booking_payload("new"))
    monkeypatch.setattr(
        app,
        "patch_booking",
        lambda booking_id, attrs: {"errors": [{"status": "503", "title": "Unavailable"}]},
    )

    result = app.ensure_allocation_for_booking("new", event="bookings.created")
    allocation = app.get_allocation("new")

    assert result["retryable"] is True
    assert result["allocation_rolled_back"] is True
    assert allocation.status == "unassigned"
    assert allocation.tables == []


def test_failed_redistribution_window_can_be_retried(monkeypatch):
    for number, table in enumerate(app.TABLES, start=1):
        add_allocation(f"old-{number}", [table])
    app.upsert_allocation(
        app.Allocation(
            booking_id="waiting",
            booking_number="BB-waiting",
            resource_id="181227",
            service_id="83445",
            start_date=START,
            end_date=END,
            need=1,
            tables=[],
            status="unassigned",
        )
    )
    attempts = 0

    def flaky_fetch(booking_id: str) -> dict:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {"errors": [{"status": "503", "title": "Unavailable"}]}
        return booking_payload("waiting")

    monkeypatch.setattr(app, "fetch_booking", flaky_fetch)
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    first = app.process_booking_event("bookings.deleted", "old-1")
    second = app.process_booking_event(
        "bookings.deleted",
        "old-1",
        retry_windows=first["redistribution"]["windows"],
    )

    assert first["retryable"] is True
    assert first["redistribution"]["error_count"] == 1
    assert second["redistribution"]["error_count"] == 0
    assert app.get_allocation("waiting").tables == ["Tisch 1"]


def test_simultaneous_allocations_are_serialized(monkeypatch):
    counter_lock = threading.Lock()
    active_fetches = 0
    max_active_fetches = 0

    def fake_fetch(booking_id: str) -> dict:
        nonlocal active_fetches, max_active_fetches
        with counter_lock:
            active_fetches += 1
            max_active_fetches = max(max_active_fetches, active_fetches)
        time.sleep(0.03)
        with counter_lock:
            active_fetches -= 1
        return booking_payload(booking_id)

    monkeypatch.setattr(app, "fetch_booking", fake_fetch)
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda booking_id: app.ensure_allocation_for_booking(booking_id, event="bookings.created"),
                ["parallel-1", "parallel-2"],
            )
        )

    assert max_active_fetches == 1
    assert results[0]["tables"] != results[1]["tables"]
