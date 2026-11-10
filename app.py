
import asyncio
import hashlib
import hmac
import json
import os
import uuid
from typing import Optional
from contextlib import asynccontextmanager

import asyncpg
import razorpay
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

load_dotenv()

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
rzp = razorpay.Client(auth=(os.environ["RZP_KEY_ID"], os.environ["RZP_KEY_SECRET"]))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    yield
    await app.state.pool.close()


app = FastAPI(lifespan=lifespan)


# 1) "Click Pay": create the order at Razorpay and save it as pending
@app.post("/orders")
async def create_order(request: Request, amount_rupees: int):
    amount_paise = amount_rupees * 100
    order = await asyncio.to_thread(
        rzp.order.create,
        {"amount": amount_paise, "currency": "INR", "receipt": f"rcpt_{uuid.uuid4().hex[:10]}"},
    )
    await request.app.state.pool.execute(
        "INSERT INTO orders (gateway_order_id, amount_paise) VALUES ($1, $2)",
        order["id"], amount_paise,
    )
    return {"order_id": order["id"], "key_id": os.environ["RZP_KEY_ID"], "amount": amount_paise}


# 2) Razorpay sends a webhook here: verify, save, reply fast
@app.post("/webhook")
async def webhook(request: Request):
    raw = await request.body()

    signature = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_id = request.headers.get("X-Razorpay-Event-Id")
    if not event_id:
        raise HTTPException(status_code=400, detail="Missing event id")

    event_type = json.loads(raw)["event"]

    await request.app.state.pool.execute(
        """
        INSERT INTO webhook_events (idempotency_key, event_type, payload)
        VALUES ($1, $2, $3)
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        event_id, event_type, raw.decode(),
    )
    return {"ok": True}


# 3) Dashboard: list events (use ?status=failed to see failures)
@app.get("/events")
async def list_events(request: Request, status: Optional[str] = None):
    rows = await request.app.state.pool.fetch(
        """
        SELECT id, idempotency_key, event_type, status, attempts, last_error, received_at
        FROM webhook_events
        WHERE ($1::text IS NULL OR status = $1)
        ORDER BY received_at DESC
        LIMIT 100
        """,
        status,
    )
    return [dict(r) for r in rows]


# 4) Replay a failed event
@app.post("/events/{event_id}/retry")
async def retry_event(request: Request, event_id: int):
    result = await request.app.state.pool.execute(
        """
        UPDATE webhook_events
        SET status = 'received', attempts = 0, last_error = NULL, next_retry_at = now()
        WHERE id = $1 AND status = 'failed'
        """,
        event_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="No failed event with this id")
    return {"ok": True}
