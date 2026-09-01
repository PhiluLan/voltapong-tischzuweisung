import app


START = "2026-09-05T18:00:00+00:00"
END = "2026-09-05T20:00:00+00:00"


def booking_payload(
    booking_id: str,
    *,
    status: str = "confirmed",
    weight: int = 1,
    description: str = "",
) -> dict:
    return {
        "data": {
            "type": "bookings",
            "id": booking_id,
            "attributes": {
                "number": f"BB-{booking_id}",
                "start_date": START,
                "end_date": END,
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
