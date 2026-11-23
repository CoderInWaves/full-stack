"""Demo backend – simple FastAPI app that simulates real API endpoints."""
import time
import random
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Demo Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_start = time.time()

PRODUCTS = [
    {"id": 1, "name": "Laptop Pro",    "price": 1299.99, "stock": 45},
    {"id": 2, "name": "Wireless Mouse","price": 29.99,   "stock": 200},
    {"id": 3, "name": "USB-C Hub",     "price": 49.99,   "stock": 150},
    {"id": 4, "name": "Monitor 4K",    "price": 599.99,  "stock": 30},
    {"id": 5, "name": "Keyboard Mech", "price": 89.99,   "stock": 75},
]

USERS = [
    {"id": "u1", "name": "Alice Johnson", "email": "alice@example.com", "plan": "premium"},
    {"id": "u2", "name": "Bob Smith",     "email": "bob@example.com",   "plan": "basic"},
    {"id": "u3", "name": "Carol White",   "email": "carol@example.com", "plan": "basic"},
]

_orders: list[dict] = []


@app.get("/api/health")
async def health():
    return {
        "status":          "healthy",
        "uptime_seconds":  round(time.time() - _start, 1),
        "service":         "demo-backend",
    }


@app.get("/api/products")
async def get_products():
    # Simulate slight processing delay
    await _fake_delay()
    return {"products": PRODUCTS, "count": len(PRODUCTS)}


@app.get("/api/users")
async def get_users():
    await _fake_delay()
    return {"users": USERS, "count": len(USERS)}


@app.post("/api/orders")
async def create_order(body: dict = None):
    await _fake_delay()
    order = {
        "id":         f"ord_{len(_orders) + 1:04d}",
        "product_id": (body or {}).get("product_id", 1),
        "quantity":   (body or {}).get("quantity", 1),
        "status":     "confirmed",
        "created_at": time.time(),
    }
    _orders.append(order)
    return {"order": order, "message": "Order created successfully"}


@app.get("/api/orders")
async def list_orders():
    await _fake_delay()
    return {"orders": _orders, "count": len(_orders)}


async def _fake_delay():
    import asyncio
    await asyncio.sleep(random.uniform(0.005, 0.020))
