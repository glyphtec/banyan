from __future__ import annotations

import uuid


def normalise_row(d: dict) -> dict:
    """
    Convert uuid.UUID values to strings for cross-backend consistency.

    DuckDB returns uuid.UUID objects for UUID columns; PostgreSQL via psycopg
    returns strings.  Normalising here means callers (service layer, Pydantic
    models) always see plain str for UUID fields.
    """
    return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in d.items()}
