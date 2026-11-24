"""Run with:  python -m pytest -q   (uses a temp database and the offline classifier)."""
import asyncio

import pytest

from app import db, mock_api, policy
from app.config import settings
from app.graph import agent
from app.seed import seed_if_empty


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings, "llm_provider", "none")     # tests never call a model
    mock_api._seen.clear()          # the fake external service remembers keys between tests otherwise
    db.init_db()
    seed_if_empty()


def run(customer_id, message, context=""):
    return asyncio.run(agent.ainvoke({"customer_id": customer_id, "session_id": "s1",
                                      "message": message, "context": context}))


def nodes(result):
    return [t["node"] for t in result["trace"]]


def test_damaged_under_limit_is_refunded_automatically():
    r = run("C-1001", "My ceramic pour-over set arrived cracked")
    assert r["facts"]["kind"] == "resolved" and r["facts"]["action"] == "refund"
    assert r["facts"]["amount"] == 64.00
    assert db.get_ticket(r["ticket_id"])["status"] == "resolved"
    assert "call_api" in nodes(r) and "escalate" not in nodes(r)


def test_high_value_order_is_escalated_to_a_human():
    r = run("C-1001", "The walnut desk arrived damaged")
    assert r["facts"]["kind"] == "escalated"
    assert db.get_ticket(r["ticket_id"])["status"] == "escalated"
    assert "call_api" not in nodes(r)


def test_outside_refund_window_is_escalated():
    r = run("C-1004", "The skillet is broken")
    assert r["facts"]["kind"] == "escalated"
    assert "window" in db.get_ticket(r["ticket_id"])["reason"]


def test_external_api_failure_falls_back_to_escalation():
    r = run("C-1004", "My desk lamp arrived broken")   # ORD-1007 is wired to fail in mock_api
    assert r["facts"]["kind"] == "escalated"
    assert "External API failed" in db.get_ticket(r["ticket_id"])["reason"]


def test_repeat_complainer_is_escalated():
    r = run("C-1003", "My duvet cover arrived damaged")
    assert r["facts"]["kind"] == "escalated"
    assert "tickets in the last 90 days" in db.get_ticket(r["ticket_id"])["reason"]


def test_late_in_transit_gets_credit():
    r = run("C-1002", "My earbuds are late, still waiting")
    assert r["facts"]["action"] == "credit"


def test_ambiguous_order_asks_a_question_and_creates_no_ticket():
    r = run("C-1002", "Something I ordered arrived broken")
    assert r["facts"]["kind"] == "clarify" and not r.get("ticket_id")


def test_clarification_context_is_used():
    r = run("C-1002", "the shoes", context="Something arrived broken")
    assert r["facts"]["kind"] == "resolved" and r["order"]["id"] == "ORD-1003"


def test_order_status_question_creates_no_ticket():
    r = run("C-1002", "Where is my earbuds order?")
    assert r["facts"]["kind"] == "order_status" and not r.get("ticket_id")


def test_legal_threat_escalates_even_without_an_order():
    r = run("C-1002", "I will call my lawyer about this")
    assert r["facts"]["kind"] == "escalated"


def test_vague_condition_wording_is_a_damage_complaint():
    r = run("C-1001", "My order is not in a good condition", )
    assert r["category"] == "damaged"


def test_unknown_customer():
    r = run("C-9999", "hello")
    assert r["facts"]["kind"] == "not_found"


def test_mock_api_is_idempotent_and_rejects_key_reuse():
    from fastapi.testclient import TestClient
    c = TestClient(mock_api.mock_app)
    body = {"order_id": "ORD-1001", "amount": 5.0, "idempotency_key": "k1"}
    first = c.post("/refunds", json=body).json()
    assert c.post("/refunds", json=body).json() == first          # replay, no second refund
    assert c.post("/refunds", json={**body, "order_id": "ORD-1002"}).status_code == 409


def test_policy_is_pure_and_testable():
    d = policy.decide(category="billing", severity="low", order=None, prior_tickets=0)
    assert d.action == "escalate"
