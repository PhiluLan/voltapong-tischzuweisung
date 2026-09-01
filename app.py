#!/usr/bin/env python3
import os
import json
import sqlite3
import urllib.request
import urllib.error
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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

app = FastAPI()


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


def list_overlapping_allocations(window_start: datetime, window_end: datetime, resource_id: str) -> List[Allocation]:
    # Note: we consider only assigned allocations for busy-map
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM allocations WHERE status='assigned' AND (resource_id=? OR resource_id IS NULL OR resource_id='')",
            (resource_id,),
        ).fetchall()

    out: List[Allocation] = []
    for r in rows:
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

    # Build busy map from OUR allocations
    busy = {t: False for t in TABLES}
    overlapping = list_overlapping_allocations(window_start, window_end, resource_id=resource_id)
    for a in overlapping:
        for t in a.tables:
            if t in busy:
                busy[t] = True

    # Option B:
    # 1) adjacent-first
    group = pick_adjacent_group(need, busy)
    mode = "adjacent"
    split = False

    # 2) fallback any-free
    if not group:
        group = pick_any_free_group(need, busy)
        if group:
            mode = "any_free"
            split = True

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


# -----------------------------
# Routes
# -----------------------------
@app.get("/health")
def health():
    return {"ok": True, "ts": iso_now()}


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
def allocations():
    with db() as conn:
        rows = conn.execute("SELECT * FROM allocations ORDER BY start_date ASC").fetchall()
    out = [{k: r[k] for k in r.keys()} for r in rows]
    return {"ok": True, "count": len(out), "items": out}