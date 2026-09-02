#!/usr/bin/env python3
import base64
import secrets
import os
import json
import sqlite3
import urllib.request
import urllib.error
import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Config
# -----------------------------
ANNY_BASE = os.environ.get("ANNY_BASE", "https://b.anny.co/api/v1").rstrip("/")
ANNY_TOKEN = os.environ["ANNY_TOKEN"]

TABLES = os.environ.get(
    "TABLE_LABELS",
    "Tisch 1,Tisch 2,Tisch 3,Tisch 4,Tisch 5,Tisch 6,Tisch 7,Tisch 8"
).split(",")

DEBUG = os.environ.get("DEBUG", "0") == "1"
DB_PATH = os.environ.get("ALLOCATOR_DB", os.path.expanduser("~/anny_webhook/allocator.db"))

MARKER = os.environ.get("AUTO_MARKER", "TISCHE:")
NOTE_PREFIX = os.environ.get("AUTO_PREFIX", "Auto-Allocation:")

HANDLE_UPDATED = os.environ.get("HANDLE_UPDATED", "1") not in ("0", "false", "False")
REDISTRIBUTION_LIMIT = max(1, int(os.environ.get("REDISTRIBUTION_LIMIT", "20")))
WEBHOOK_EVENT_RETENTION_DAYS = max(1, int(os.environ.get("WEBHOOK_EVENT_RETENTION_DAYS", "90")))

# Optional: restrict allocator to certain resource IDs (comma separated).
# If empty -> applies to ALL resources.
ALLOCATE_RESOURCE_IDS = set(
    [x.strip() for x in os.environ.get("ALLOCATE_RESOURCE_IDS", "").split(",") if x.strip()]
)

# Webhook auth (supports BOTH header and query key)
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()

# Dashboard auth is deliberately fail-closed. There are no default credentials.
DASHBOARD_USERNAME = os.environ.get("DASHBOARD_USERNAME", "").strip()
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "").strip()
DASHBOARD_REFRESH_SECONDS = max(10, int(os.environ.get("DASHBOARD_REFRESH_SECONDS", "30")))
DASHBOARD_TEMPLATE = Path(__file__).resolve().parent / "templates" / "dashboard.html"

app = FastAPI(title="Volta Pong Tischzuweisung", version="3.1.0")

# Uvicorn runs this service with one worker. Serializing the complete
# read/choose/write cycle prevents simultaneous webhooks from choosing the
# same table before either allocation has reached SQLite.
ALLOCATION_LOCK = threading.RLock()


def dprint(*a):
    if DEBUG:
        print("[DEBUG]", *a, flush=True)


# -----------------------------
# Time helpers
# -----------------------------
def parse_iso(dt: str) -> datetime:
    return datetime.fromisoformat(dt.replace("Z", "+00:00"))


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


# -----------------------------
# HTTP (Anny)
# -----------------------------
def http_json(method: str, path: str, body: Optional[dict] = None) -> dict:
    url = f"{ANNY_BASE}{path}"
    data = None

    # Cloudflare-friendly headers (keep!)
    headers = {
        "Authorization": f"Bearer {ANNY_TOKEN}",
        "Accept": "application/vnd.api+json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://anny.co",
        "Referer": "https://anny.co/",
        "X-App-Key": "anny_shop",
        "Accept-Language": "de,en;q=0.8",
    }

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/vnd.api+json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
            j = json.loads(raw.decode("utf-8"))
            if isinstance(j, dict):
                return j
        except Exception:
            pass
        return {"errors": [{"status": str(e.code), "title": str(e)}]}
    except Exception as e:
        return {"errors": [{"status": "0", "title": "Request failed", "detail": str(e)}]}


def fetch_booking(booking_id: str) -> dict:
    # Include only technical relationships used by the allocator. In
    # particular, Anny represents an optional additional resource as one or
    # more sub-bookings. Customer and order data stay out of this integration.
    includes = (
        "resource,service,sub_bookings,sub_bookings.resource,"
        "sub_bookings.service,super_booking"
    )
    return http_json("GET", f"/bookings/{booking_id}?include={includes}")


def patch_booking(booking_id: str, attrs: Dict[str, Any]) -> dict:
    body = {
        "data": {
            "type": "bookings",
            "id": str(booking_id),
            "attributes": attrs,
        }
    }
    return http_json("PATCH", f"/bookings/{booking_id}", body)


