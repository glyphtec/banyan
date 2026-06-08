"""
Admin API — dev/debug tooling only.

Mounted at /admin only when config.enable_admin_api is True.
NEVER expose this in production.

Endpoints
---------
GET /admin/query?sql=SELECT+...
    Execute any read SQL statement and return rows as JSON.
    Only SELECT and WITH statements are permitted; anything else is rejected.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from banyan_platform.persistence.connection import Database


_ALLOWED = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def build_admin_router(db: Database) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.get("/query")
    def run_query(sql: str = Query(..., description="Read-only SQL (SELECT / WITH only)")):
        if not _ALLOWED.match(sql):
            raise HTTPException(
                status_code=400,
                detail="Only SELECT and WITH statements are allowed.",
            )
        try:
            with db.connect() as conn:
                result = conn.execute(sql).fetchdf()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return JSONResponse(content=result.to_dict(orient="records"))

    return router
