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

```bash
cd backend
pip install -e .[dev]
pytest
python -m banyan_platform.main
```
