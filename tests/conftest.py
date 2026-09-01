import os
import tempfile


_test_directory = tempfile.TemporaryDirectory(prefix="anny-allocator-tests-")

os.environ["ANNY_TOKEN"] = "test-token"
os.environ["ALLOCATOR_DB"] = os.path.join(_test_directory.name, "allocator.db")
os.environ["ALLOCATE_RESOURCE_IDS"] = "181227"
os.environ["TABLE_LABELS"] = ",".join(f"Tisch {number}" for number in range(1, 9))
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["DEBUG"] = "0"
