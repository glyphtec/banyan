from __future__ import annotations

from datetime import datetime
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
    topology_id: str | None = None

class GraphUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None
    topology_id: str | None = None

class GraphResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    graph_id: str
    name: str
    notes: str | None = None
    topology_id: str | None = None
    root_node_id: str | None = None
    inserted_datetime: Any = None
    updated_datetime: Any = None
    updated_by: str | None = None


class NodeCreate(BaseModel):
    source_id: str
    name: str
    notes: str | None = None
    metadata: dict = {}
    node_type_id: str | None = None

class NodeUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None
    source_id: str | None = None
    metadata: dict | None = None

class NodeResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    node_id: str
    graph_id: str
    node_type_id: str
    source_id: str
    name: str
    notes: str | None = None
    metadata: dict = {}
    inserted_datetime: Any = None
    updated_datetime: Any = None
    updated_by: str | None = None


class LinkCreate(BaseModel):
    link_type_id: str
    from_graph_id: str
    to_graph_id: str
    from_node_id: str
    to_node_id: str
    link_order: float = 0.0
    metadata: dict = {}
    valid_from_datetime: datetime | None = None
    valid_until_datetime: datetime | None = None

class LinkUpdate(BaseModel):
    link_order: float | None = None
    metadata: dict | None = None
    is_disabled: bool | None = None
    valid_from_datetime: datetime | None = None
    valid_until_datetime: datetime | None = None

class LinkResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    link_id: str
    link_type_id: str
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
    notes: str | None = None

class SnapshotRestoreRequest(BaseModel):
    new_name: str | None = None

