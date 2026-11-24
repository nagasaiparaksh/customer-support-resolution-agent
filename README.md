# Customer Support Resolution Agent

A LangGraph agent behind FastAPI that registers complaints, looks up customer data, calls an
external API, and hands anything risky to a human. Two UIs: a customer chat and a staff desk.

## Run

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # open http://localhost:8000
python -m pytest -q             # 13 tests, offline
```

Optional: set `ANTHROPIC_API_KEY` (see `.env.example`) so Claude classifies messages and phrases
replies. Without it the agent runs offline with keyword rules and templates; decisions are identical.

## Map

| File | Role |
|---|---|
| `app/graph.py` | The LangGraph: state, nodes, routing |
| `app/policy.py` | Pure business rules (refund / replace / credit / escalate) |
| `app/llm.py` | Classifier + reply writer, with offline fallback |
| `app/external.py`, `app/mock_api.py` | Client and fake payments/shipping service (idempotent) |
| `app/db.py`, `app/seed.py` | SQLite storage and demo data |
| `app/main.py` | HTTP endpoints |
| `static/` | Both UIs (vanilla JS, no build) |

## Try these

- Maya: "My ceramic pour-over set arrived cracked" -> auto refund
- Maya: "The walnut desk arrived damaged" -> escalated (over $100); resolve it from the Staff desk
- Arjun: "Something I ordered arrived broken" -> asks which order
- Tomás: "My desk lamp arrived broken" -> payment API fails -> escalated
- Lena: any damage complaint -> escalated (repeat complainer)
