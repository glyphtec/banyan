from fastapi import FastAPI

from banyan_platform.api.mcp_server import build_mcp_server
from banyan_platform.api.rest import build_rest_router
from banyan_platform.config import DatabaseConfig
from banyan_platform.persistence.connection import create_database
from banyan_platform.persistence.ddl import bootstrap
from banyan_platform.services.taxonomy_service import BanyanService


def create_app(config: DatabaseConfig | None = None) -> FastAPI:
    config = config or DatabaseConfig()
    db = create_database(config)
    bootstrap(db)

    service = BanyanService(db)

    # Build the MCP ASGI sub-app first so we can pass its lifespan to FastAPI.
    # The lifespan initialises FastMCP's session manager; without it requests fail.
    mcp_server = build_mcp_server(service)
    mcp_app = mcp_server.http_app(path="/")

    app = FastAPI(
        title="Banyan Platform",
        version="0.1.0",
        lifespan=mcp_app.lifespan,
    )
    app.include_router(build_rest_router(service))

    # MCP endpoint: /mcp/
    app.mount("/mcp", mcp_app)

    return app
