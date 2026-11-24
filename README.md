# Payment Reconciliation

A small FastAPI service that creates Razorpay orders and reconciles payment status from signed Razorpay webhooks. The API stores incoming webhook events in PostgreSQL, and a separate worker processes them with retries.

## How it works

1. The client asks the API to create a Razorpay order.
2. Razorpay sends a signed webhook to the API.
3. The API verifies the signature, stores the event, and responds.
4. The worker updates the order for `payment.captured` or `payment.failed` events.
5. Failed processing is retried; events that reach the retry limit can be inspected and replayed through the API.

The application code and database schema are in [`payment-reconciliation/`](payment-reconciliation/).

## Requirements

- Python 3.9 or newer
- PostgreSQL
- Razorpay API credentials and a webhook secret

## Setup

Open a terminal in the application directory and create a virtual environment:

```bash
cd payment-reconciliation
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a local environment file and fill in your PostgreSQL connection string and Razorpay credentials:

```bash
cp .env.example .env
```

Apply the database schema to your PostgreSQL database:

```bash
psql "postgresql://USER:PASSWORD@HOST:PORT/DATABASE" -f schema.sql
```

Use the same database in `DATABASE_URL` in `.env`. Set `RZP_KEY_ID`, `RZP_KEY_SECRET`, and `WEBHOOK_SECRET` there as well. Configure the corresponding webhook secret in Razorpay.

## Run locally

Start the API from `payment-reconciliation/`:

```bash
uvicorn app:app --reload
```

In a second terminal, activate the virtual environment and start the worker:

```bash
cd payment-reconciliation
source .venv/bin/activate
python worker.py
```

The API listens at `http://127.0.0.1:8000`. For local webhook testing, expose that address through a tunnel and configure the Razorpay webhook URL as `https://YOUR_PUBLIC_HOST/webhook`. Subscribe to the `payment.captured` and `payment.failed` events.

## API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/orders?amount_rupees=100` | Create a Razorpay order for the given whole-rupee amount. Returns the gateway order ID, public key ID, and amount in paise. |
| `POST` | `/webhook` | Receive and verify a Razorpay webhook. |
| `GET` | `/events` | List the latest 100 webhook events. Optionally filter with `?status=failed`. |
| `POST` | `/events/{event_id}/retry` | Reset a failed event so the worker can process it again. |

Example order request:

```bash
curl -X POST "http://127.0.0.1:8000/orders?amount_rupees=100"
```

The events and retry endpoints currently have no authentication. Restrict access to them before exposing the service publicly.

## Project files

- `payment-reconciliation/app.py` — FastAPI order, webhook, event-listing, and retry endpoints.
- `payment-reconciliation/worker.py` — background event processor with retry handling.
- `payment-reconciliation/schema.sql` — PostgreSQL tables and index.
- `payment-reconciliation/flow.txt` — short processing flow overview.
- `payment-reconciliation/.env.example` — required environment variable names and sample values.
