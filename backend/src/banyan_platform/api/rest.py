from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from banyan_platform.services.taxonomy_service import BanyanService


# ---------------------------------------------------------------------------
# Actor identity
# ---------------------------------------------------------------------------

def get_actor(x_actor_id: str = Header(default="anonymous")) -> str:
    """Pull actor identity from the X-Actor-Id request header."""
    return x_actor_id


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class GraphCreate(BaseModel):
    name: str
    notes: str | None = None
    topology_id: int | None = None

class GraphUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None
    topology_id: int | None = None

class GraphResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    graph_id: str
    name: str
    notes: str | None = None
    topology_id: int | None = None
    root_node_id: str | None = None
    inserted_datetime: Any = None
    updated_datetime: Any = None
    updated_by: str | None = None


class NodeCreate(BaseModel):
    source_id: str
    name: str
    notes: str | None = None
    metadata: dict = {}
    node_type_id: int | None = None

class NodeUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None
    source_id: str | None = None
    metadata: dict | None = None

class NodeResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    node_id: str
    graph_id: str
    node_type_id: int
    source_id: str
    name: str
    notes: str | None = None
    metadata: dict = {}
    inserted_datetime: Any = None
    updated_datetime: Any = None
    updated_by: str | None = None


class LinkCreate(BaseModel):
    link_type_id: int
    from_graph_id: str
    to_graph_id: str
    from_node_id: str
    to_node_id: str
    link_order: float = 0.0
    metadata: dict = {}

class LinkUpdate(BaseModel):
    link_order: float | None = None
    metadata: dict | None = None
    is_disabled: bool | None = None

class LinkResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    link_id: str
    link_type_id: int
    from_graph_id: str
    to_graph_id: str
    from_node_id: str
    to_node_id: str
    link_order: float
    metadata: dict = {}
    is_disabled: bool
    valid_from_datetime: Any = None
    valid_until_datetime: Any = None
    inserted_datetime: Any = None
    updated_datetime: Any = None
    updated_by: str | None = None


class SnapshotCreate(BaseModel):
    version_label: str
    metadata: dict = {}

class SnapshotResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    snapshot_id: str
    graph_id: str
    version_label: str
    ledger_id: int
    actor_id: str
    snapshot_metadata: dict = {}
    inserted_datetime: Any = None


# ---------------------------------------------------------------------------
# Exception mapping
# ---------------------------------------------------------------------------

def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))

