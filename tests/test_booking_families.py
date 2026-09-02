import app


START = "2026-09-02T11:00:00+00:00"
END = "2026-09-02T12:00:00+00:00"
RESOURCE_ID = "181227"
SERVICE_ID = "82490"


def booking_data(
    booking_id: str,
    *,
    is_sub_booking: bool = False,
    sub_booking_ids: list[str] | None = None,
    super_booking_id: str = "",
    status: str = "accepted",
    description: str = "",
) -> dict:
    relationships = {
        "resource": {"data": {"type": "resources", "id": RESOURCE_ID}},
        "service": {"data": {"type": "services", "id": SERVICE_ID}},
    }
    if sub_booking_ids is not None:
        relationships["sub_bookings"] = {
            "data": [
                {"type": "bookings", "id": child_id}
                for child_id in sub_booking_ids
            ]
        }
    if super_booking_id:
        relationships["super_booking"] = {
            "data": {"type": "bookings", "id": super_booking_id}
        }
    return {
        "type": "bookings",
        "id": booking_id,
        "attributes": {
            "number": f"BB-{booking_id}",
            "start_date": START,
            "end_date": END,
            "weight": 1,
            "status": status,
            "canceled_at": "2026-09-02T10:00:00+00:00" if status == "canceled" else None,
            "description": description,
            "note": "",
            "customer_note": "",
            "is_sub_booking": is_sub_booking,
        },
        "relationships": relationships,
    }


def family_response(child_ids: list[str], *, status: str = "accepted") -> dict:
    root = booking_data(
        "root",
        sub_booking_ids=child_ids,
        status=status,
        description="Geburtstag",
    )
    children = [
        booking_data(child_id, is_sub_booking=True, super_booking_id="root")
        for child_id in child_ids
    ]
    return {"data": root, "included": children}


def test_main_booking_is_patched_first_with_all_optional_resource_tables(monkeypatch):
    response = family_response(["child-1", "child-2"])
    patch_calls = []

    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: response)

    def fake_patch(booking_id, attrs):
        patch_calls.append((booking_id, attrs))
        return {"data": {"type": "bookings", "id": booking_id}}

    monkeypatch.setattr(app, "patch_booking", fake_patch)

    result = app.process_booking_event("bookings.created", "root")

    assert result["ok"] is True
    assert result["family"] is True
    assert result["need"] == 3
    assert result["tables"] == ["Tisch 1", "Tisch 2", "Tisch 3"]
    assert [booking_id for booking_id, _attrs in patch_calls] == [
        "root",
        "child-1",
        "child-2",
    ]
    assert patch_calls[0][1]["customer_note"] == "Deine Tische: Tisch 1, Tisch 2, Tisch 3"
    assert patch_calls[0][1]["description"] == (
        "TISCHE: Tisch 1, Tisch 2, Tisch 3 — Geburtstag"
    )
    assert app.get_allocation("root").root_booking_id == "root"
    assert app.get_allocation("child-1").root_booking_id == "root"
    assert app.get_allocation("child-2").root_booking_id == "root"


def test_sub_booking_webhook_resolves_and_updates_main_booking(monkeypatch):
    root_response = family_response(["child-1", "child-2"])
    child_response = {
        "data": booking_data(
            "child-1",
            is_sub_booking=True,
            super_booking_id="root",
        )
    }
    fetch_calls = []
    patch_calls = []

    def fake_fetch(booking_id):
        fetch_calls.append(booking_id)
        return child_response if booking_id == "child-1" else root_response

    monkeypatch.setattr(app, "fetch_booking", fake_fetch)
    monkeypatch.setattr(
        app,
        "patch_booking",
        lambda booking_id, attrs: patch_calls.append((booking_id, attrs))
        or {"data": {"id": booking_id}},
    )

    result = app.process_booking_event("bookings.created", "child-1")

    assert result["ok"] is True
    assert fetch_calls == ["child-1", "root"]
    assert patch_calls[0][0] == "root"
    assert patch_calls[0][1]["customer_note"] == "Deine Tische: Tisch 1, Tisch 2, Tisch 3"


def test_deleting_optional_resource_removes_its_table_from_main_booking(monkeypatch):
    responses = {"root": family_response(["child-1", "child-2"])}
    patch_calls = []

    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: responses["root"])
    monkeypatch.setattr(
        app,
        "patch_booking",
        lambda booking_id, attrs: patch_calls.append((booking_id, attrs))
        or {"data": {"id": booking_id}},
    )
    app.process_booking_event("bookings.created", "root")

    responses["root"] = family_response(["child-2"])
    patch_calls.clear()
    result = app.process_booking_event("bookings.deleted", "child-1")

    assert result["ok"] is True
    assert app.get_allocation("child-1") is None
    assert app.get_allocation("root").tables == ["Tisch 1"]
    assert app.get_allocation("child-2").tables == ["Tisch 3"]
    assert patch_calls[0][0] == "root"
    assert patch_calls[0][1]["customer_note"] == "Deine Tische: Tisch 1 & Tisch 3"


def test_deleted_optional_resource_keeps_parent_mapping_for_api_retry(monkeypatch):
    active = family_response(["child-1"])
    current = {"response": active}
    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: current["response"])
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})
    app.process_booking_event("bookings.created", "root")

    current["response"] = {"errors": [{"status": "503", "title": "Unavailable"}]}
    failed = app.process_booking_event("bookings.deleted", "child-1")

    assert failed["retryable"] is True
    assert app.get_allocation("child-1").root_booking_id == "root"

    current["response"] = family_response([])
    retried = app.process_booking_event("bookings.deleted", "child-1")

    assert retried["ok"] is True
    assert app.get_allocation("child-1") is None
    assert app.get_allocation("root").tables == ["Tisch 1"]


def test_canceling_main_booking_removes_the_complete_family(monkeypatch):
    active = family_response(["child-1", "child-2"])
    canceled = family_response(["child-1", "child-2"], status="canceled")
    current = {"response": active}

    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: current["response"])
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})
    app.process_booking_event("bookings.created", "root")

    current["response"] = canceled
    result = app.process_booking_event("bookings.updated", "root")

    assert result["reason"] == "BOOKING_FAMILY_CANCELED_DB_CLEANED"
    assert app.get_allocation("root") is None
    assert app.get_allocation("child-1") is None
    assert app.get_allocation("child-2") is None


def test_main_patch_failure_rolls_back_new_family_capacity(monkeypatch):
    response = family_response(["child-1", "child-2"])
    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: response)
    monkeypatch.setattr(
        app,
        "patch_booking",
        lambda booking_id, attrs: {"errors": [{"status": "503", "title": "Unavailable"}]},
    )

    result = app.process_booking_event("bookings.created", "root")

    assert result["reason"] == "ANNY_PATCH_FAILED"
    assert result["retryable"] is True
    for booking_id in ("root", "child-1", "child-2"):
        allocation = app.get_allocation(booking_id)
        assert allocation.status == "unassigned"
        assert allocation.tables == []


def test_family_member_validation_failure_does_not_leave_unpatched_capacity(monkeypatch):
    response = family_response(["child-1"])
    response["included"][0]["relationships"].pop("resource")
    monkeypatch.setattr(app, "fetch_booking", lambda booking_id: response)
    monkeypatch.setattr(app, "patch_booking", lambda booking_id, attrs: {"data": {"id": booking_id}})

    result = app.process_booking_event("bookings.created", "root")

    assert result["reason"] == "NO_RESOURCE_ID"
    assert result["retryable"] is True
    root = app.get_allocation("root")
    assert root.status == "unassigned"
    assert root.tables == []
    assert app.get_allocation("child-1") is None
