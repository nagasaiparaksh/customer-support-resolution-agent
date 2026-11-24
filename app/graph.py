"""The LangGraph agent.

    load_customer -> classify -> resolve_order -+-> answer_status ----------------------+
                                                +-> register_complaint -> decide -+     |
                                                +-> (clarify / other) -------+    |     |
                                                                            |    |     |
                                         escalate <--- (escalate) ----------+----+     |
                                         call_api <--- (refund/replace/credit)         |
                                            |-> resolve_ticket                          |
                                            '-> escalate (API failed)                   |
                                         respond <--------------------------------------'

State is a dict every node reads and updates. Each node returns only the keys it changes;
`trace` uses an `add` reducer so entries accumulate instead of overwriting.
"""
import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from . import db, llm, policy
from .external import ExternalAPIError, perform


class State(TypedDict, total=False):
    # inputs
    customer_id: str
    session_id: str
    message: str
    context: str                 # previous customer message when we had asked a clarifying question
    # working data
    customer: dict | None
    orders: list[dict]
    intent: str
    category: str
    severity: str
    mentioned_order_id: str | None
    summary: str
    classified_by: str
    order: dict | None
    ticket_id: str | None
    decision: dict | None
    api_result: dict | None
    # outputs
    facts: dict
    reply: str
    trace: Annotated[list, operator.add]


def traced(name):
    """Wrap a node: time it, pull out its `_summary`, and append a trace entry."""
    def deco(fn):
        async def wrapper(state: State):
            start = time.perf_counter()
            update = await fn(state)
            summary = update.pop("_summary", "")
            update["trace"] = [{"node": name, "summary": summary,
                                "ms": round((time.perf_counter() - start) * 1000)}]
            return update
        wrapper.node_name = name
        return wrapper
    return deco


# ------------------------------------------------------------------- nodes
@traced("load_customer")
async def load_customer(state: State):
    customer = db.get_customer(state["customer_id"])
    orders = db.get_orders(state["customer_id"]) if customer else []
    return {"customer": customer, "orders": orders,
            "_summary": f"{customer['name']} ({customer['tier']}), {len(orders)} orders" if customer else "not found"}


@traced("classify")
async def classify(state: State):
    fields, source = llm.classify(state["message"], state.get("context", ""), state["orders"])
    return {"intent": fields["intent"], "category": fields["category"], "severity": fields["severity"],
            "mentioned_order_id": fields["order_id"], "summary": fields["summary"], "classified_by": source,
            "_summary": f"{fields['intent']} / {fields['category']} / severity {fields['severity']} (via {source})"}


@traced("resolve_order")
async def resolve_order(state: State):
    orders = state["orders"]
    order = next((o for o in orders if o["id"] == state.get("mentioned_order_id")), None)
    how = "mentioned by customer"
    if order is None and len(orders) == 1:
        order, how = orders[0], "customer's only order"
    return {"order": order,
            "_summary": f"{order['id']} {order['item']} ({how})" if order else "no order identified"}


@traced("answer_status")
async def answer_status(state: State):
    o = state.get("order")
    if o:
        return {"facts": {"kind": "order_status", "order": o}, "_summary": f"status = {o['status']}"}
    return {"facts": {"kind": "clarify", "orders": state["orders"]}, "_summary": "which order? asking customer"}


@traced("register_complaint")
async def register_complaint(state: State):
    t = db.create_ticket(session_id=state["session_id"], customer_id=state["customer_id"],
                         order_id=state["order"]["id"] if state.get("order") else None,
                         category=state["category"], severity=state["severity"], summary=state["summary"])
    return {"ticket_id": t["id"], "_summary": f"created {t['id']}"}


@traced("decide")
async def decide(state: State):
    prior = db.count_recent_tickets(state["customer_id"], exclude_id=state["ticket_id"])
    d = policy.decide(category=state["category"], severity=state["severity"],
                      order=state.get("order"), prior_tickets=prior)
    db.update_ticket(state["ticket_id"], decision=d.action, reason=d.reason)
    return {"decision": d.__dict__,
            "_summary": f"{d.action}" + (f" ${d.amount:.2f}" if d.amount else "") + f": {d.reason}"}


