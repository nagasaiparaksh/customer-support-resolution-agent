"""HTTP layer. FastAPI receives requests, runs the graph, and exposes data for the two UIs."""
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, llm
from .external import ExternalAPIError, perform
from .graph import agent
from .seed import seed_if_empty

STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    seed_if_empty()
    yield


app = FastAPI(title="Customer Support Resolution Agent", lifespan=lifespan)


class ChatIn(BaseModel):
    customer_id: str
    message: str = Field(min_length=1, max_length=1000)
    session_id: str | None = None


class ResolveIn(BaseModel):
    outcome: str = Field(pattern="^(refund|replace|credit|decline)$")
    amount: float = Field(default=0.0, ge=0)
    note: str = Field(min_length=1, max_length=500)


@app.get("/api/status")
def status():
    return {"llm": "claude" if llm.enabled() else "offline rules", "model": llm_model()}


def llm_model():
    from .config import settings
    return settings.model if llm.enabled() else None


@app.get("/api/customers")
def customers():
    return [{**c, "orders": db.get_orders(c["id"])} for c in db.list_customers()]


@app.get("/api/graph")
def graph_shape():
    g = agent.get_graph()
    return {"nodes": [n for n in g.nodes],
            "edges": [{"from": e.source, "to": e.target, "conditional": e.conditional} for e in g.edges]}


@app.post("/api/chat")
async def chat(body: ChatIn):
    customer = db.get_customer(body.customer_id)
    if not customer:
        raise HTTPException(404, "Unknown customer")
    session_id = body.session_id or uuid.uuid4().hex[:8]
    history = db.get_messages(session_id)
    if any(m["customer_id"] != body.customer_id for m in history):
        raise HTTPException(403, "Session belongs to another customer")

    # If we just asked "which order?", the previous customer message is still part of the problem.
    context = ""
    if history and history[-1]["kind"] == "clarify":
        context = next((m["text"] for m in reversed(history) if m["role"] == "customer"), "")

    db.add_message(session_id, body.customer_id, "customer", body.message)
    result = await agent.ainvoke({"customer_id": body.customer_id, "session_id": session_id,
                                  "message": body.message, "context": context})
    db.add_message(session_id, body.customer_id, "agent", result["reply"], result["facts"]["kind"])
    ticket = db.get_ticket(result["ticket_id"]) if result.get("ticket_id") else None
    return {"session_id": session_id, "reply": result["reply"], "kind": result["facts"]["kind"],
            "trace": result["trace"], "ticket": ticket}


@app.get("/api/sessions/{session_id}/messages")
def session_messages(session_id: str):
    return db.get_messages(session_id)


@app.get("/api/tickets")
def tickets(status: str | None = None):
    rows = db.list_tickets(status)
    names = {c["id"]: c["name"] for c in db.list_customers()}
    return [{**t, "customer_name": names.get(t["customer_id"])} for t in rows]


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: str):
    t = db.get_ticket(ticket_id)
    if not t:
        raise HTTPException(404, "Unknown ticket")
    return {**t, "customer": db.get_customer(t["customer_id"]),
            "order": db.get_order(t["order_id"]) if t["order_id"] else None,
            "messages": db.get_messages(t["session_id"]) if t["session_id"] else []}


@app.post("/api/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: str, body: ResolveIn):
    """The human half of the handoff: a staff member closes an escalated ticket."""
    t = db.get_ticket(ticket_id)
    if not t:
        raise HTTPException(404, "Unknown ticket")
    if t["status"] != "escalated":
        raise HTTPException(409, f"Ticket is {t['status']}, not escalated")
    if body.outcome != "decline":
        if not t["order_id"]:
            raise HTTPException(422, "This ticket has no order to act on")
        try:
            await perform(body.outcome, order_id=t["order_id"], amount=body.amount,
                          idempotency_key=f"{ticket_id}:human:{body.outcome}")
        except ExternalAPIError as e:
            raise HTTPException(502, f"External API failed: {e}")
    resolution = f"{body.outcome} by staff: {body.note}"
    updated = db.update_ticket(ticket_id, status="resolved", resolution=resolution)
    if t["session_id"]:
        db.add_message(t["session_id"], t["customer_id"], "human", body.note, "human_resolution")
    return updated


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
