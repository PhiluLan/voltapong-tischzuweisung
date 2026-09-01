from datetime import datetime, timezone

import app


def test_compute_need_accepts_valid_weight_and_defaults_invalid_values():
    assert app.compute_need(3) == 3
    assert app.compute_need("8") == 8
    assert app.compute_need(None) == 1
    assert app.compute_need("unknown") == 1
    assert app.compute_need(0) == 1
    assert app.compute_need(9) == 1


def test_adjacent_group_uses_first_contiguous_free_block():
    busy = {table: False for table in app.TABLES}
    busy["Tisch 1"] = True
    busy["Tisch 4"] = True

    assert app.pick_adjacent_group(2, busy) == ["Tisch 2", "Tisch 3"]


def test_any_free_group_is_split_fallback_in_table_order():
    busy = {table: table in {"Tisch 2", "Tisch 4", "Tisch 6", "Tisch 8"} for table in app.TABLES}

    assert app.pick_adjacent_group(3, busy) is None
    assert app.pick_any_free_group(3, busy) == ["Tisch 1", "Tisch 3", "Tisch 5"]


def test_overlaps_treats_touching_intervals_as_non_overlapping():
    at_1800 = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    at_1900 = datetime(2026, 9, 1, 19, 0, tzinfo=timezone.utc)
    at_1930 = datetime(2026, 9, 1, 19, 30, tzinfo=timezone.utc)
    at_2000 = datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc)

    assert app.overlaps(at_1800, at_1900, at_1900, at_2000) is False
    assert app.overlaps(at_1800, at_1930, at_1900, at_2000) is True


def test_desired_patch_fields_marks_split_assignment():
    fields = app.desired_patch_fields(
        ["Tisch 1", "Tisch 3", "Tisch 5"],
        "Geburtstagsrunde",
        split=True,
    )

    assert fields["customer_note"] == "Deine Tische: Tisch 1, Tisch 3, Tisch 5"
    assert fields["note"] == "Auto-Allocation: Tisch 1, Tisch 3, Tisch 5 (Split)"
    assert fields["description"] == "TISCHE: Tisch 1, Tisch 3, Tisch 5 — Geburtstagsrunde"


def test_extract_event_and_booking_id_supports_nested_payload():
    event, booking_id = app.extract_event_and_booking_id(
        {"event": "bookings.updated", "data": {"type": "bookings", "id": 4711}},
        {},
    )

    assert event == "bookings.updated"
    assert booking_id == "4711"


def test_extract_event_uses_headers_and_defaults_event():
    assert app.extract_event_and_booking_id({"booking_id": "12"}, {}) == ("bookings.created", "12")
    assert app.extract_event_and_booking_id(
        {"booking_id": "13"},
        {"x-anny-event": "bookings.deleted"},
    ) == ("bookings.deleted", "13")


def test_cancellation_detection_covers_status_and_timestamp():
    assert app.is_booking_canceled({"status": "cancelled"})[0] is True
    assert app.is_booking_canceled({"status": "confirmed", "canceled_at": "2026-09-01T12:00:00Z"})[0] is True
    assert app.is_booking_canceled({"status": "confirmed", "canceled_at": None})[0] is False
