from fastapi import FastAPI

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

    app = FastAPI(title="Banyan Platform", version="0.1.0")
    app.include_router(build_rest_router(service))
    return app
