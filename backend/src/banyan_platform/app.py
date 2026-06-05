from fastapi import FastAPI

from banyan_platform.api.graphql import build_graphql_router
from banyan_platform.api.rest import build_rest_router
from banyan_platform.config import DatabaseConfig
from banyan_platform.dao.taxonomy_dao import TaxonomyDAO
from banyan_platform.persistence.connection import Database
from banyan_platform.services.taxonomy_service import TaxonomyService


def create_app(config: DatabaseConfig | None = None) -> FastAPI:
    config = config or DatabaseConfig()
    db = Database(config)
    dao = TaxonomyDAO(db, config.dialect)
    service = TaxonomyService(dao)
    service.initialize()

    app = FastAPI(title="Banyan Platform", version="0.1.0")
    app.include_router(build_rest_router(service))
    app.include_router(build_graphql_router(service), prefix="")
    return app
