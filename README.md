# banyan

Taxonomy Graph Management system as Semantic MDM and AI-ready grounding system.

## Standard project structure

- `backend/src/banyan_platform/persistence`: schema DDL + PostgreSQL/SQLite connection support
- `backend/src/banyan_platform/dao`: DAO layer to isolate service logic from persistence details
- `backend/src/banyan_platform/services`: business/service logic
- `backend/src/banyan_platform/api/rest.py`: REST exposure (FastAPI)
- `backend/src/banyan_platform/api/graphql.py`: GraphQL exposure (Strawberry)
- `frontend/`: React frontend scaffold
- `Dockerfile` and `docker-compose.yml`: containerized local stack
- `backend/tests/`: persistence, DAO, service, REST, and GraphQL tests

## Quick start

### Backend

```bash
cd backend
pip install -e .[dev]
pytest
python -m uvicorn banyan_platform.main:app --host 0.0.0.0 --port 8000
```

> **Note:** Do not use `--reload`. DuckDB holds an exclusive file lock on the
> database file; `--reload` spawns a second process that immediately crashes.

API available at http://localhost:8000. Interactive docs at http://localhost:8000/docs.

### Frontend

```bash
cd frontend
npm install       # first time only
npm start
```

UI available at http://localhost:5173. Vite proxies `/api` requests to the backend.