# -----------------------------
# DB
# -----------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        # 1) ensure base table exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS allocations (
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
                root_booking_id TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()

        # 2) migrate old DBs (ADD COLUMN) BEFORE creating indexes
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(allocations)").fetchall()]

        if "resource_id" not in cols:
            conn.execute("ALTER TABLE allocations ADD COLUMN resource_id TEXT")
        if "last_patch_hash" not in cols:
            conn.execute("ALTER TABLE allocations ADD COLUMN last_patch_hash TEXT")
        if "patched_at" not in cols:
            conn.execute("ALTER TABLE allocations ADD COLUMN patched_at TEXT")
        if "root_booking_id" not in cols:
            conn.execute("ALTER TABLE allocations ADD COLUMN root_booking_id TEXT")

        conn.commit()

        # 3) indexes last
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alloc_time ON allocations(start_date, end_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alloc_resource ON allocations(resource_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alloc_root_booking ON allocations(root_booking_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                booking_id TEXT,
                processed_at TEXT NOT NULL,
                outcome_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_webhook_events_processed_at ON webhook_events(processed_at)"
        )
        conn.commit()


init_db()


@dataclass
class Allocation:
    booking_id: str
    booking_number: str
    resource_id: str
    service_id: str
    start_date: str
    end_date: str
    need: int
    tables: List[str]
    status: str
    last_patch_hash: str = ""
    patched_at: str = ""
    root_booking_id: str = ""


def get_allocation(booking_id: str) -> Optional[Allocation]:
    with db() as conn:
        row = conn.execute("SELECT * FROM allocations WHERE booking_id=?", (str(booking_id),)).fetchone()
        if not row:
            return None
        return Allocation(
            booking_id=row["booking_id"],
            booking_number=row["booking_number"] or "",
            resource_id=(row["resource_id"] or ""),
            service_id=row["service_id"] or "",
            start_date=row["start_date"],
            end_date=row["end_date"],
            need=int(row["need"] or 0),
            tables=(row["tables_csv"].split(",") if row["tables_csv"] else []),
            status=row["status"] or "assigned",
            last_patch_hash=(row["last_patch_hash"] or ""),
            patched_at=(row["patched_at"] or ""),
            root_booking_id=(row["root_booking_id"] or ""),
        )


def list_family_allocations(root_booking_id: str) -> List[Allocation]:
    with db() as conn:
        rows = conn.execute(
            "SELECT booking_id FROM allocations WHERE root_booking_id=? OR booking_id=?",
            (str(root_booking_id), str(root_booking_id)),
        ).fetchall()
    return [allocation for row in rows if (allocation := get_allocation(row["booking_id"]))]


def upsert_allocation(a: Allocation):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO allocations (
              booking_id, booking_number, resource_id, service_id, start_date, end_date, need, tables_csv, status,
              last_patch_hash, patched_at, root_booking_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(booking_id) DO UPDATE SET
                booking_number=excluded.booking_number,
                resource_id=excluded.resource_id,
                service_id=excluded.service_id,
                start_date=excluded.start_date,
                end_date=excluded.end_date,
                need=excluded.need,
                tables_csv=excluded.tables_csv,
                status=excluded.status,
                last_patch_hash=excluded.last_patch_hash,
                patched_at=excluded.patched_at,
                root_booking_id=excluded.root_booking_id,
                updated_at=excluded.updated_at
            """,
            (
                a.booking_id,
                a.booking_number,
                a.resource_id,
                a.service_id,
                a.start_date,
                a.end_date,
                a.need,
                ",".join(a.tables),
                a.status,
                a.last_patch_hash or "",
                a.patched_at or "",
                a.root_booking_id or a.booking_id,
                iso_now(),
                iso_now(),
            ),
        )
        conn.commit()


def touch_patch_meta(booking_id: str, patch_hash: str):
    with db() as conn:
        conn.execute(
            "UPDATE allocations SET last_patch_hash=?, patched_at=?, updated_at=? WHERE booking_id=?",
            (patch_hash, iso_now(), iso_now(), str(booking_id)),
        )
        conn.commit()


def delete_allocation(booking_id: str):
    with db() as conn:
        conn.execute("DELETE FROM allocations WHERE booking_id=?", (str(booking_id),))
        conn.commit()


def delete_family_allocations(root_booking_id: str):
    with db() as conn:
        conn.execute(
            "DELETE FROM allocations WHERE root_booking_id=? OR booking_id=?",
            (str(root_booking_id), str(root_booking_id)),
        )
        conn.commit()


def get_processed_webhook_event(event_id: str) -> Optional[Dict[str, Any]]:
    if not event_id:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT event_type, booking_id, processed_at, outcome_json FROM webhook_events WHERE event_id=?",
            (str(event_id),),
        ).fetchone()
    if not row:
        return None
    try:
        outcome = json.loads(row["outcome_json"] or "{}")
    except Exception:
        outcome = {}
    return {
        "event_id": str(event_id),
        "event_type": row["event_type"],
        "booking_id": row["booking_id"] or "",
        "processed_at": row["processed_at"],
        "outcome": outcome,
    }


def record_processed_webhook_event(
    event_id: str,
    event_type: str,
    booking_id: str,
    outcome: Dict[str, Any],
) -> None:
    if not event_id:
        return
    with db() as conn:
        conn.execute(
            """
            INSERT INTO webhook_events (
                event_id, event_type, booking_id, processed_at, outcome_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                event_type=excluded.event_type,
                booking_id=excluded.booking_id,
                processed_at=excluded.processed_at,
                outcome_json=excluded.outcome_json
            """,
            (
                str(event_id),
                str(event_type),
                str(booking_id or ""),
                iso_now(),
                json.dumps(outcome, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.execute(
            "DELETE FROM webhook_events WHERE julianday(processed_at) < julianday('now', ?)",
            (f"-{WEBHOOK_EVENT_RETENTION_DAYS} days",),
        )
        conn.commit()


def list_overlapping_allocations(
    window_start: datetime,
    window_end: datetime,
    resource_id: str,
    exclude_booking_id: Optional[str] = None,
) -> List[Allocation]:
    # Note: we consider only assigned allocations for busy-map
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM allocations WHERE status='assigned' AND (resource_id=? OR resource_id IS NULL OR resource_id='')",
            (resource_id,),
        ).fetchall()

    out: List[Allocation] = []
    for r in rows:
        if exclude_booking_id is not None and str(r["booking_id"]) == str(exclude_booking_id):
            continue
        try:
            s = parse_iso(r["start_date"])
            e = parse_iso(r["end_date"])
        except Exception:
            continue
        if overlaps(s, e, window_start, window_end):
            out.append(
                Allocation(
                    booking_id=r["booking_id"],
                    booking_number=r["booking_number"] or "",
                    resource_id=(r["resource_id"] or ""),
                    service_id=r["service_id"] or "",
                    start_date=r["start_date"],
                    end_date=r["end_date"],
                    need=int(r["need"] or 0),
                    tables=(r["tables_csv"].split(",") if r["tables_csv"] else []),
                    status=r["status"] or "assigned",
                    last_patch_hash=(r["last_patch_hash"] or ""),
                    patched_at=(r["patched_at"] or ""),
                    root_booking_id=(r["root_booking_id"] or ""),
                )
            )
    return out


def list_overlapping_unassigned_booking_ids(
    window_start: datetime,
    window_end: datetime,
    resource_id: str,
    exclude_booking_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[str]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT booking_id, start_date, end_date, created_at
            FROM allocations
            WHERE status='unassigned' AND (resource_id=? OR resource_id IS NULL OR resource_id='')
            ORDER BY COALESCE(created_at, ''), start_date, booking_id
            """,
            (resource_id,),
        ).fetchall()

    booking_ids: List[str] = []
    for row in rows:
        if exclude_booking_id is not None and str(row["booking_id"]) == str(exclude_booking_id):
            continue
        try:
            start = parse_iso(row["start_date"])
            end = parse_iso(row["end_date"])
        except Exception:
            continue
        if overlaps(start, end, window_start, window_end):
            booking_ids.append(str(row["booking_id"]))
        if limit is not None and len(booking_ids) >= limit:
            break
    return booking_ids


# -----------------------------
# Allocation logic
# -----------------------------
def pick_adjacent_group(need: int, busy: Dict[str, bool]) -> Optional[List[str]]:
    """Adjacent-first (best case)"""
    for i in range(0, len(TABLES) - need + 1):
        group = TABLES[i: i + need]
        if all(not busy[t] for t in group):
            return group
    return None


def pick_any_free_group(need: int, busy: Dict[str, bool]) -> Optional[List[str]]:
    """Fallback: any free tables in order (not necessarily adjacent)."""
    free = [t for t in TABLES if not busy.get(t, False)]
    if len(free) < need:
        return None
    return free[:need]


def build_busy_map(
    window_start: datetime,
    window_end: datetime,
    resource_id: str,
    exclude_booking_id: Optional[str] = None,
) -> Dict[str, bool]:
    busy = {table: False for table in TABLES}
    overlapping = list_overlapping_allocations(
        window_start,
        window_end,
        resource_id=resource_id,
        exclude_booking_id=exclude_booking_id,
    )
    for allocation in overlapping:
        for table in allocation.tables:
            if table in busy:
                busy[table] = True
    return busy


def choose_group(need: int, busy: Dict[str, bool]) -> Tuple[Optional[List[str]], str, bool]:
    group = pick_adjacent_group(need, busy)
    if group:
        return group, "adjacent", False

    group = pick_any_free_group(need, busy)
    if group:
        return group, "any_free", True

    return None, "unassigned", False


def tables_are_split(tables: List[str]) -> bool:
    """Return whether an assigned group is non-contiguous in TABLE_LABELS order."""
    if len(tables) < 2:
        return False
    try:
        positions = [TABLES.index(table) for table in tables]
    except ValueError:
        return True
    return positions != list(range(positions[0], positions[0] + len(positions)))


def compute_need(booking_weight: Optional[int]) -> int:
    # For "single table" services weight may be missing; default is 1
    if booking_weight is not None:
        try:
            w = int(booking_weight)
            if 1 <= w <= len(TABLES):
                return w
        except Exception:
            pass
    return 1


def managed_description(original: str, message: str) -> str:
    """Replace only our leading description segment and preserve staff text."""
    remainder = (original or "").strip()
    if remainder.startswith(MARKER):
        _managed, separator, staff_text = remainder.partition(" — ")
        remainder = staff_text.strip() if separator else ""
    return f"{message} — {remainder}" if remainder else message


def desired_patch_fields(tables: List[str], current_description: str, split: bool) -> Dict[str, str]:
    if len(tables) == 0:
        label = ""
    elif len(tables) == 2:
        label = " & ".join(tables)
    else:
        label = ", ".join(tables)

    msg = f"{MARKER} {label}".strip()

    new_desc = managed_description(current_description, msg)

    # Optional hint for staff when fallback used (split seating)
    note_suffix = " (Split)" if split and label else ""

    return {
        "customer_note": f"Deine Tische: {label}".strip(),
        "note": f"{NOTE_PREFIX} {label}{note_suffix}".strip(),
        "description": new_desc.strip(),
    }


def patch_hash(fields: Dict[str, str]) -> str:
    raw = json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def patch_if_needed(booking_id: str, current_attrs: Dict[str, Any], fields: Dict[str, str]) -> Dict[str, Any]:
    need_patch = any((current_attrs.get(k) or "") != v for k, v in fields.items())
    h = patch_hash(fields)

    if not need_patch:
        touch_patch_meta(booking_id, h)
        return {"ok": True, "skipped": True, "reason": "NO_OP_PATCH", "hash": h}

    res = patch_booking(str(booking_id), fields)
    if isinstance(res, dict) and res.get("errors"):
        return {
            "ok": False,
            "patched": False,
            "retryable": True,
            "reason": "ANNY_PATCH_FAILED",
            "hash": h,
            "errors": res.get("errors") or [],
        }
    touch_patch_meta(booking_id, h)
    return {"ok": True, "patched": True, "hash": h, "response": res}


def patch_result_or_retryable_failure(
    result: Dict[str, Any],
    patch_result: Dict[str, Any],
) -> Dict[str, Any]:
    result["patch"] = patch_result
    if patch_result.get("ok"):
        return result
    result.update(
        {
            "ok": False,
            "reason": "ANNY_PATCH_FAILED",
            "retryable": True,
        }
    )
    return result


def is_booking_canceled(attrs: Dict[str, Any]) -> Tuple[bool, str, Any]:
    status = str(attrs.get("status") or "").lower().strip()
    canceled_at = attrs.get("canceled_at")
    # Treat these as cancellation-like states
    is_c = bool(canceled_at) or status in (
        "canceled", "cancelled", "rejected", "declined", "denied", "void", "refunded"
    )
    return is_c, status, canceled_at


def response_is_not_found(response: Dict[str, Any]) -> bool:
    for error in response.get("errors") or []:
        if str(error.get("status") or "") == "404":
            return True
    return False


def cleanup_stale_overlapping_allocations(
    window_start: datetime,
    window_end: datetime,
    resource_id: str,
    exclude_booking_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Remove confirmed canceled/deleted blockers before declaring a capacity failure.

    This intentionally runs only after the local allocation map has no room. It
    makes missed cancellation webhooks self-healing without adding Anny API
    traffic to every normal booking. Unknown API failures remain fail-closed.
    """
    candidates = list_overlapping_allocations(
        window_start,
        window_end,
        resource_id=resource_id,
        exclude_booking_id=exclude_booking_id,
    )
    removed: List[Dict[str, str]] = []
    api_errors: List[Dict[str, Any]] = []

    for allocation in candidates:
        booking = fetch_booking(allocation.booking_id)
        if "errors" in booking:
            if response_is_not_found(booking):
                delete_allocation(allocation.booking_id)
                removed.append({"booking_id": allocation.booking_id, "reason": "BOOKING_NOT_FOUND"})
            else:
                api_errors.append({"booking_id": allocation.booking_id, "errors": booking.get("errors") or []})
                # A general Anny outage would otherwise multiply the request
                # timeout by every occupied table. Keep all remaining rows
                # blocked and stop this best-effort reconciliation early.
                break
            continue

        attrs = (booking.get("data") or {}).get("attributes") or {}
        canceled, status, _ = is_booking_canceled(attrs)
        if canceled:
            delete_allocation(allocation.booking_id)
            removed.append(
                {
                    "booking_id": allocation.booking_id,
                    "reason": "BOOKING_CANCELED",
                    "status": status,
                }
            )

    return {
        "attempted": True,
        "checked": len(candidates),
        "removed": removed,
        "removed_count": len(removed),
        "api_errors": api_errors,
        "api_error_count": len(api_errors),
    }


def _ensure_allocation_for_booking(
    booking_id: str,
    event: str,
    booking_json: Optional[Dict[str, Any]] = None,
    perform_patch: bool = True,
    root_booking_id: str = "",
) -> Dict[str, Any]:
    existing = get_allocation(str(booking_id))
    bj = booking_json if booking_json is not None else fetch_booking(str(booking_id))
    if "errors" in bj:
        if response_is_not_found(bj):
            delete_allocation(str(booking_id))
            return {
                "ok": True,
                "skipped": True,
                "reason": "BOOKING_NOT_FOUND_DB_CLEANED",
                "booking_id": str(booking_id),
                "allocation_removed": existing is not None,
            }
        return {
            "ok": False,
            "reason": "FETCH_BOOKING_FAILED",
            "retryable": True,
            "errors": bj["errors"],
        }

    data = bj.get("data") or {}
    attrs = data.get("attributes") or {}
    rel = data.get("relationships") or {}

    service_id = str((rel.get("service", {}).get("data") or {}).get("id") or "")
    resource_id = str((rel.get("resource", {}).get("data") or {}).get("id") or "")
    booking_number = str(attrs.get("number") or "")
    start_date = str(attrs.get("start_date") or "")
    end_date = str(attrs.get("end_date") or "")
    weight = attrs.get("weight")
    description = str(attrs.get("description") or "")

    if not resource_id:
        return {"ok": False, "reason": "NO_RESOURCE_ID", "retryable": True}

    # RESOURCE FILTER (production-safe)
    if ALLOCATE_RESOURCE_IDS and resource_id not in ALLOCATE_RESOURCE_IDS:
        if existing:
            delete_allocation(str(booking_id))
        dprint(f"ignore booking_id={booking_id} resource_id={resource_id} service_id={service_id}")
        return {
            "ok": True,
            "ignored": True,
            "booking_id": str(booking_id),
            "resource_id": resource_id,
            "service_id": service_id,
            "allocation_removed": existing is not None,
        }

    # --- NEW: Cancellation cleanup ---
    canceled, status, canceled_at = is_booking_canceled(attrs)
    if canceled:
        delete_allocation(str(booking_id))
        return {
            "ok": True,
            "skipped": True,
            "reason": "BOOKING_CANCELED_DB_CLEANED",
            "booking_id": str(booking_id),
            "booking_number": booking_number,
            "resource_id": resource_id,
            "service_id": service_id,
            "status": status,
            "canceled_at": canceled_at,
        }
    # -------------------------------

    if not start_date or not end_date:
        return {"ok": False, "reason": "MISSING_DATES", "retryable": True}

    need = compute_need(weight)
    try:
        window_start = parse_iso(start_date)
        window_end = parse_iso(end_date)
    except Exception:
        return {"ok": False, "reason": "INVALID_DATES", "retryable": True}

    # Reuse allocation if unchanged
    if existing and existing.status == "assigned":
        try:
            ex_s = parse_iso(existing.start_date)
            ex_e = parse_iso(existing.end_date)
        except Exception:
            ex_s, ex_e = window_start, window_end

        if ex_s == window_start and ex_e == window_end and existing.need == need and existing.tables:
            if root_booking_id and existing.root_booking_id != root_booking_id:
                existing.root_booking_id = root_booking_id
                upsert_allocation(existing)
            if not perform_patch:
                return {
                    "ok": True,
                    "booking_id": str(booking_id),
                    "booking_number": booking_number,
                    "resource_id": resource_id,
                    "service_id": service_id,
                    "need": need,
                    "tables": existing.tables,
                    "reused": True,
                    "mode": "reused",
                    "patch_deferred": True,
                }
            fields = desired_patch_fields(
                existing.tables,
                description,
                split=tables_are_split(existing.tables),
            )
            patch_res = patch_if_needed(str(booking_id), attrs, fields)
            return patch_result_or_retryable_failure({
                "ok": True,
                "booking_id": str(booking_id),
                "booking_number": booking_number,
                "resource_id": resource_id,
                "service_id": service_id,
                "need": need,
                "tables": existing.tables,
                "reused": True,
                "mode": "reused",
            }, patch_res)

    # Build busy map from OUR allocations. Never let an older allocation for
    # the same booking block its own reallocation.
    busy = build_busy_map(
        window_start,
        window_end,
        resource_id=resource_id,
        exclude_booking_id=str(booking_id),
    )
    group, mode, split = choose_group(need, busy)

    reconciliation: Dict[str, Any] = {
        "attempted": False,
        "checked": 0,
        "removed": [],
        "removed_count": 0,
        "api_errors": [],
        "api_error_count": 0,
    }

    # If SQLite says "full", verify the blocking bookings against Anny before
    # marking the new booking unassigned. This repairs missed cancellation or
    # deletion webhooks at the exact moment their stale rows would cause harm.
    if not group:
        reconciliation = cleanup_stale_overlapping_allocations(
            window_start,
            window_end,
            resource_id=resource_id,
            exclude_booking_id=str(booking_id),
        )
        if reconciliation["removed_count"]:
            busy = build_busy_map(
                window_start,
                window_end,
                resource_id=resource_id,
                exclude_booking_id=str(booking_id),
            )
            group, mode, split = choose_group(need, busy)

    # 3) if still none -> truly not enough free tables
    if not group:
        warn = f"{MARKER} Keine freien {need} Tische verfügbar (bitte manuell zuweisen)."
        upsert_allocation(
            Allocation(
                booking_id=str(booking_id),
                booking_number=booking_number,
                resource_id=resource_id,
                service_id=service_id,
                start_date=start_date,
                end_date=end_date,
                need=need,
                tables=[],
                status="unassigned",
                root_booking_id=root_booking_id or str(booking_id),
            )
        )
        result = {
            "ok": False,
            "reason": "NOT_ENOUGH_FREE_TABLES",
            "capacity_reason": "NOT_ENOUGH_FREE_TABLES",
            "retryable": False,
            "booking_id": str(booking_id),
            "booking_number": booking_number,
            "resource_id": resource_id,
            "service_id": service_id,
            "need": need,
            "busy": busy,
            "reconciliation": reconciliation,
        }
        if not perform_patch:
            result["patch_deferred"] = True
            return result
        patch_res = patch_if_needed(
            str(booking_id),
            attrs,
            {
                "customer_note": warn,
                "note": warn,
                "description": managed_description(description, warn),
            },
        )
        return patch_result_or_retryable_failure(result, patch_res)

    # Persist allocation
    upsert_allocation(
        Allocation(
            booking_id=str(booking_id),
            booking_number=booking_number,
            resource_id=resource_id,
            service_id=service_id,
            start_date=start_date,
            end_date=end_date,
            need=need,
            tables=group,
            status="assigned",
            root_booking_id=root_booking_id or str(booking_id),
        )
    )

    result = {
        "ok": True,
        "booking_id": str(booking_id),
        "booking_number": booking_number,
        "resource_id": resource_id,
        "service_id": service_id,
        "need": need,
        "tables": group,
        "mode": mode,
        "reconciliation": reconciliation,
    }
    if not perform_patch:
        result["patch_deferred"] = True
        return result

    fields = desired_patch_fields(group, description, split=split)
    patch_res = patch_if_needed(str(booking_id), attrs, fields)
    result = patch_result_or_retryable_failure(result, patch_res)
    if not patch_res.get("ok") and (not existing or existing.status != "assigned"):
        # A brand-new/retried allocation is not acknowledged until Anny also
        # contains the table note. Keeping it unassigned lets the same event or
        # a pending redistribution retry safely without blocking the table.
        upsert_allocation(
            Allocation(
                booking_id=str(booking_id),
                booking_number=booking_number,
                resource_id=resource_id,
                service_id=service_id,
                start_date=start_date,
                end_date=end_date,
                need=need,
                tables=[],
                status="unassigned",
                root_booking_id=root_booking_id or str(booking_id),
            )
        )
        result["allocation_rolled_back"] = True
    return result


def relationship_id(data: Dict[str, Any], name: str) -> str:
    relationship = ((data.get("relationships") or {}).get(name) or {}).get("data")
    if isinstance(relationship, dict):
        return str(relationship.get("id") or "")
    return ""


def relationship_ids(data: Dict[str, Any], name: str) -> List[str]:
    relationship = ((data.get("relationships") or {}).get(name) or {}).get("data")
    if not isinstance(relationship, list):
        return []
    return [str(item.get("id")) for item in relationship if isinstance(item, dict) and item.get("id")]


def included_bookings(response: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in response.get("included") or []
        if isinstance(item, dict) and item.get("type") == "bookings" and item.get("id")
    }


def allocation_capacity_keys(allocations: List[Allocation]) -> set:
    return {
        (allocation.resource_id, allocation.start_date, allocation.end_date, table)
        for allocation in allocations
        if allocation.status == "assigned"
        for table in allocation.tables
    }


def released_family_windows(
    before: List[Allocation],
    after: List[Allocation],
) -> List[Dict[str, str]]:
    released = allocation_capacity_keys(before) - allocation_capacity_keys(after)
    windows = {
        (resource_id, start_date, end_date)
        for resource_id, start_date, end_date, _table in released
        if resource_id and start_date and end_date
    }
    return [
        {
            "resource_id": resource_id,
            "window_start": start_date,
            "window_end": end_date,
        }
        for resource_id, start_date, end_date in sorted(windows)
    ]


def rollback_deferred_family_allocations(
    member_ids: List[str],
    previous_by_id: Dict[str, Allocation],
    root_booking_id: str,
) -> None:
    """Undo capacity that was never confirmed on the Anny main booking."""
    for member_id in member_ids:
        previous = previous_by_id.get(member_id)
        if previous and previous.status == "assigned" and previous.tables:
            upsert_allocation(previous)
            continue
        current = get_allocation(member_id)
        if current:
            current.tables = []
            current.status = "unassigned"
            current.root_booking_id = root_booking_id
            upsert_allocation(current)


def _ensure_family_allocation(
    root_booking_id: str,
    root_response: Dict[str, Any],
    trigger_booking_id: str,
    event: str,
) -> Dict[str, Any]:
    """Allocate an Anny main booking and its optional resources as one family.

    Anny models each optional resource as a sub-booking. Allocations remain one
    SQLite row per booking for traceability, while the main booking is patched
    first and exactly once with the complete table list used in confirmations.
    """
    root_data = root_response.get("data") or {}
    root_attrs = root_data.get("attributes") or {}
    root_canceled, root_status, root_canceled_at = is_booking_canceled(root_attrs)
    before_family = list_family_allocations(root_booking_id)

    if root_canceled:
        delete_family_allocations(root_booking_id)
        return {
            "ok": True,
            "skipped": True,
            "reason": "BOOKING_FAMILY_CANCELED_DB_CLEANED",
            "booking_id": root_booking_id,
            "trigger_booking_id": trigger_booking_id,
            "status": root_status,
            "canceled_at": root_canceled_at,
            "family": True,
            "family_size": len(before_family),
            "family_released_windows": released_family_windows(before_family, []),
        }

    sub_booking_ids = relationship_ids(root_data, "sub_bookings")
    member_ids = [root_booking_id] + [
        booking_id for booking_id in sub_booking_ids if booking_id != root_booking_id
    ]
    included = included_bookings(root_response)
    member_responses: Dict[str, Dict[str, Any]] = {root_booking_id: root_response}

    # Resolve the complete family before changing SQLite. The nested includes
    # normally make this a single request; the fallback keeps the code robust
    # if Anny omits one included record temporarily.
    for member_id in member_ids[1:]:
        if member_id in included:
            member_responses[member_id] = {"data": included[member_id]}
            continue
        response = fetch_booking(member_id)
        if response.get("errors"):
            if response_is_not_found(response):
                delete_allocation(member_id)
                continue
            return {
                "ok": False,
                "reason": "FETCH_FAMILY_MEMBER_FAILED",
                "retryable": True,
                "booking_id": root_booking_id,
                "trigger_booking_id": trigger_booking_id,
                "family": True,
                "failed_member_id": member_id,
                "errors": response.get("errors") or [],
            }
        member_responses[member_id] = response

    member_ids = [member_id for member_id in member_ids if member_id in member_responses]
    active_ids = set(member_ids)
    for stale in before_family:
        if stale.booking_id not in active_ids:
            delete_allocation(stale.booking_id)

    previous_by_id = {allocation.booking_id: allocation for allocation in before_family}
    member_results: List[Dict[str, Any]] = []
    managed_ids: List[str] = []
    processed_ids: List[str] = []

    for member_id in member_ids:
        member_result = _ensure_allocation_for_booking(
            member_id,
            event=event,
            booking_json=member_responses[member_id],
            perform_patch=False,
            root_booking_id=root_booking_id,
        )
        member_results.append(member_result)
        processed_ids.append(member_id)
        if member_result.get("retryable"):
            rollback_deferred_family_allocations(
                processed_ids,
                previous_by_id,
                root_booking_id,
            )
            return {
                "ok": False,
                "reason": str(member_result.get("reason") or "FAMILY_MEMBER_FAILED"),
                "retryable": True,
                "booking_id": root_booking_id,
                "trigger_booking_id": trigger_booking_id,
                "family": True,
                "members": member_results,
            }
        if not member_result.get("ignored") and member_result.get("need") is not None:
            managed_ids.append(member_id)

    allocations_by_id = {
        member_id: allocation
        for member_id in managed_ids
        if (allocation := get_allocation(member_id)) is not None
    }
    assigned_ids = [
        member_id
        for member_id in managed_ids
        if allocations_by_id.get(member_id)
        and allocations_by_id[member_id].status == "assigned"
        and allocations_by_id[member_id].tables
    ]
    all_assigned = bool(managed_ids) and len(assigned_ids) == len(managed_ids)
    tables = [
        table
        for member_id in managed_ids
        if member_id in allocations_by_id
        for table in allocations_by_id[member_id].tables
    ]
    total_need = sum(
        int(result.get("need") or 0)
        for result in member_results
        if not result.get("ignored")
    )

    if not managed_ids:
        return {
            "ok": True,
            "ignored": True,
            "booking_id": root_booking_id,
            "trigger_booking_id": trigger_booking_id,
            "family": True,
            "family_size": len(member_ids),
            "members": member_results,
        }

    if all_assigned:
        fields = desired_patch_fields(
            tables,
            str(root_attrs.get("description") or ""),
            split=tables_are_split(tables),
        )
    else:
        warning = f"{MARKER} Keine freien {total_need} Tische verfügbar (bitte manuell zuweisen)."
        fields = {
            "customer_note": warning,
            "note": warning,
            "description": managed_description(str(root_attrs.get("description") or ""), warning),
        }

    # Patch the customer-visible main booking before its technical
    # sub-bookings. This prevents a confirmation from seeing only the first
    # table when all family members arrived in the same webhook cycle.
    root_patch = patch_if_needed(root_booking_id, root_attrs, fields)
    result: Dict[str, Any] = {
        "ok": all_assigned,
        "booking_id": root_booking_id,
        "booking_number": str(root_attrs.get("number") or ""),
        "trigger_booking_id": trigger_booking_id,
        "family": True,
        "family_size": len(member_ids),
        "managed_family_size": len(managed_ids),
        "need": total_need,
        "tables": tables,
        "members": member_results,
        "patch": root_patch,
    }

    if not root_patch.get("ok"):
        # Mirror the single-booking fail-safe: newly acknowledged capacity is
        # not allowed to block tables until the main Anny booking contains the
        # full assignment. Existing confirmed allocations remain intact.
        rollback_deferred_family_allocations(
            managed_ids,
            previous_by_id,
            root_booking_id,
        )
        result.update(
            {
                "ok": False,
                "reason": "ANNY_PATCH_FAILED",
                "retryable": True,
                "allocation_rolled_back": True,
            }
        )
        result["family_released_windows"] = released_family_windows(
            before_family,
            list_family_allocations(root_booking_id),
        )
        return result

    child_patches: List[Dict[str, Any]] = []
    if all_assigned:
        for child_id in managed_ids:
            if child_id == root_booking_id:
                continue
            child_allocation = allocations_by_id[child_id]
            child_attrs = (member_responses[child_id].get("data") or {}).get("attributes") or {}
            child_fields = desired_patch_fields(
                child_allocation.tables,
                str(child_attrs.get("description") or ""),
                split=tables_are_split(child_allocation.tables),
            )
            child_patch = patch_if_needed(child_id, child_attrs, child_fields)
            child_patches.append({"booking_id": child_id, "patch": child_patch})
            if not child_patch.get("ok"):
                result.update(
                    {
                        "ok": False,
                        "reason": "ANNY_SUB_BOOKING_PATCH_FAILED",
                        "retryable": True,
                    }
                )
                break
    else:
        result.update(
            {
                "reason": "NOT_ENOUGH_FREE_TABLES_FOR_FAMILY",
                "capacity_reason": "NOT_ENOUGH_FREE_TABLES",
                "retryable": False,
            }
        )

    result["child_patches"] = child_patches
    result["family_released_windows"] = released_family_windows(
        before_family,
        list_family_allocations(root_booking_id),
    )
    return result


def _ensure_booking_or_family(booking_id: str, event: str) -> Dict[str, Any]:
    booking_id = str(booking_id)
    response = fetch_booking(booking_id)
    if response.get("errors"):
        return _ensure_allocation_for_booking(
            booking_id,
            event,
            booking_json=response,
        )

    data = response.get("data") or {}
    attrs = data.get("attributes") or {}
    super_booking_id = relationship_id(data, "super_booking")
    root_booking_id = super_booking_id or booking_id
    root_response = response
    if super_booking_id:
        root_response = fetch_booking(root_booking_id)
        if root_response.get("errors"):
            return {
                "ok": False,
                "reason": "FETCH_SUPER_BOOKING_FAILED",
                "retryable": True,
                "booking_id": booking_id,
                "root_booking_id": root_booking_id,
                "errors": root_response.get("errors") or [],
            }

    root_data = root_response.get("data") or {}
    sub_booking_ids = relationship_ids(root_data, "sub_bookings")
    known_family = list_family_allocations(root_booking_id)
    is_family = bool(
        super_booking_id
        or attrs.get("is_sub_booking")
        or sub_booking_ids
        or len(known_family) > 1
    )
    if not is_family:
        return _ensure_allocation_for_booking(
            booking_id,
            event,
            booking_json=response,
            root_booking_id=booking_id,
        )

    return _ensure_family_allocation(
        root_booking_id,
        root_response,
        trigger_booking_id=booking_id,
        event=event,
    )


def ensure_allocation_for_booking(booking_id: str, event: str) -> Dict[str, Any]:
    with ALLOCATION_LOCK:
        return _ensure_booking_or_family(booking_id, event)


def allocation_released_capacity(before: Optional[Allocation], after: Optional[Allocation]) -> bool:
    if not before or before.status != "assigned" or not before.tables:
        return False
    if not after or after.status != "assigned" or not after.tables:
        return True
    return (
        before.resource_id != after.resource_id
        or before.start_date != after.start_date
        or before.end_date != after.end_date
        or before.need != after.need
        or before.tables != after.tables
    )


def redistribute_unassigned(
    window_start: datetime,
    window_end: datetime,
    resource_id: str,
    exclude_booking_id: Optional[str] = None,
) -> Dict[str, Any]:
    candidate_ids = list_overlapping_unassigned_booking_ids(
        window_start,
        window_end,
        resource_id=resource_id,
        exclude_booking_id=exclude_booking_id,
        limit=REDISTRIBUTION_LIMIT,
    )
    summary: Dict[str, Any] = {
        "attempted": bool(candidate_ids),
        "checked": 0,
        "assigned": [],
        "still_unassigned": [],
        "removed": [],
        "errors": [],
        "limit": REDISTRIBUTION_LIMIT,
    }

    for candidate_id in candidate_ids:
        summary["checked"] += 1
        result = _ensure_booking_or_family(candidate_id, event="internal.redistribution")
        current = get_allocation(candidate_id)
        booking_number = str(result.get("booking_number") or (current.booking_number if current else ""))
        if result.get("retryable"):
            summary["errors"].append(
                {
                    "booking_number": booking_number,
                    "reason": str(result.get("reason") or "UNKNOWN_ERROR"),
                }
            )
        if current is None:
            summary["removed"].append(booking_number or candidate_id)
        elif current.status == "assigned" and current.tables:
            summary["assigned"].append(
                {
                    "booking_number": current.booking_number,
                    "tables": current.tables,
                }
            )
        else:
            summary["still_unassigned"].append(current.booking_number or candidate_id)
        if result.get("retryable"):
            # Avoid multiplying an Anny outage by every waiting booking. The
            # failed item remains visible in the dashboard and can be retried
            # by the documented webhook delivery retry.
            break

    summary["assigned_count"] = len(summary["assigned"])
    summary["still_unassigned_count"] = len(summary["still_unassigned"])
    summary["removed_count"] = len(summary["removed"])
    summary["error_count"] = len(summary["errors"])
    return summary


def process_booking_event(
    event: str,
    booking_id: str,
    retry_windows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Apply one Anny booking event and redistribute only released capacity."""
    with ALLOCATION_LOCK:
        before = get_allocation(booking_id)

        if event == "bookings.deleted":
            root_booking_id = before.root_booking_id if before else ""
            if root_booking_id and root_booking_id != booking_id:
                result = _ensure_booking_or_family(
                    root_booking_id,
                    event="internal.family_member_deleted",
                )
                if result.get("reason") == "BOOKING_NOT_FOUND_DB_CLEANED":
                    delete_family_allocations(root_booking_id)
                result.update(
                    {
                        "event": event,
                        "deleted_booking_id": booking_id,
                        "deleted": before is not None,
                    }
                )
            else:
                if root_booking_id == booking_id:
                    delete_family_allocations(booking_id)
                else:
                    delete_allocation(booking_id)
                result = {
                    "ok": True,
                    "event": event,
                    "booking_id": booking_id,
                    "deleted": before is not None,
                }
        else:
            result = _ensure_booking_or_family(booking_id, event=event)
            result["event"] = event

        after = get_allocation(booking_id)
        windows: List[Tuple[datetime, datetime, str]] = []

        if allocation_released_capacity(before, after):
            try:
                windows.append((parse_iso(before.start_date), parse_iso(before.end_date), before.resource_id))
            except Exception:
                pass

        reconciliation = result.get("reconciliation") or {}
        if reconciliation.get("removed_count") and after:
            try:
                windows.append((parse_iso(after.start_date), parse_iso(after.end_date), after.resource_id))
            except Exception:
                pass

        for released_window in result.get("family_released_windows") or []:
            try:
                windows.append(
                    (
                        parse_iso(str(released_window["window_start"])),
                        parse_iso(str(released_window["window_end"])),
                        str(released_window["resource_id"]),
                    )
                )
            except Exception:
                continue

        for retry_window in retry_windows or []:
            if not retry_window.get("error_count"):
                continue
            try:
                windows.append(
                    (
                        parse_iso(str(retry_window["window_start"])),
                        parse_iso(str(retry_window["window_end"])),
                        str(retry_window["resource_id"]),
                    )
                )
            except Exception:
                continue

        seen_windows = set()
        redistributions: List[Dict[str, Any]] = []
        for window_start, window_end, resource_id in windows:
            key = (window_start.isoformat(), window_end.isoformat(), resource_id)
            if not resource_id or key in seen_windows:
                continue
            seen_windows.add(key)
            summary = redistribute_unassigned(
                window_start,
                window_end,
                resource_id=resource_id,
                exclude_booking_id=booking_id,
            )
            summary.update(
                {
                    "resource_id": resource_id,
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                }
            )
            redistributions.append(summary)

        result["redistribution"] = {
            "triggered": bool(redistributions),
            "windows": redistributions,
            "assigned_count": sum(item["assigned_count"] for item in redistributions),
            "error_count": sum(item["error_count"] for item in redistributions),
        }
        if result["redistribution"]["error_count"]:
            result["retryable"] = True
            result["retry_reason"] = "REDISTRIBUTION_FAILED"
        return result


# -----------------------------
# Webhook parsing + auth
# -----------------------------
def extract_event_and_booking_id(payload: Any, headers_lower: Dict[str, str]) -> Tuple[str, Optional[str]]:
    event = (
        headers_lower.get("x-anny-event")
        or headers_lower.get("x-event")
        or headers_lower.get("x-webhook-event")
        or ""
    ).strip()

    booking_id: Optional[str] = None
    if isinstance(payload, dict):
        event = str(payload.get("event") or payload.get("type") or event or "").strip()
        booking_id = payload.get("booking_id") or payload.get("bookingId")

        if not booking_id:
            d = payload.get("data")
            if isinstance(d, dict):
                if d.get("type") in ("bookings", "booking") and d.get("id") is not None:
                    booking_id = str(d.get("id"))
                if not booking_id and isinstance(d.get("data"), dict):
                    inner = d["data"]
                    if inner.get("type") in ("bookings", "booking") and inner.get("id") is not None:
                        booking_id = str(inner.get("id"))
                if not booking_id and isinstance(d.get("booking"), dict) and d["booking"].get("id") is not None:
                    booking_id = str(d["booking"]["id"])

        if not booking_id and payload.get("type") in ("bookings", "booking") and payload.get("id") is not None:
            booking_id = str(payload.get("id"))

    if not event:
        event = "bookings.created"
    return event, booking_id


def extract_event_id(payload: Any, headers_lower: Dict[str, str]) -> str:
    if isinstance(payload, dict) and payload.get("event_id"):
        return str(payload.get("event_id")).strip()
    return str(headers_lower.get("x-anny-event-id") or "").strip()


async def read_payload(req: Request) -> Any:
    try:
        return await req.json()
    except Exception:
        try:
            raw = await req.body()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            return {}


def check_webhook_auth(req: Request) -> Optional[JSONResponse]:
    if not WEBHOOK_SECRET:
        return None
    got = req.headers.get("X-Webhook-Secret", "")
    if secrets.compare_digest(got, WEBHOOK_SECRET):
        return None
    key = req.query_params.get("key", "")
    if secrets.compare_digest(key, WEBHOOK_SECRET):
        return None
    return JSONResponse({"ok": False, "reason": "UNAUTHORIZED"}, status_code=401)


def check_dashboard_auth(req: Request) -> Optional[JSONResponse]:
    if not DASHBOARD_USERNAME or not DASHBOARD_PASSWORD:
        return JSONResponse(
            {
                "ok": False,
                "reason": "DASHBOARD_NOT_CONFIGURED",
                "detail": "DASHBOARD_USERNAME und DASHBOARD_PASSWORD müssen gesetzt sein.",
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    authorization = req.headers.get("Authorization", "")
    scheme, separator, encoded = authorization.partition(" ")
    username = ""
    password = ""
    if separator and scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            username, found_separator, password = decoded.partition(":")
            if not found_separator:
                username = ""
                password = ""
        except Exception:
            username = ""
            password = ""

    username_ok = secrets.compare_digest(username, DASHBOARD_USERNAME)
    password_ok = secrets.compare_digest(password, DASHBOARD_PASSWORD)
    if username_ok and password_ok:
        return None

    return JSONResponse(
        {"ok": False, "reason": "UNAUTHORIZED"},
        status_code=401,
        headers={
            "WWW-Authenticate": 'Basic realm="Volta Pong Systemstatus", charset="UTF-8"',
            "Cache-Control": "no-store",
        },
    )


def list_allocation_rows() -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM allocations ORDER BY start_date ASC").fetchall()
    return [{k: row[k] for k in row.keys()} for row in rows]


def normalized_datetime(value: str) -> datetime:
    parsed = parse_iso(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def webhook_activity_snapshot() -> Dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT event_type, processed_at, outcome_json
            FROM webhook_events
            WHERE julianday(processed_at) >= julianday('now', '-1 day')
            ORDER BY processed_at DESC
            LIMIT 200
            """
        ).fetchall()

    retryable_failures = 0
    redistributed = 0
    last_outcome: Dict[str, Any] = {}
    for index, row in enumerate(rows):
        try:
            outcome = json.loads(row["outcome_json"] or "{}")
        except Exception:
            outcome = {}
        if index == 0:
            last_outcome = outcome
        if outcome.get("retryable"):
            retryable_failures += 1
        redistributed += int((outcome.get("redistribution") or {}).get("assigned_count") or 0)

    last = rows[0] if rows else None
    return {
        "events_24h": len(rows),
        "retryable_failures_24h": retryable_failures,
        "redistributed_24h": redistributed,
        "last_event": str(last["event_type"] or "") if last else "",
        "last_event_at": str(last["processed_at"] or "") if last else "",
        "last_result": str(last_outcome.get("reason") or "OK") if last else "",
        "last_ok": bool(last) and not bool(last_outcome.get("retryable")),
    }


def dashboard_snapshot(now: Optional[datetime] = None) -> Dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    raw_rows = list_allocation_rows()
    webhook_activity = webhook_activity_snapshot()
    parsed_rows: List[Dict[str, Any]] = []
    invalid_rows: List[Dict[str, str]] = []

    for row in raw_rows:
        try:
            start = normalized_datetime(str(row.get("start_date") or ""))
            end = normalized_datetime(str(row.get("end_date") or ""))
        except Exception:
            invalid_rows.append(
                {
                    "booking_number": str(row.get("booking_number") or "Unbekannt"),
                    "reason": "Ungültiger Zeitraum",
                }
            )
            continue

        public = {
            "booking_number": str(row.get("booking_number") or "Unbekannt"),
            "resource_id": str(row.get("resource_id") or ""),
            "service_id": str(row.get("service_id") or ""),
            "start_date": str(row.get("start_date") or ""),
            "end_date": str(row.get("end_date") or ""),
            "need": int(row.get("need") or 0),
            "tables": [table for table in str(row.get("tables_csv") or "").split(",") if table],
            "status": str(row.get("status") or "unknown"),
            "updated_at": str(row.get("updated_at") or ""),
        }
        parsed_rows.append({"start": start, "end": end, "public": public})

    active_or_future = [item for item in parsed_rows if item["end"] > current_time]
    current_assigned = [
        item
        for item in active_or_future
        if item["public"]["status"] == "assigned" and item["start"] <= current_time < item["end"]
    ]
    future_unassigned = [item for item in active_or_future if item["public"]["status"] == "unassigned"]

    configured_resources = sorted(ALLOCATE_RESOURCE_IDS)
    observed_resources = sorted(
        {item["public"]["resource_id"] for item in active_or_future if item["public"]["resource_id"]}
    )
    resource_ids = configured_resources or observed_resources
    resource_summaries: List[Dict[str, Any]] = []
    for resource_id in resource_ids:
        occupied = sorted(
            {
                table
                for item in current_assigned
                if item["public"]["resource_id"] == resource_id
                for table in item["public"]["tables"]
            },
            key=lambda table: TABLES.index(table) if table in TABLES else len(TABLES),
        )
        resource_summaries.append(
            {
                "resource_id": resource_id,
                "occupied_tables": occupied,
                "free_tables": [table for table in TABLES if table not in occupied],
                "occupied_count": len(occupied),
                "free_count": max(0, len(TABLES) - len(occupied)),
            }
        )

    collisions: List[Dict[str, Any]] = []
    assigned_active_or_future = [
        item for item in active_or_future if item["public"]["status"] == "assigned"
    ]
    for index, first in enumerate(assigned_active_or_future):
        for second in assigned_active_or_future[index + 1:]:
            first_public = first["public"]
            second_public = second["public"]
            if first_public["resource_id"] != second_public["resource_id"]:
                continue
            if not overlaps(first["start"], first["end"], second["start"], second["end"]):
                continue
            shared_tables = sorted(set(first_public["tables"]) & set(second_public["tables"]))
            if shared_tables:
                collisions.append(
                    {
                        "booking_numbers": [
                            first_public["booking_number"],
                            second_public["booking_number"],
                        ],
                        "tables": shared_tables,
                    }
                )

    if collisions:
        status = "error"
        status_message = "Tischkollision erkannt – bitte sofort prüfen."
    elif webhook_activity["retryable_failures_24h"]:
        status = "warning"
        status_message = "Mindestens ein Anny-Webhook benötigt einen erneuten Zustellversuch."
    elif future_unassigned or invalid_rows:
        status = "warning"
        status_message = "Es gibt offene Zuweisungen oder fehlerhafte Datensätze."
    elif not raw_rows:
        status = "warning"
        status_message = "Noch keine Zuweisungen in der Datenbank."
    else:
        status = "ok"
        status_message = "Alles in Ordnung – aktuell sind keine Konflikte bekannt."

    newest_update = max(
        (str(row.get("updated_at") or "") for row in raw_rows),
        default="",
    )
    primary_resource = resource_summaries[0] if resource_summaries else {
        "resource_id": "",
        "occupied_tables": [],
        "free_tables": list(TABLES),
        "occupied_count": 0,
        "free_count": len(TABLES),
    }
    current_public = [item["public"] for item in sorted(current_assigned, key=lambda item: item["start"])]
    upcoming_public = [
        item["public"]
        for item in sorted(active_or_future, key=lambda item: item["start"])
        if item["start"] > current_time
    ][:30]

    return {
        "ok": True,
        "status": status,
        "status_message": status_message,
        "generated_at": current_time.isoformat(),
        "refresh_seconds": DASHBOARD_REFRESH_SECONDS,
        "summary": {
            "total": len(raw_rows),
            "assigned": sum(1 for row in raw_rows if row.get("status") == "assigned"),
            "unassigned": sum(1 for row in raw_rows if row.get("status") == "unassigned"),
            "active_or_future": len(active_or_future),
            "current_bookings": len(current_assigned),
            "occupied_now": primary_resource["occupied_count"],
            "free_now": primary_resource["free_count"],
            "future_unassigned": len(future_unassigned),
            "collisions": len(collisions),
            "invalid_rows": len(invalid_rows),
            "webhook_events_24h": webhook_activity["events_24h"],
            "webhook_failures_24h": webhook_activity["retryable_failures_24h"],
            "redistributed_24h": webhook_activity["redistributed_24h"],
            "last_update": newest_update,
        },
        "webhook": webhook_activity,
        "resources": resource_summaries,
        "current": current_public,
        "upcoming": upcoming_public,
        "issues": {
            "unassigned": [item["public"] for item in future_unassigned[:20]],
            "collisions": collisions[:20],
            "invalid_rows": invalid_rows[:20],
            "webhook_failures": webhook_activity["retryable_failures_24h"],
        },
        "configuration": {
            "tables": TABLES,
            "resource_ids": configured_resources,
            "handle_updated": HANDLE_UPDATED,
            "capacity_reconciliation": True,
            "automatic_redistribution": True,
            "event_id_idempotency": True,
            "redistribution_limit": REDISTRIBUTION_LIMIT,
        },
    }


# -----------------------------
# Routes
# -----------------------------
@app.get("/health")
def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        return JSONResponse(
            {"ok": False, "database": False, "ts": iso_now()},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    return {
        "ok": True,
        "database": True,
        "version": app.version,
        "ts": iso_now(),
    }


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(req: Request):
    auth = check_dashboard_auth(req)
    if auth:
        return auth
    if not DASHBOARD_TEMPLATE.is_file():
        return HTMLResponse("Dashboard-Datei fehlt.", status_code=500)
    html = DASHBOARD_TEMPLATE.read_text(encoding="utf-8").replace(
        "__REFRESH_SECONDS__",
        str(DASHBOARD_REFRESH_SECONDS),
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/dashboard/data", include_in_schema=False)
def dashboard_data(req: Request):
    auth = check_dashboard_auth(req)
    if auth:
        return auth
    return JSONResponse(dashboard_snapshot(), headers={"Cache-Control": "no-store"})


@app.post("/")
async def webhook_root(req: Request):
    auth = check_webhook_auth(req)
    if auth:
        return auth

    payload = await read_payload(req)
    headers_lower = {k.lower(): v for k, v in req.headers.items()}
    event, booking_id = extract_event_and_booking_id(payload, headers_lower)
    event_id = extract_event_id(payload, headers_lower)

    if not booking_id:
        return JSONResponse({"ok": False, "reason": "NO_BOOKING_ID", "event": event}, status_code=200)

    with ALLOCATION_LOCK:
        previous = get_processed_webhook_event(event_id)
        if previous and not previous["outcome"].get("retryable"):
            return JSONResponse(
                {
                    "ok": True,
                    "duplicate": True,
                    "event": event,
                    "event_id": event_id,
                    "booking_id": booking_id,
                    "processed_at": previous["processed_at"],
                },
                status_code=200,
            )

        if event == "bookings.updated" and not HANDLE_UPDATED:
            result: Dict[str, Any] = {
                "ok": True,
                "event": event,
                "booking_id": booking_id,
                "ignored_event": True,
                "reason": "HANDLE_UPDATED=0",
            }
        elif event in ("bookings.created", "bookings.updated", "bookings.deleted"):
            retry_windows = []
            if previous and previous["outcome"].get("retryable"):
                retry_windows = (previous["outcome"].get("redistribution") or {}).get("windows") or []
            result = process_booking_event(event, booking_id, retry_windows=retry_windows)
        else:
            result = {
                "ok": True,
                "event": event,
                "booking_id": booking_id,
                "ignored_event": True,
            }

        result["event_id"] = event_id
        retryable = bool(result.get("retryable"))
        if event_id:
            record_processed_webhook_event(event_id, event, booking_id, result)
        return JSONResponse(result, status_code=503 if retryable else 200)


@app.get("/allocations")
def allocations(req: Request):
    auth = check_dashboard_auth(req)
    if auth:
        return auth
    out = list_allocation_rows()
    return JSONResponse(
        {"ok": True, "count": len(out), "items": out},
        headers={"Cache-Control": "no-store"},
    )
