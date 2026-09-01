#!/usr/bin/env python3
import base64
import secrets
import os
import json
import sqlite3
import urllib.request
import urllib.error
import hashlib
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

app = FastAPI(title="Volta Pong Tischzuweisung", version="2.0.0")


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
    return http_json("GET", f"/bookings/{booking_id}?include=resource,service,customer,order")


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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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

        conn.commit()

        # 3) indexes last
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alloc_time ON allocations(start_date, end_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alloc_resource ON allocations(resource_id)")
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
        )


def upsert_allocation(a: Allocation):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO allocations (
              booking_id, booking_number, resource_id, service_id, start_date, end_date, need, tables_csv, status,
              last_patch_hash, patched_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                )
            )
    return out


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


def prefix_once(original: str, prefix: str) -> str:
    if not original:
        return prefix.strip()
    if original.startswith(prefix):
        return original
    return prefix + original


def desired_patch_fields(tables: List[str], current_description: str, split: bool) -> Dict[str, str]:
    if len(tables) == 0:
        label = ""
    elif len(tables) == 2:
        label = " & ".join(tables)
    else:
        label = ", ".join(tables)

    msg = f"{MARKER} {label}".strip()

    if MARKER in (current_description or ""):
        new_desc = current_description
    else:
        new_desc = f"{msg} — {current_description}" if current_description else msg

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
    touch_patch_meta(booking_id, h)
    return {"ok": True, "patched": True, "hash": h, "response": res}


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


def ensure_allocation_for_booking(booking_id: str, event: str) -> Dict[str, Any]:
    bj = fetch_booking(str(booking_id))
    if "errors" in bj:
        return {"ok": False, "reason": "FETCH_BOOKING_FAILED", "errors": bj["errors"]}

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
    current_note = str(attrs.get("note") or "")
    current_desc = str(attrs.get("description") or "")

    if not resource_id:
        return {"ok": False, "reason": "NO_RESOURCE_ID"}

    # RESOURCE FILTER (production-safe)
    if ALLOCATE_RESOURCE_IDS and resource_id not in ALLOCATE_RESOURCE_IDS:
        dprint(f"ignore booking_id={booking_id} resource_id={resource_id} service_id={service_id}")
        return {
            "ok": True,
            "ignored": True,
            "booking_id": str(booking_id),
            "resource_id": resource_id,
            "service_id": service_id,
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
        return {"ok": False, "reason": "MISSING_DATES"}

    need = compute_need(weight)
    window_start = parse_iso(start_date)
    window_end = parse_iso(end_date)

    existing = get_allocation(str(booking_id))

    # Prevent infinite loops: if updated and booking already contains our marker/note, skip.
    looks_ours = (MARKER in current_desc) or current_note.startswith(NOTE_PREFIX)
    if event == "bookings.updated" and existing and looks_ours:
        return {
            "ok": True,
            "skipped": True,
            "reason": "UPDATED_EVENT_LOOKS_OURS",
            "booking_id": str(booking_id),
            "tables": existing.tables,
        }

    # Reuse allocation if unchanged
    if existing and existing.status == "assigned":
        try:
            ex_s = parse_iso(existing.start_date)
            ex_e = parse_iso(existing.end_date)
        except Exception:
            ex_s, ex_e = window_start, window_end

        if ex_s == window_start and ex_e == window_end and existing.need == need and existing.tables:
            fields = desired_patch_fields(existing.tables, description, split=False)
            patch_res = patch_if_needed(str(booking_id), attrs, fields)
            return {
                "ok": True,
                "booking_id": str(booking_id),
                "booking_number": booking_number,
                "resource_id": resource_id,
                "service_id": service_id,
                "need": need,
                "tables": existing.tables,
                "reused": True,
                "patch": patch_res,
                "mode": "reused",
            }

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
        patch_res = patch_if_needed(
            str(booking_id),
            attrs,
            {"customer_note": warn, "note": warn, "description": prefix_once(description, warn + " — ")},
        )
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
                last_patch_hash=patch_res.get("hash", ""),
                patched_at=iso_now(),
            )
        )
        return {
            "ok": False,
            "reason": "NOT_ENOUGH_FREE_TABLES",
            "booking_id": str(booking_id),
            "booking_number": booking_number,
            "resource_id": resource_id,
            "service_id": service_id,
            "need": need,
            "busy": busy,
            "reconciliation": reconciliation,
            "patch": patch_res,
        }

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
        )
    )

    fields = desired_patch_fields(group, description, split=split)
    patch_res = patch_if_needed(str(booking_id), attrs, fields)

    return {
        "ok": True,
        "booking_id": str(booking_id),
        "booking_number": booking_number,
        "resource_id": resource_id,
        "service_id": service_id,
        "need": need,
        "tables": group,
        "patch": patch_res,
        "mode": mode,
        "reconciliation": reconciliation,
    }


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
    if got == WEBHOOK_SECRET:
        return None
    key = req.query_params.get("key", "")
    if key == WEBHOOK_SECRET:
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


def dashboard_snapshot(now: Optional[datetime] = None) -> Dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    raw_rows = list_allocation_rows()
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
            "last_update": newest_update,
        },
        "resources": resource_summaries,
        "current": current_public,
        "upcoming": upcoming_public,
        "issues": {
            "unassigned": [item["public"] for item in future_unassigned[:20]],
            "collisions": collisions[:20],
            "invalid_rows": invalid_rows[:20],
        },
        "configuration": {
            "tables": TABLES,
            "resource_ids": configured_resources,
            "handle_updated": HANDLE_UPDATED,
            "capacity_reconciliation": True,
        },
    }


# -----------------------------
# Routes
# -----------------------------
@app.get("/health")
def health():
    return {"ok": True, "ts": iso_now()}


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

    if not booking_id:
        return JSONResponse({"ok": False, "reason": "NO_BOOKING_ID", "event": event}, status_code=200)

    if event == "bookings.deleted":
        delete_allocation(booking_id)
        return {"ok": True, "event": event, "booking_id": booking_id, "deleted": True}

    if event == "bookings.updated" and not HANDLE_UPDATED:
        return {
            "ok": True,
            "event": event,
            "booking_id": booking_id,
            "ignored_event": True,
            "reason": "HANDLE_UPDATED=0",
        }

    if event in ("bookings.created", "bookings.updated"):
        result = ensure_allocation_for_booking(booking_id, event=event)
        result["event"] = event
        return JSONResponse(result, status_code=200)

    return {"ok": True, "event": event, "booking_id": booking_id, "ignored_event": True}


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
