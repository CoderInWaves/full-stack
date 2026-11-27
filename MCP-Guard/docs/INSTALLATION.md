# Installation

Use a project-local virtual environment so dependencies do not change the global Python installation. Python 3.11 or newer is required.

```bash
cd /path/to/MCP-Guard
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

For optional signed JWT support or OTLP tracing, install only the needed extra into this same environment:

```bash
python -m pip install -e '.[auth]'
python -m pip install -e '.[telemetry]'
```

If the project already has a local `venv/`, use its interpreter directly, for example `venv/bin/python -m pip install -e '.[dev]'`; this does not affect global Python. Then validate and run:

```bash
.venv/bin/mcp-guard validate-config --config examples/demo_config.yaml
.venv/bin/python examples/run_demo.py
```

See [README](../README.md) for HTTP setup, and [Configuration](CONFIGURATION.md) for JWT, mTLS, administrator, policy, and REST action settings.

## Preview the admin console

The React frontend requires Node.js 22.12 or newer. Build it into the Python package before serving it through the gateway:

```bash
cd frontend
npm install
npm run build
cd ..
```

For frontend development with Vite, run `npm run dev` in `frontend/`; the local development server proxies API requests to the gateway at `127.0.0.1:8080`. See [Frontend guide](FRONTEND.md) for complete commands and the backend feature matrix.

In one terminal:

```bash
cd /path/to/MCP-Guard
source venv/bin/activate
mcp-guard validate-config --config examples/dashboard_demo_config.yaml
mcp-guard http --config examples/dashboard_demo_config.yaml
```

Leave that terminal running and open `http://127.0.0.1:8080/admin`. Sign in with the local demo admin token `local-demo-admin-token`. This sample config is for loopback preview only; it contains public demo credentials and must not be exposed to a network. The dashboard data endpoints are protected even though the page shell is public.
