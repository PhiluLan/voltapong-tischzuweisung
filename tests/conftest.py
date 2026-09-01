import os
import tempfile

import pytest


_test_directory = tempfile.TemporaryDirectory(prefix="anny-allocator-tests-")

os.environ["ANNY_TOKEN"] = "test-token"
os.environ["ALLOCATOR_DB"] = os.path.join(_test_directory.name, "allocator.db")
os.environ["ALLOCATE_RESOURCE_IDS"] = "181227"
os.environ["TABLE_LABELS"] = ",".join(f"Tisch {number}" for number in range(1, 9))
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["DASHBOARD_USERNAME"] = "test-admin"
os.environ["DASHBOARD_PASSWORD"] = "test-dashboard-password"
os.environ["DASHBOARD_REFRESH_SECONDS"] = "30"
os.environ["DEBUG"] = "0"


@pytest.fixture(autouse=True)
def clean_allocations():
    import app

    with app.db() as connection:
        connection.execute("DELETE FROM allocations")
        connection.execute("DELETE FROM webhook_events")
        connection.commit()
    yield
