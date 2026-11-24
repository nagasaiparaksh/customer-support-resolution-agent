"""SQLite storage: customers, orders, tickets (complaints) and chat messages."""
import datetime as dt
import sqlite3
from contextlib import contextmanager

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, tier TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
    item TEXT NOT NULL, amount REAL NOT NULL, status TEXT NOT NULL,
    placed_at TEXT NOT NULL, expected_at TEXT, delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY, session_id TEXT, customer_id TEXT NOT NULL REFERENCES customers(id),
    order_id TEXT, category TEXT NOT NULL, severity TEXT NOT NULL, summary TEXT NOT NULL,
    status TEXT NOT NULL, decision TEXT, reason TEXT, resolution TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, customer_id TEXT NOT NULL,
    role TEXT NOT NULL, text TEXT NOT NULL, kind TEXT, created_at TEXT NOT NULL
);
"""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conn():
    c = sqlite3.connect(settings.db_path)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


def _one(sql, args=()):
    with conn() as c:
        row = c.execute(sql, args).fetchone()
        return dict(row) if row else None


def _all(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


# ---- customers & orders -------------------------------------------------
def list_customers():
    return _all("SELECT * FROM customers ORDER BY id")


def get_customer(customer_id):
    return _one("SELECT * FROM customers WHERE id = ?", (customer_id,))


def get_orders(customer_id):
    return _all("SELECT * FROM orders WHERE customer_id = ? ORDER BY placed_at DESC", (customer_id,))


def get_order(order_id):
    return _one("SELECT * FROM orders WHERE id = ?", (order_id,))


# ---- tickets --------------------------------------------------------------
def create_ticket(*, session_id, customer_id, order_id, category, severity, summary) -> dict:
    with conn() as c:
        n = c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        tid = f"TKT-{1001 + n}"
        ts = now()
        c.execute(
            "INSERT INTO tickets (id, session_id, customer_id, order_id, category, severity, summary,"
            " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tid, session_id, customer_id, order_id, category, severity, summary, "open", ts, ts),
        )
    return get_ticket(tid)


def update_ticket(ticket_id, **fields) -> dict:
    allowed = {"status", "decision", "reason", "resolution"}
    assert set(fields) <= allowed, f"unexpected fields: {set(fields) - allowed}"
    sets = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
    with conn() as c:
        c.execute(f"UPDATE tickets SET {sets} WHERE id = ?", (*fields.values(), now(), ticket_id))
    return get_ticket(ticket_id)


def get_ticket(ticket_id):
    return _one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))


def list_tickets(status=None):
    if status:
        return _all("SELECT * FROM tickets WHERE status = ? ORDER BY created_at DESC, id DESC", (status,))
    return _all("SELECT * FROM tickets ORDER BY created_at DESC, id DESC")


def count_recent_tickets(customer_id, days=90, exclude_id=None) -> int:
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat(timespec="seconds")
    row = _one(
        "SELECT COUNT(*) AS n FROM tickets WHERE customer_id = ? AND created_at >= ? AND id != ?",
        (customer_id, cutoff, exclude_id or ""),
    )
    return row["n"]


# ---- messages -------------------------------------------------------------
def add_message(session_id, customer_id, role, text, kind=None) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO messages (session_id, customer_id, role, text, kind, created_at) VALUES (?,?,?,?,?,?)",
            (session_id, customer_id, role, text, kind, now()),
        )


def get_messages(session_id):
    return _all("SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,))
