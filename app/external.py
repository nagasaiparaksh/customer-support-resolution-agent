"""Client for the external payments/shipping API, with one retry on server errors."""
import httpx

from .mock_api import mock_app

ENDPOINTS = {"refund": "/refunds", "credit": "/credits", "replace": "/replacements"}


class ExternalAPIError(Exception):
    pass


async def perform(action: str, *, order_id: str, amount: float, idempotency_key: str) -> dict:
    payload = {"order_id": order_id, "amount": amount, "idempotency_key": idempotency_key}
    transport = httpx.ASGITransport(app=mock_app)   # replace with a real base_url in production
    async with httpx.AsyncClient(transport=transport, base_url="http://payments.internal", timeout=5) as client:
        last = None
        for _ in range(2):
            try:
                r = await client.post(ENDPOINTS[action], json=payload)
                if r.is_success:
                    return r.json()
                if r.status_code < 500:                  # client error: retrying cannot help
                    raise ExternalAPIError(f"HTTP {r.status_code}: {r.text}")
                last = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last = str(e)
        raise ExternalAPIError(last or "unknown error")
