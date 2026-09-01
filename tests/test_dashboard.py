from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app


client = TestClient(app.app)
AUTH = ("test-admin", "test-dashboard-password")


def add_dashboard_allocation(
    booking_id: str,
    *,
    start: datetime,
    end: datetime,
    tables: list[str],
    status: str = "assigned",
):
    app.upsert_allocation(
        app.Allocation(
            booking_id=booking_id,
            booking_number=f"BB-{booking_id}",
            resource_id="181227",
            service_id="83445",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            need=max(1, len(tables)),
            tables=tables,
            status=status,
        )
    )


def test_dashboard_and_allocations_are_protected():
    dashboard_response = client.get("/dashboard")
    allocations_response = client.get("/allocations")

    assert dashboard_response.status_code == 401
    assert dashboard_response.headers["www-authenticate"].startswith("Basic")
    assert allocations_response.status_code == 401


def test_dashboard_page_and_data_are_available_with_basic_auth():
    now = datetime.now(timezone.utc)
    add_dashboard_allocation(
        "current",
        start=now - timedelta(minutes=30),
        end=now + timedelta(minutes=90),
        tables=["Tisch 1", "Tisch 2"],
    )

    page_response = client.get("/dashboard", auth=AUTH)
    data_response = client.get("/dashboard/data", auth=AUTH)

    assert page_response.status_code == 200
    assert "Volta Pong" in page_response.text
    assert "So funktioniert die Zuweisung" in page_response.text
    assert data_response.status_code == 200
    data = data_response.json()
    assert data["status"] == "ok"
    assert data["summary"]["occupied_now"] == 2
    assert data["summary"]["free_now"] == 6
    assert data["summary"]["current_bookings"] == 1
    assert data["current"][0]["booking_number"] == "BB-current"
    assert "booking_id" not in data["current"][0]


def test_dashboard_reports_future_unassigned_as_warning():
    now = datetime.now(timezone.utc)
    add_dashboard_allocation(
        "open",
        start=now + timedelta(hours=2),
        end=now + timedelta(hours=4),
        tables=[],
        status="unassigned",
    )

    data = client.get("/dashboard/data", auth=AUTH).json()

    assert data["status"] == "warning"
    assert data["summary"]["future_unassigned"] == 1
    assert data["issues"]["unassigned"][0]["booking_number"] == "BB-open"


def test_dashboard_detects_table_collision():
    now = datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc)
    add_dashboard_allocation(
        "first",
        start=now - timedelta(minutes=30),
        end=now + timedelta(hours=1),
        tables=["Tisch 3"],
    )
    add_dashboard_allocation(
        "second",
        start=now,
        end=now + timedelta(hours=2),
        tables=["Tisch 3"],
    )

    data = app.dashboard_snapshot(now=now)

    assert data["status"] == "error"
    assert data["summary"]["collisions"] == 1
    assert data["issues"]["collisions"][0]["tables"] == ["Tisch 3"]
