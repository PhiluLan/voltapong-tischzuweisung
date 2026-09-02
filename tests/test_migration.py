import sqlite3

import app


def test_init_db_adds_webhook_events_without_changing_allocations(tmp_path, monkeypatch):
    database_path = tmp_path / "production-copy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE allocations (
                booking_id TEXT PRIMARY KEY,
                booking_number TEXT,
                resource_id TEXT,
                service_id TEXT,
                start_date TEXT,
                end_date TEXT,
                need INTEGER,
                tables_csv TEXT,
                status TEXT,
                last_patch_hash TEXT,
                patched_at TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO allocations (
                booking_id, booking_number, resource_id, service_id,
                start_date, end_date, need, tables_csv, status
            ) VALUES ('existing', 'BB-existing', '181227', '83445',
                      '2026-09-05T18:00:00+00:00', '2026-09-05T20:00:00+00:00',
                      1, 'Tisch 1', 'assigned')
            """
        )
        connection.commit()

    monkeypatch.setattr(app, "DB_PATH", str(database_path))
    app.init_db()

    with app.db() as connection:
        allocation_count = connection.execute("SELECT COUNT(*) FROM allocations").fetchone()[0]
        event_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='webhook_events'"
        ).fetchone()
        allocation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(allocations)").fetchall()
        }

    assert allocation_count == 1
    assert event_table[0] == "webhook_events"
    assert "root_booking_id" in allocation_columns