@traced("call_api")
async def call_api(state: State):
    d, order = state["decision"], state["order"]
    key = f"{state['ticket_id']}:{d['action']}"        # same ticket+action => safe to retry
    try:
        result = await perform(d["action"], order_id=order["id"], amount=d["amount"], idempotency_key=key)
        return {"api_result": result, "_summary": f"{d['action']} accepted, ref {result['id']}"}
    except ExternalAPIError as e:
        return {"api_result": None,
                "decision": {**d, "action": "escalate", "reason": f"External API failed ({e})",
                             "public_reason": "We hit a technical problem completing this automatically."},
                "_summary": f"API failed ({e}) -> escalating"}


@traced("resolve_ticket")
async def resolve_ticket(state: State):
    d, ref = state["decision"], state["api_result"]["id"]
    db.update_ticket(state["ticket_id"], status="resolved", resolution=f"{d['action']} via agent ({ref})")
    return {"facts": {"kind": "resolved", "action": d["action"], "amount": d["amount"], "reference": ref,
                      "order": state["order"], "ticket_id": state["ticket_id"]},
            "_summary": f"{state['ticket_id']} resolved"}


@traced("escalate")
async def escalate(state: State):
    d = state["decision"]
    db.update_ticket(state["ticket_id"], status="escalated", decision="escalate", reason=d["reason"])
    return {"facts": {"kind": "escalated", "ticket_id": state["ticket_id"], "public_reason": d["public_reason"]},
            "_summary": f"{state['ticket_id']} handed to a human: {d['reason']}"}


@traced("respond")
async def respond(state: State):
    facts = state.get("facts")
    if not state.get("customer"):
        facts = {"kind": "not_found"}
    elif not facts:
        # complaint without an identifiable order, or small talk
        facts = ({"kind": "clarify", "orders": state["orders"]} if state["intent"] == "complaint"
                 else {"kind": "other"})
    facts = {**facts, "first_name": (state.get("customer") or {}).get("name", "").split(" ")[0] or "there"}
    reply, source = llm.write_reply(facts)
    return {"facts": facts, "reply": reply, "_summary": f"{facts['kind']} reply (via {source})"}


# ------------------------------------------------------------------ routing
def after_load(state: State):
    return "classify" if state.get("customer") else "respond"


def after_classify(state: State):
    return "resolve_order" if state["intent"] in ("complaint", "order_status") else "respond"


def after_resolve_order(state: State):
    if state["intent"] == "order_status":
        return "answer_status"
    # a complaint needs an order, unless it is something a human must see anyway
    if state.get("order") or state["severity"] == "high":
        return "register_complaint"
    return "respond"


def after_decide(state: State):
    return "escalate" if state["decision"]["action"] == "escalate" else "call_api"


def after_call_api(state: State):
    return "escalate" if state["decision"]["action"] == "escalate" else "resolve_ticket"


def build_graph():
    g = StateGraph(State)
    for node in (load_customer, classify, resolve_order, answer_status, register_complaint,
                 decide, call_api, resolve_ticket, escalate, respond):
        g.add_node(node.node_name, node)
    g.add_edge(START, "load_customer")
    g.add_conditional_edges("load_customer", after_load, ["classify", "respond"])
    g.add_conditional_edges("classify", after_classify, ["resolve_order", "respond"])
    g.add_conditional_edges("resolve_order", after_resolve_order,
                            ["answer_status", "register_complaint", "respond"])
    g.add_edge("answer_status", "respond")
    g.add_edge("register_complaint", "decide")
    g.add_conditional_edges("decide", after_decide, ["escalate", "call_api"])
    g.add_conditional_edges("call_api", after_call_api, ["escalate", "resolve_ticket"])
    g.add_edge("resolve_ticket", "respond")
    g.add_edge("escalate", "respond")
    g.add_edge("respond", END)
    return g.compile()


agent = build_graph()