def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def build_rest_router(service: BanyanService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["banyan"])

    # -- Graphs ----------------------------------------------------------------

    @router.post("/graphs", response_model=GraphResponse, status_code=201)
    def create_graph(payload: GraphCreate, actor_id: str = Depends(get_actor)):
        return service.create_graph(
            name=payload.name, notes=payload.notes,
            topology_id=payload.topology_id, actor_id=actor_id,
        )

    @router.get("/graphs", response_model=list[GraphResponse])
    def list_graphs():
        return service.list_graphs()

    @router.get("/graphs/{graph_id}", response_model=GraphResponse)
    def get_graph(graph_id: str):
        try:
            return service.get_graph(graph_id)
        except KeyError as exc:
            raise _not_found(exc)

    @router.patch("/graphs/{graph_id}", response_model=GraphResponse)
    def update_graph(
        graph_id: str,
        payload: GraphUpdate,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.update_graph(
                graph_id, actor_id=actor_id,
                name=payload.name, notes=payload.notes,
                topology_id=payload.topology_id,
            )
        except KeyError as exc:
            raise _not_found(exc)

    @router.delete("/graphs/{graph_id}", status_code=204)
    def delete_graph(graph_id: str, actor_id: str = Depends(get_actor)):
        try:
            service.delete_graph(graph_id, actor_id=actor_id)
        except KeyError as exc:
            raise _not_found(exc)
        except ValueError as exc:
            raise _bad_request(exc)

    # -- Nodes -----------------------------------------------------------------

    @router.post("/graphs/{graph_id}/nodes", response_model=NodeResponse, status_code=201)
    def add_node(
        graph_id: str,
        payload: NodeCreate,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.add_node(
                graph_id=graph_id,
                source_id=payload.source_id,
                name=payload.name,
                notes=payload.notes,
                metadata=payload.metadata,
                node_type_id=payload.node_type_id,
                actor_id=actor_id,
            )
        except KeyError as exc:
            raise _not_found(exc)

    @router.get("/graphs/{graph_id}/nodes", response_model=list[NodeResponse])
    def list_nodes(graph_id: str):
        return service.list_nodes(graph_id)

    @router.get("/nodes/{node_id}", response_model=NodeResponse)
    def get_node(node_id: str):
        try:
            return service.get_node(node_id)
        except KeyError as exc:
            raise _not_found(exc)

    @router.patch("/nodes/{node_id}", response_model=NodeResponse)
    def update_node(
        node_id: str,
        payload: NodeUpdate,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.update_node(
                node_id, actor_id=actor_id,
                name=payload.name, notes=payload.notes,
                source_id=payload.source_id, metadata=payload.metadata,
            )
        except KeyError as exc:
            raise _not_found(exc)

    @router.delete("/nodes/{node_id}", status_code=200)
    def delete_node(
        node_id: str,
        force: bool = False,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.delete_node(node_id, actor_id=actor_id, force=force)
        except KeyError as exc:
            raise _not_found(exc)
        except ValueError as exc:
            raise _bad_request(exc)

    # -- Links -----------------------------------------------------------------

    @router.post("/links", response_model=LinkResponse, status_code=201)
    def create_link(payload: LinkCreate, actor_id: str = Depends(get_actor)):
        try:
            return service.create_link(
                link_type_id=payload.link_type_id,
                from_graph_id=payload.from_graph_id,
                to_graph_id=payload.to_graph_id,
                from_node_id=payload.from_node_id,
                to_node_id=payload.to_node_id,
                link_order=payload.link_order,
                metadata=payload.metadata,
                actor_id=actor_id,
            )
        except ValueError as exc:
            raise _bad_request(exc)

    @router.get("/links/{link_id}", response_model=LinkResponse)
    def get_link(link_id: str):
        try:
            return service.get_link(link_id)
        except KeyError as exc:
            raise _not_found(exc)

    @router.patch("/links/{link_id}", response_model=LinkResponse)
    def update_link(
        link_id: str,
        payload: LinkUpdate,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.update_link(
                link_id, actor_id=actor_id,
                link_order=payload.link_order,
                metadata=payload.metadata,
                is_disabled=payload.is_disabled,
            )
        except KeyError as exc:
            raise _not_found(exc)

    @router.delete("/links/{link_id}", status_code=204)
    def destroy_link(link_id: str, actor_id: str = Depends(get_actor)):
        try:
            service.destroy_link(link_id, actor_id=actor_id)
        except KeyError as exc:
            raise _not_found(exc)

    # -- Traversal (read-only) -------------------------------------------------

    @router.get("/graphs/{graph_id}/nodes/{node_id}/subtree")
    def get_subtree(
        graph_id: str,
        node_id: str,
        link_type_id: int | None = None,
    ):
        return service.get_subtree(graph_id, node_id, link_type_id)

    @router.get("/graphs/{graph_id}/nodes/{node_id}/ancestors")
    def get_ancestors(
        graph_id: str,
        node_id: str,
        link_type_id: int | None = None,
    ):
        return service.get_ancestors(graph_id, node_id, link_type_id)

    @router.get("/graphs/{graph_id}/nodes/{node_id}/impact")
    def get_impact_summary(graph_id: str, node_id: str):
        return service.get_impact_summary(graph_id, node_id)

    # -- Snapshots -------------------------------------------------------------

    @router.post("/graphs/{graph_id}/snapshots", response_model=SnapshotResponse, status_code=201)
    def create_snapshot(
        graph_id: str,
        payload: SnapshotCreate,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.create_snapshot(
                graph_id=graph_id,
                version_label=payload.version_label,
                metadata=payload.metadata,
                actor_id=actor_id,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/graphs/{graph_id}/snapshots", response_model=list[SnapshotResponse])
    def list_snapshots(graph_id: str):
        return service.list_snapshots(graph_id)

    # -- Lookup ----------------------------------------------------------------

    @router.get("/link-types")
    def get_link_types():
        return service.get_link_types()

    @router.get("/node-types")
    def get_node_types():
        return service.get_node_types()

    # -- History ---------------------------------------------------------------

    @router.get("/graphs/{graph_id}/history")
    def get_graph_history(
        graph_id: str,
        since_ledger_id: int | None = None,
    ):
        return service.get_graph_history(graph_id, since_ledger_id)

    return router
