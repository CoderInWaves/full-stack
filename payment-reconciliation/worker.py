
import asyncio
import json
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

MAX_ATTEMPTS = 5


async def handle_event(conn, event_type: str, payload: dict):
    if event_type == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        order = await conn.fetchrow(
            "SELECT id, amount_paise FROM orders WHERE gateway_order_id = $1 FOR UPDATE",
            payment["order_id"],
        )
        if order is None:
            raise ValueError(f"order {payment['order_id']} not found")
        if order["amount_paise"] != payment["amount"]:
            raise ValueError("amount mismatch")
        await conn.execute(
            "UPDATE orders SET status = 'paid', updated_at = now() WHERE id = $1 AND status <> 'paid'",
            order["id"],
        )

    elif event_type == "payment.failed":
        payment = payload["payload"]["payment"]["entity"]
        await conn.execute(
            "UPDATE orders SET status = 'failed', updated_at = now() "
            "WHERE gateway_order_id = $1 AND status = 'pending'",
            payment["order_id"],
        )


async def process_one(pool) -> bool:
    async with pool.acquire() as conn:
        async with conn.transaction():
            event = await conn.fetchrow(
                """
                SELECT id, event_type, payload FROM webhook_events
                WHERE (status = 'received' OR (status = 'failed' AND attempts < $1))
                  AND next_retry_at <= now()
                ORDER BY received_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                MAX_ATTEMPTS,
            )
            if event is None:
                return False

            try:
                async with conn.transaction():
                    await handle_event(conn, event["event_type"], json.loads(event["payload"]))
                await conn.execute(
                    "UPDATE webhook_events SET status = 'processed', processed_at = now() WHERE id = $1",
                    event["id"],
                )
            except Exception as e:
                await conn.execute(
                    """
                    UPDATE webhook_events
                    SET status = 'failed', attempts = attempts + 1, last_error = $2,
                        next_retry_at = now() + make_interval(secs => 30 * (attempts + 1))
                    WHERE id = $1
                    """,
                    event["id"], str(e),
                )
            return True


async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    print("Worker started")
    while True:
        if not await process_one(pool):
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