class SnapshotHeaderResponse(BaseModel):
    """Header-only snapshot metadata — no payload. Used for list endpoints."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    snapshot_id: str
    graph_id: str
    version_label: str
    ledger_id: int
    actor_id: str
    notes: str | None = None
    inserted_datetime: Any = None


class SnapshotResponse(SnapshotHeaderResponse):
    """Full snapshot including payload. Used for create/get-single endpoints."""
    snapshot_payload: dict = {}


class ActorRegister(BaseModel):
    handle: str
    display_name: str
    actor_type: str = "HUMAN"
    org: str | None = None
    notes: str | None = None
    snapshot_payload: dict = {}


class LinkTypeCreate(BaseModel):
    name: str
    notes: str | None = None
    parent_link_type_id: str | None = None

class LinkTypeUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None

class LinkTypeResponse(BaseModel):
    link_type_id: str
    parent_link_type_id: str | None = None
    name: str
    notes: str | None = None
    is_symmetric: bool = False


class NodeTypeCreate(BaseModel):
    name: str
    notes: str | None = None

class NodeTypeUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None

class NodeTypeResponse(BaseModel):
    node_type_id: str
    name: str
    notes: str | None = None


class LedgerEntryResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    ledger_id: int
    transaction_id: str
    actor_id: str
    primitive_verb: str
    source_graph_id: str
    target_graph_id: str | None = None
    entity_id: str
    payload: dict = {}
    reversal_payload: dict = {}
    reverses_ledger_id: int | None = None
    inserted_datetime: Any = None


class ImportRequest(BaseModel):
    export_doc: dict
    new_name: str | None = None
    merge_into_graph_id: str | None = None


class CloneRequest(BaseModel):
    new_name: str


class StakeholderCreate(BaseModel):
    name: str
    org: str | None = None
    contact_ref: str | None = None
    actor_id: str | None = None
    notes: str | None = None

class StakeholderUpdate(BaseModel):
    name: str | None = None
    org: str | None = None
    contact_ref: str | None = None
    actor_id: str | None = None
    notes: str | None = None

class GraphStakeholderAttach(BaseModel):
    stakeholder_id: str
    role: str        # OWNER | WATCHER | APPROVER
    notes: str | None = None

class NodeStakeholderAttach(BaseModel):
    stakeholder_id: str
    role: str
    scope: str = "NODE_ONLY"    # NODE_ONLY | SUBGRAPH | ANCESTORS
    scope_depth: int | None = None
    scope_link_type_id: str | None = None
    notes: str | None = None


class DiffRequest(BaseModel):
    base: str | dict   # graph_id, "snapshot:<id>", or export doc
    compare: str | dict
    include_cross_graph_links: bool = False


class BatchNodeOperation(BaseModel):
    verb: str   # ADD_NODE | UPDATE_NODE | DELETE_NODE
    data: dict

class BatchLinkOperation(BaseModel):
    verb: str   # CREATE_LINK | UPDATE_LINK | DESTROY_LINK
    data: dict

class BatchRequest(BaseModel):
    # Accept graph by UUID or by name (from_graph_name mirrors the named-batch
    # file convention; graph_name is the canonical API field).
    graph_id: str | None = None
    graph_name: str | None = None
    from_graph_name: str | None = None   # named-batch alias for graph_name
    actor_id: str | None = None
    default_link_type_id: str | None = None
    default_link_type_name: str | None = None
    node_operations: list[BatchNodeOperation] = []
    link_operations: list[BatchLinkOperation] = []

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# BQL models
# ---------------------------------------------------------------------------

class BQLGraphRef(BaseModel):
    name: str | None = None
    id: str | None = None

class BQLStep(BaseModel):
    direction: str = "FROM"          # FROM | TO | WITH
    link_types: list[str] = []       # empty = all types; "NAME!" = exact match
    depth: int | None = None         # None = MAX_DEPTH_HARD
    node_types: list[str] = []
    graphs: list[str] = []           # empty = origin graph only; ["*"] = unrestricted
    collect: bool = True

class BQLResult(BaseModel):
    format: str = "LINK_NODE"        # NODE | LINK_NODE
    include_seed: bool = True
    limit: int | None = None
    verbose: bool = False

class BQLQueryRequest(BaseModel):
    graph: BQLGraphRef
    starting: dict | None = None     # NodePredicate; None = root node
    steps: list[BQLStep] | None = None  # None = default step (full traversal)
    result: BQLResult = BQLResult()

class BQLQueryResponse(BaseModel):
    success: bool
    seed_count: int
    total_count: int
    steps: list[dict] | None = None  # populated only when verbose=true
    results: list[dict]


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
                valid_from_datetime=payload.valid_from_datetime,
                valid_until_datetime=payload.valid_until_datetime,
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
                valid_from_datetime=payload.valid_from_datetime,
                valid_until_datetime=payload.valid_until_datetime,
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
        link_type_id: str | None = None,
    ):
        return service.get_subtree(graph_id, node_id, link_type_id)

    @router.get("/graphs/{graph_id}/nodes/{node_id}/ancestors")
    def get_ancestors(
        graph_id: str,
        node_id: str,
        link_type_id: str | None = None,
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
                actor_id=actor_id,
                notes=payload.notes,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/graphs/{graph_id}/snapshots", response_model=list[SnapshotHeaderResponse])
    def list_snapshots(graph_id: str):
        return service.list_snapshots(graph_id)

    @router.post("/snapshots/{snapshot_id}/restore", response_model=GraphResponse, status_code=201)
    def restore_snapshot(
        snapshot_id: str,
        body: SnapshotRestoreRequest,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.restore_snapshot(
                snapshot_id=snapshot_id,
                actor_id=actor_id,
                new_name=body.new_name,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # -- Lookup ----------------------------------------------------------------

    @router.get("/link-types", response_model=list[LinkTypeResponse])
    def get_link_types(root: str | None = None):
        result = service.get_link_types(root=root)
        if root is not None and not result:
            raise HTTPException(
                status_code=404,
                detail=f"Link type '{root}' not found.",
            )
        return result

    @router.post("/link-types", response_model=LinkTypeResponse, status_code=201)
    def create_link_type(payload: LinkTypeCreate):
        try:
            return service.create_link_type(
                name=payload.name,
                notes=payload.notes,
                parent_link_type_id=payload.parent_link_type_id,
            )
        except KeyError as exc:
            raise _not_found(exc)
        except ValueError as exc:
            raise _bad_request(exc)

    @router.patch("/link-types/{link_type_id}", response_model=LinkTypeResponse)
    def update_link_type(link_type_id: str, payload: LinkTypeUpdate):
        try:
            return service.update_link_type(
                link_type_id, name=payload.name, notes=payload.notes
            )
        except KeyError as exc:
            raise _not_found(exc)

    @router.delete("/link-types/{link_type_id}", status_code=204)
    def delete_link_type(link_type_id: str):
        try:
            service.delete_link_type(link_type_id)
        except KeyError as exc:
            raise _not_found(exc)
        except ValueError as exc:
            raise _bad_request(exc)

    @router.get("/node-types", response_model=list[NodeTypeResponse])
    def get_node_types():
        return service.get_node_types()

    @router.post("/node-types", response_model=NodeTypeResponse, status_code=201)
    def create_node_type(payload: NodeTypeCreate):
        try:
            return service.create_node_type(name=payload.name, notes=payload.notes)
        except ValueError as exc:
            raise _bad_request(exc)

    @router.patch("/node-types/{node_type_id}", response_model=NodeTypeResponse)
    def update_node_type(node_type_id: str, payload: NodeTypeUpdate):
        try:
            return service.update_node_type(
                node_type_id, name=payload.name, notes=payload.notes
            )
        except KeyError as exc:
            raise _not_found(exc)

    @router.delete("/node-types/{node_type_id}", status_code=204)
    def delete_node_type(node_type_id: str):
        try:
            service.delete_node_type(node_type_id)
        except KeyError as exc:
            raise _not_found(exc)
        except ValueError as exc:
            raise _bad_request(exc)

    # -- Actor registry --------------------------------------------------------

    @router.get("/actors")
    def list_actors():
        return service.get_actors()

    @router.get("/actors/{handle}")
    def get_actor_by_handle(handle: str):
        actor = service.get_actor_by_handle(handle)
        if actor is None:
            raise HTTPException(status_code=404, detail=f"Actor '{handle}' not found")
        return actor

    @router.post("/actors", status_code=201)
    def register_actor(body: ActorRegister):
        try:
            return service.register_actor(
                handle=body.handle,
                display_name=body.display_name,
                actor_type=body.actor_type,
                org=body.org,
                notes=body.notes,
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    # -- History / Undo --------------------------------------------------------

    @router.get("/graphs/{graph_id}/history")
    def get_graph_history(
        graph_id: str,
        since_ledger_id: int | None = None,
    ):
        return service.get_graph_history(graph_id, since_ledger_id)

    @router.get("/ledger/verify-chain")
    def verify_ledger_chain():
        """Re-compute and verify the global ledger hash chain integrity."""
        return service.verify_ledger_chain()

    @router.post("/ledger/{ledger_id}/undo", response_model=LedgerEntryResponse, status_code=201)
    def undo_ledger_entry(
        ledger_id: int,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.undo_ledger_entry(ledger_id, actor_id=actor_id)
        except KeyError as exc:
            raise _not_found(exc)
        except ValueError as exc:
            raise _bad_request(exc)

    # -- Export / Import / Diff / Batch ----------------------------------------

    @router.get("/graphs/{graph_id}/export")
    def export_graph(
        graph_id: str,
        include_cross_graph_links: bool = False,
    ):
        try:
            return service.export_graph(graph_id, include_cross_graph_links)
        except KeyError as exc:
            raise _not_found(exc)

    @router.post("/graphs/{graph_id}/clone", response_model=GraphResponse, status_code=201)
    def clone_graph(
        graph_id: str,
        body: CloneRequest,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.clone_graph(
                source_graph_id=graph_id,
                new_name=body.new_name,
                actor_id=actor_id,
            )
        except KeyError as exc:
            raise _not_found(exc)
        except ValueError as exc:
            raise _bad_request(exc)

    @router.post("/graphs/import", response_model=GraphResponse, status_code=201)
    def import_graph(
        body: ImportRequest,
        actor_id: str = Depends(get_actor),
    ):
        try:
            return service.import_graph(
                export_doc=body.export_doc,
                actor_id=actor_id,
                new_name=body.new_name,
                merge_into_graph_id=body.merge_into_graph_id,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/graphs/diff")
    def diff_graphs(body: DiffRequest):
        try:
            return service.diff_graphs(
                base=body.base,
                compare=body.compare,
                include_cross_graph_links=body.include_cross_graph_links,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/graphs/batch")
    def execute_batch(
        body: BatchRequest,
        actor_id: str = Depends(get_actor),
    ):
        batch_dict = body.model_dump(exclude_none=True)

        # ── Resolve graph name → graph_id ─────────────────────────────────
        if not batch_dict.get("graph_id"):
            gname = batch_dict.pop("graph_name", None) or batch_dict.pop("from_graph_name", None)
            if not gname:
                raise HTTPException(400, "batch requires graph_id or graph_name")
            gmap = {g["name"]: g["graph_id"] for g in service.list_graphs()}
            gid = gmap.get(gname)
            if not gid:
                raise HTTPException(400, f"Graph '{gname}' not found")
            batch_dict["graph_id"] = gid
        else:
            batch_dict.pop("graph_name", None)
            batch_dict.pop("from_graph_name", None)

        # ── Resolve default link type name → link_type_id ─────────────────
        if not batch_dict.get("default_link_type_id") and batch_dict.get("default_link_type_name"):
            lt_name = batch_dict.pop("default_link_type_name")
            ltmap = {lt["name"]: lt["link_type_id"] for lt in service.get_link_types()}
            ltid = ltmap.get(lt_name)
            if not ltid:
                raise HTTPException(400, f"Link type '{lt_name}' not found")
            batch_dict["default_link_type_id"] = ltid
        else:
            batch_dict.pop("default_link_type_name", None)

        # ── Resolve to_graph_name in link operation data ───────────────────
        graph_names_needed = {
            op["data"]["to_graph_name"]
            for op in batch_dict.get("link_operations", [])
            if "to_graph_name" in op.get("data", {})
        }
        if graph_names_needed:
            gmap2 = {g["name"]: g["graph_id"] for g in service.list_graphs()}
            missing = graph_names_needed - set(gmap2)
            if missing:
                raise HTTPException(400, f"Graphs not found: {sorted(missing)}")
            for op in batch_dict.get("link_operations", []):
                tgn = op.get("data", {}).pop("to_graph_name", None)
                if tgn:
                    op["data"]["to_graph_id"] = gmap2[tgn]

        try:
            return service.execute_batch(batch_dict, actor_id=actor_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # -- Stakeholder registry --------------------------------------------------

    @router.post("/stakeholders", status_code=201)
    def create_stakeholder(body: StakeholderCreate):
        try:
            return service.create_stakeholder(**body.model_dump())
        except ValueError as exc:
            raise _bad_request(exc)

    @router.get("/stakeholders")
    def list_stakeholders():
        return service.list_stakeholders()

    @router.get("/stakeholders/{stakeholder_id}")
    def get_stakeholder(stakeholder_id: str):
        try:
            return service.get_stakeholder(stakeholder_id)
        except KeyError as exc:
            raise _not_found(exc)

    @router.patch("/stakeholders/{stakeholder_id}")
    def update_stakeholder(stakeholder_id: str, body: StakeholderUpdate):
        try:
            return service.update_stakeholder(stakeholder_id, **body.model_dump(exclude_none=True))
        except KeyError as exc:
            raise _not_found(exc)

    @router.delete("/stakeholders/{stakeholder_id}", status_code=204)
    def delete_stakeholder(stakeholder_id: str):
        try:
            service.delete_stakeholder(stakeholder_id)
        except KeyError as exc:
            raise _not_found(exc)

    @router.post("/graphs/{graph_id}/stakeholders", status_code=204)
    def attach_graph_stakeholder(graph_id: str, body: GraphStakeholderAttach):
        try:
            service.attach_stakeholder_to_graph(
                graph_id, body.stakeholder_id, body.role, body.notes
            )
        except KeyError as exc:
            raise _not_found(exc)

    @router.delete("/graphs/{graph_id}/stakeholders/{stakeholder_id}", status_code=204)
    def detach_graph_stakeholder(graph_id: str, stakeholder_id: str):
        service.detach_stakeholder_from_graph(graph_id, stakeholder_id)

    @router.get("/graphs/{graph_id}/stakeholders")
    def list_graph_stakeholders(graph_id: str):
        try:
            return service.list_graph_stakeholders(graph_id)
        except KeyError as exc:
            raise _not_found(exc)

    @router.post("/nodes/{node_id}/stakeholders", status_code=204)
    def attach_node_stakeholder(node_id: str, body: NodeStakeholderAttach):
        try:
            service.attach_stakeholder_to_node(
                node_id, body.stakeholder_id, body.role,
                scope=body.scope, scope_depth=body.scope_depth,
                scope_link_type_id=body.scope_link_type_id, notes=body.notes,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.delete("/nodes/{node_id}/stakeholders/{stakeholder_id}", status_code=204)
    def detach_node_stakeholder(node_id: str, stakeholder_id: str):
        service.detach_stakeholder_from_node(node_id, stakeholder_id)

    @router.get("/nodes/{node_id}/stakeholders")
    def list_node_stakeholders(node_id: str):
        try:
            return service.list_node_stakeholders(node_id)
        except KeyError as exc:
            raise _not_found(exc)

    @router.get("/nodes/{node_id}/stakeholders/resolve")
    def resolve_node_stakeholders(node_id: str, graph_id: str):
        """
        Return all stakeholders with governance interest in the node,
        respecting NODE_ONLY, SUBGRAPH, ANCESTORS, and GRAPH attachment scopes.
        """
        return service.resolve_stakeholders_for_node(node_id, graph_id)

    # -- BQL query -------------------------------------------------------------

    @router.post("/query", response_model=BQLQueryResponse)
    def execute_bql_query(body: BQLQueryRequest):
        try:
            return service.execute_bql(body.model_dump(exclude_none=False))
        except KeyError as exc:
            raise _not_found(exc)
        except ValueError as exc:
            raise _bad_request(exc)

    return router
