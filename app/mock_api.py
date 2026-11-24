"""A stand-in for the company's payments/shipping service.

It is a separate FastAPI app. `external.py` talks to it over real HTTP semantics (in-process),
so swapping in a real service later only means changing a base URL.
"""
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

mock_app = FastAPI(title="Mock payments & shipping")

_seen: dict[str, dict] = {}          # idempotency-key -> response
FAILING_ORDERS = {"ORD-1007"}        # lets you demo the "external API is down" path


class Request(BaseModel):
    order_id: str
    amount: float = 0.0
    idempotency_key: str


def _handle(prefix: str, body: Request, extra: dict) -> dict:
    if body.idempotency_key in _seen:          # same request twice -> same result, no double refund
        prev = _seen[body.idempotency_key]
        if prev["order_id"] != body.order_id or prev.get("amount") != extra.get("amount"):
            raise HTTPException(409, "Idempotency key reused with a different request")
        return prev
    if body.order_id in FAILING_ORDERS:
        raise HTTPException(503, "Upstream unavailable")
    resp = {"id": f"{prefix}-{uuid.uuid4().hex[:8]}", "status": "accepted", "order_id": body.order_id, **extra}
    _seen[body.idempotency_key] = resp
    return resp


@mock_app.post("/refunds")
def refund(body: Request):
    return _handle("RF", body, {"amount": body.amount})


@mock_app.post("/credits")
def credit(body: Request):
    return _handle("CR", body, {"amount": body.amount})


@mock_app.post("/replacements")
def replacement(body: Request):
    return _handle("RP", body, {})
