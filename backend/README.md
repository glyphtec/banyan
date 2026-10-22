# Backend

Layered Python backend for an embeddable taxonomy platform. See the [project README](../README.md) for the overview.

- `persistence/`: DDL and connection adapters for DuckDB and PostgreSQL
- `dao/`: data access layer
- `services/`: business logic layer
- `api/rest.py`: REST exposure
- `api/mcp_server.py`: MCP (FastMCP) exposure for agents
- `api/agent.py`: built-in chat agent

Run locally (all commands from the `backend/` directory):

```bash
pip install -e .[dev]

# Start the API server — must be run from backend/ so the .env and data/ path resolve correctly.
# Do NOT use --reload; DuckDB file-based mode does not support multiple simultaneous writers.
cd backend/
python -m uvicorn banyan_platform.main:app --host 0.0.0.0 --port 8000

pytest
```
