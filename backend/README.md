# Backend

Layered Python backend for an embeddable taxonomy platform:

- `persistence/`: DDL and connection adapters for PostgreSQL and SQLite
- `dao/`: data access layer
- `services/`: business logic layer
- `api/rest.py`: REST exposure
- `api/graphql.py`: GraphQL exposure

Run locally:

```bash
pip install -e .[dev]
uvicorn banyan_platform.main:app --host 0.0.0.0 --port 8000
pytest
```
