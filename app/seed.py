"""Demo data. Dates are relative to 'now' so refund-window rules behave the same any day."""
import datetime as dt

from . import db


def _ago(days: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat(timespec="seconds")


def seed_if_empty() -> None:
    if db.list_customers():
        return
    with db.conn() as c:
        c.executemany(
            "INSERT INTO customers VALUES (?,?,?,?)",
            [
                ("C-1001", "Maya Fernandez", "maya@example.com", "gold"),
                ("C-1002", "Arjun Rao", "arjun@example.com", "standard"),
                ("C-1003", "Lena Okafor", "lena@example.com", "standard"),
                ("C-1004", "Tomás Reyes", "tomas@example.com", "standard"),
            ],
        )
        # id, customer, item, amount, status, placed, expected, delivered
        c.executemany(
            "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)",
            [
                ("ORD-1001", "C-1001", "Ceramic pour-over set", 64.00, "delivered", _ago(9), _ago(6), _ago(5)),
                ("ORD-1002", "C-1001", "Walnut standing desk", 489.00, "delivered", _ago(14), _ago(10), _ago(9)),
                ("ORD-1003", "C-1002", "Trail running shoes", 92.50, "delivered", _ago(7), _ago(4), _ago(3)),
                ("ORD-1004", "C-1002", "Noise-cancelling earbuds", 129.00, "in_transit", _ago(12), _ago(8), None),
                ("ORD-1005", "C-1003", "Linen duvet cover", 78.00, "delivered", _ago(18), _ago(15), _ago(14)),
                ("ORD-1006", "C-1004", "Cast-iron skillet", 45.00, "delivered", _ago(55), _ago(51), _ago(50)),
                ("ORD-1007", "C-1004", "Desk lamp", 38.00, "delivered", _ago(5), _ago(3), _ago(2)),
            ],
        )
        # Lena already has three recent tickets -> triggers the repeat-complaint rule.
        for i, days in enumerate((20, 40, 60)):
            c.execute(
                "INSERT INTO tickets (id, session_id, customer_id, order_id, category, severity, summary,"
                " status, decision, resolution, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"TKT-{900 + i}", None, "C-1003", None, "late", "low", "Earlier delivery delay",
                 "resolved", "credit", "Goodwill credit issued", _ago(days), _ago(days)),
            )
