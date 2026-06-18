"""
Admin API — dev/debug tooling only.

Mounted at /admin only when config.enable_admin_api is True.
NEVER expose this in production.

Endpoints
---------
GET  /admin/query?sql=SELECT+...
    Execute any read SQL statement and return rows as JSON.
    Only SELECT and WITH statements are permitted; anything else is rejected.

GET  /admin/graphs
    List all graphs (id, name, node count).

DELETE /admin/graphs/{graph_id}
    Purge a single graph with prejudice — all nodes, links, ledger entries,
    and snapshots are hard-deleted in one transaction.

DELETE /admin/graphs
    Purge ALL graphs.  Returns a list of per-graph purge summaries.
    Requires the query param ?confirm=yes as a speed bump.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from banyan_platform.persistence.connection import Database

if TYPE_CHECKING:
    from banyan_platform.services.taxonomy_service import BanyanService


_ALLOWED = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def build_admin_router(db: Database, service: "BanyanService") -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    # ── Raw SQL backdoor ──────────────────────────────────────────────────────

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

        # Use pandas to_json() with default_handler=str so that UUID objects,
        # timestamps and any other non-primitive DuckDB types are safely coerced
        # to strings rather than causing ujson byte-level decode errors.
        return Response(
            content=result.to_json(orient="records", date_format="iso", default_handler=str),
            media_type="application/json",
        )

    # ── Graph listing ─────────────────────────────────────────────────────────

    @router.get("/graphs")
    def list_graphs():
        """Return all graphs with a live node count."""
        graphs = service.list_graphs()
        p = db.placeholder
        result = []
        with db.connect() as conn:
            for g in graphs:
                cur = conn.execute(
                    f"SELECT COUNT(*) FROM node WHERE graph_id = {p}",
                    [g["graph_id"]],
                )
                node_count = cur.fetchone()[0]
                result.append({
                    "graph_id": g["graph_id"],
                    "name": g["name"],
                    "node_count": node_count,
                    "inserted_datetime": str(g.get("inserted_datetime", "")),
                })
        return result

    # ── Purge single graph ────────────────────────────────────────────────────

    @router.delete("/graphs/{graph_id}")
    def purge_graph(graph_id: str):
        """Hard-delete a graph and all its content (dev only)."""
        try:
            summary = service.purge_graph(graph_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return summary

    # ── Purge ALL graphs ──────────────────────────────────────────────────────

    @router.delete("/graphs")
    def purge_all_graphs(confirm: str = Query(default="", description="Pass 'yes' to confirm")):
        """Hard-delete every graph.  Requires ?confirm=yes."""
        if confirm.lower() != "yes":
            raise HTTPException(
                status_code=400,
                detail="Pass ?confirm=yes to purge all graphs.",
            )
        graphs = service.list_graphs()
        summaries = []
        for g in graphs:
            try:
                summaries.append(service.purge_graph(g["graph_id"]))
            except KeyError:
                pass  # already gone (race); skip
        return {"purged": len(summaries), "details": summaries}

    return router
